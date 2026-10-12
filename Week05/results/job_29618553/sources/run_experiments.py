#!/usr/bin/env python3
"""Sequential, allocation-only MPI experiments; JSON syntax is a YAML subset."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
FIELDS = ['experiment', 'implementation', 'repetition', 'nodes', 'ranks',
          'ranks_per_host', 'chunk_size', 'width', 'height', 'target_area',
          'actual_area', 'runtime_seconds', 'exit_status', 'stdout_log', 'stderr_log']
CONFIG_FIELDS = FIELDS[:11]


def read_config(path=HERE / 'experiments.yaml'):
    return json.loads(Path(path).read_text())


def configurations(config):
    d = config['defaults']
    e = config['experiments']
    chunks = [max(1, d['width'] // (d['ranks'] * x)) for x in e['chunk_size']['divisors']]
    if chunks != e['chunk_size']['values']:
        raise ValueError('Chunk values disagree with the agreed formula')
    area = e['image_area']
    targets = [area['minimum'] + i * (area['maximum'] - area['minimum']) / (area['count'] - 1)
               for i in range(area['count'])]
    sides = [math.floor(math.sqrt(a) + 0.5) for a in targets]
    if sides != area['sides']:
        raise ValueError('Image sides disagree with target areas')
    rows = []
    for experiment, values in [('nodes', e['nodes']['values']), ('chunk_size', chunks),
                               ('image_area', list(zip(targets, sides)))]:
        for value in values:
            nodes = value if experiment == 'nodes' else d['nodes']
            chunk = value if experiment == 'chunk_size' else d['chunk_size']
            target, width = value if experiment == 'image_area' else (d['width'] * d['height'], d['width'])
            height = width if experiment == 'image_area' else d['height']
            if d['ranks'] % nodes:
                raise ValueError('Ranks must divide evenly over hosts')
            for implementation in config['implementations']:
                rows.append(dict(experiment=experiment, implementation=implementation,
                                 nodes=nodes, ranks=d['ranks'], ranks_per_host=d['ranks'] // nodes,
                                 chunk_size=chunk, width=width, height=height,
                                 target_area=target, actual_area=width * height))
    return rows


def measurements(config):
    rng = random.Random(config['defaults']['seed'])
    result = []
    for repetition in range(1, config['defaults']['repetitions'] + 1):
        round_rows = configurations(config)
        rng.shuffle(round_rows)
        result.extend(dict(row, repetition=repetition) for row in round_rows)
    return result


def allocation(env, config):
    """Preserve LSF host order, including the host that will receive rank zero."""
    slots = Counter()
    if env.get('LSB_MCPU_HOSTS'):
        parts = env['LSB_MCPU_HOSTS'].split()
        if len(parts) % 2:
            raise ValueError('Malformed LSB_MCPU_HOSTS')
        for host, count in zip(parts[::2], parts[1::2]):
            slots[host] += int(count)
    elif env.get('LSB_HOSTS'):
        slots.update(env['LSB_HOSTS'].split())
    else:
        raise ValueError('No LSF allocation: submit the batch script')
    c = config['cluster']
    if len(slots) != c['hosts'] or any(n != c['slots_per_host'] for n in slots.values()):
        raise ValueError(f'Need exactly eight distinct hosts with four slots each; got {dict(slots)}')
    return slots


def mpi_command(hostfile, row, program, arguments):
    return ['mpirun', '-np', str(row['ranks']), '--hostfile', str(hostfile),
            '--map-by', f"ppr:{row['ranks_per_host']}:node", '--rank-by', 'slot',
            '--bind-to', 'core', '--nooversubscribe', '--report-bindings',
            sys.executable, str(program), *map(str, arguments)]


def timed_command(command, stdout, stderr, timeout):
    """Time launch through exit; terminate the MPI launcher group on timeout."""
    with open(stdout, 'w') as out, open(stderr, 'w') as err:
        start = time.monotonic()
        try:
            process = subprocess.Popen(command, stdout=out, stderr=err, start_new_session=True)
        except OSError as exc:
            err.write(str(exc) + '\n')
            return time.monotonic() - start, 127
        try:
            status = process.wait(timeout=max(0.01, timeout))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            err.write('Experiment time budget exceeded\n')
            status = 124
        return time.monotonic() - start, status


def check_probe(records, hosts, ranks_per_host, model=None, expected_model=None, expected_mpi=None):
    if len(records) != 8 or sorted(r['rank'] for r in records) != list(range(8)):
        raise ValueError('Probe did not report eight distinct ranks')
    models = {r['cpu_model'] for r in records}
    if len(models) != 1 or not next(iter(models)):
        raise ValueError('Every allocated host must use the same CPU model')
    detected_model = next(iter(models))
    if model and model not in detected_model:
        raise ValueError(f'Unexpected CPU model: {detected_model}')
    if expected_model is not None and detected_model != expected_model:
        raise ValueError('CPU model changed between placement probes')
    if expected_mpi is not None:
        libraries = {r.get('mpi_library_version', '') for r in records}
        if len(libraries) != 1 or not next(iter(libraries)).startswith(f'Open MPI v{expected_mpi},'):
            raise ValueError(f'Every rank must use Open MPI {expected_mpi}')
    short = lambda host: host.split('.')[0]
    expected = [short(host) for host in hosts for _ in range(ranks_per_host)]
    cores = set()
    for r in records:
        if short(r['host']) != expected[r['rank']]:
            raise ValueError(f'Unexpected placement: {r}')
        # SMT siblings can share one physical core; different ranks must not.
        if not r['affinity'] or len(r['physical_cores']) != 1:
            raise ValueError(f'Rank must be bound to one physical core: {r}')
        key = (short(r['host']), tuple(r['physical_cores'][0]))
        if key in cores:
            raise ValueError('Two ranks share a physical core')
        cores.add(key)
    return detected_model


def estimated_seconds(config, pilots):
    """Estimate startup plus area-dependent compute from two pilot sizes."""
    small_side, baseline_side = sorted(config['pilot']['sides'])
    small_area, baseline_area = small_side ** 2, baseline_side ** 2
    times = {(p['implementation'], p['width']): p['runtime_seconds'] for p in pilots}
    total = 0
    for row in measurements(config):
        small = times[row['implementation'], small_side]
        baseline = times[row['implementation'], baseline_side]
        per_pixel = max(0, (baseline - small) / (baseline_area - small_area))
        startup = max(0, small - per_pixel * small_area)
        total += max(small, startup + per_pixel * row['actual_area'])
    return total * config['pilot']['allowance_factor']


def run(config, result_dir):
    if not os.environ.get('LSB_JOBID'):
        raise ValueError('Measurements require an LSF batch allocation')
    started = time.monotonic()
    slots = allocation(os.environ, config)
    hosts = list(slots)
    for key, value in config['cluster']['env'].items():
        os.environ[key] = value
    result_dir.mkdir(parents=True, exist_ok=False)
    logs = result_dir / 'logs'
    logs.mkdir()
    batch_start = float(os.environ.get('EXPERIMENT_BATCH_START', time.time()))
    initial_remaining = config['cluster']['walltime_seconds'] - (time.time() - batch_start)
    reserve = config['pilot']['analysis_reserve_seconds']
    remaining = lambda: initial_remaining - (time.monotonic() - started) - reserve
    paths = [HERE / name for name in config['implementations'].values()]
    paths += [Path(__file__), HERE / 'mpi_probe.py', HERE / 'plot_experiments.py', HERE / 'publish_results.py', HERE / 'experiments_job.sh', HERE / 'test_experiments.py', HERE / 'vendor' / 'six.py']
    metadata = dict(job_id=os.environ['LSB_JOBID'], started_utc=datetime.now(timezone.utc).isoformat(),
                    hosts=hosts, allocated_slots=dict(slots), configuration=config,
                    seed=config['defaults']['seed'], python=sys.version,
                    modules=os.environ.get('LOADEDMODULES', '').split(':'),
                    versions={p: importlib.metadata.version(p) for p in ['numpy', 'mpi4py', 'matplotlib']},
                    source_hashes={str(p.name): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                    pilots=[], probes={}, launcher_stress=[], status='preflight', commands=[])
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=HERE,
                              text=True, capture_output=True, check=False)
    metadata['git_commit'] = revision.stdout.strip() if revision.returncode == 0 else None
    sources = result_dir / 'sources'
    sources.mkdir()
    for path in paths:
        destination = sources / path.relative_to(HERE)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
    (result_dir / 'experiments.yaml').write_text(json.dumps(config, indent=2) + '\n')
    def save():
        tmp = result_dir / 'metadata.json.tmp'
        tmp.write_text(json.dumps(metadata, indent=2) + '\n')
        tmp.replace(result_dir / 'metadata.json')
    save()
    hostfiles = {}
    for nodes in [2, 4, 8]:
        path = result_dir / f'hosts_{nodes}.txt'
        path.write_text(''.join(f'{host} slots=4 max_slots=4\n' for host in hosts[:nodes]))
        hostfiles[nodes] = path
    def attempt(label, row, program, arguments):
        out, err = logs / f'{label}.out', logs / f'{label}.err'
        command = mpi_command(hostfiles[row['nodes']], row, program, arguments)
        metadata['commands'].append(dict(label=label, argv=command))
        runtime, status = timed_command(command, out, err, remaining())
        return dict(runtime_seconds=runtime, exit_status=status,
                    stdout_log=str(out.relative_to(result_dir)), stderr_log=str(err.relative_to(result_dir)))
    try:
        for nodes in [2, 4, 8]:
            row = dict(nodes=nodes, ranks=8, ranks_per_host=8 // nodes)
            info = attempt(f'probe_{nodes}', row, HERE / 'mpi_probe.py', [])
            metadata['probes'][str(nodes)] = info
            save()
            if info['exit_status']:
                raise RuntimeError(f'MPI probe failed: {info}')
            records = json.loads((result_dir / info['stdout_log']).read_text())
            detected_model = check_probe(
                records, hosts[:nodes], 8 // nodes,
                config['cluster'].get('cpu_model_contains'),
                expected_model=metadata.get('cpu_model'),
                expected_mpi=config['cluster'].get('mpi_version'))
            metadata['cpu_model'] = detected_model
            metadata['probes'][str(nodes)]['ranks'] = records
            save()
        # Exercise the intermittent eight-host startup path before expensive runs.
        for repetition in range(1, config.get('preflight', {}).get('eight_host_repetitions', 0) + 1):
            row = dict(nodes=8, ranks=8, ranks_per_host=1)
            info = attempt(f'launcher_stress_{repetition:02d}', row, HERE / 'mpi_probe.py', [])
            metadata['launcher_stress'].append(dict(repetition=repetition, **info))
            save()
            if info['exit_status']:
                raise RuntimeError(f'Eight-host launcher stress check {repetition} failed: {info}')
            records = json.loads((result_dir / info['stdout_log']).read_text())
            check_probe(records, hosts, 1, expected_model=metadata['cpu_model'],
                        expected_mpi=config['cluster'].get('mpi_version'))
            metadata['launcher_stress'][-1]['validated'] = True
            save()
            if repetition % 10 == 0:
                print(f'Eight-host launcher checks passed: {repetition}', flush=True)
        for impl, filename in config['implementations'].items():
            for side in config['pilot']['sides']:
                row = dict(implementation=impl, nodes=2, ranks=8, ranks_per_host=4, width=side)
                info = attempt(f'pilot_{impl}_{side}', row, HERE / filename,
                               [config['defaults']['chunk_size'], f'{side}x{side}', config['defaults']['xlim'], config['defaults']['ylim']])
                metadata['pilots'].append(dict(row, **info))
                save()
                if info['exit_status']:
                    raise RuntimeError(f'Pilot failed: {impl} at {side}')
        estimate = estimated_seconds(config, metadata['pilots'])
        metadata.update(estimated_suite_seconds=estimate, remaining_measurement_seconds=remaining())
        save()
        if estimate > remaining():
            raise RuntimeError(f'Suite estimate {estimate:.0f}s exceeds remaining budget {remaining():.0f}s')
        metadata['status'] = 'measuring'
        save()
        with (result_dir / config['output']['csv']).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            stream.flush()
            for index, row in enumerate(measurements(config), 1):
                label = f"run_{index:03d}_{row['experiment']}_{row['implementation']}_r{row['repetition']}"
                print(f'{index}/240 {label}', flush=True)
                info = attempt(label, row, HERE / config['implementations'][row['implementation']],
                               [row['chunk_size'], f"{row['width']}x{row['height']}",
                                config['defaults']['xlim'], config['defaults']['ylim']])
                writer.writerow(dict(row, **info))
                stream.flush()
                os.fsync(stream.fileno())
                save()
                if info['exit_status']:
                    raise RuntimeError(f'Measurement failed: {label}; see logs')
        metadata['status'] = 'measurements_complete'
    except BaseException as exc:
        metadata.update(status='failed', error=str(exc))
        raise
    finally:
        metadata['elapsed_seconds'] = time.monotonic() - started
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=HERE / 'experiments.yaml')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--results-dir', type=Path)
    args = parser.parse_args()
    config = read_config(args.config)
    rows = measurements(config)
    if len(rows) != 240:
        raise ValueError(f'Expected 240 measurements; got {len(rows)}')
    if args.dry_run:
        print(json.dumps(dict(count=len(rows), seed=config['defaults']['seed'], measurements=rows), indent=2))
        return
    result_dir = args.results_dir or HERE / config['output']['directory'] / (
        f"job_{os.environ.get('LSB_JOBID', 'none')}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    run(config, result_dir.resolve())
    print(f'Results: {result_dir}', flush=True)


if __name__ == '__main__':
    main()
