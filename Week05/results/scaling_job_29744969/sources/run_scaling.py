#!/usr/bin/env python3
"""Strong scaling over 1-64 ranks, and 8 ranks on 1/2/4/8 hosts for a small and a large image."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import time

from run_experiments import allocation, check_probe, mpi_command, timed_command, FIELDS

HERE = Path(__file__).resolve().parent


def read_config():
    return json.loads((HERE / 'scaling.yaml').read_text())


def placement(ranks, slots_per_host):
    """Fill hosts completely: P ranks use ceil(P / slots) hosts with P / hosts ranks each."""
    hosts = math.ceil(ranks / slots_per_host)
    if ranks % hosts:
        raise ValueError(f'{ranks} ranks cannot be spread evenly over {hosts} hosts')
    return hosts, ranks // hosts


def configurations(config):
    d, e = config['defaults'], config['experiments']
    slots = config['cluster']['slots_per_host']
    rows = []
    for ranks in e['scaling']['ranks']:
        hosts, per_host = placement(ranks, slots)
        rows.append(dict(experiment='scaling', nodes=hosts, ranks=ranks, ranks_per_host=per_host,
                         width=d['width'], height=d['height']))
    ranks = e['nodes']['ranks']
    for side in e['nodes']['sides']:
        for hosts in e['nodes']['hosts']:
            if ranks % hosts or ranks // hosts > slots:
                raise ValueError(f'{ranks} ranks cannot be placed on {hosts} hosts')
            rows.append(dict(experiment='nodes', nodes=hosts, ranks=ranks, ranks_per_host=ranks // hosts,
                             width=side, height=side))
    return [dict(row, implementation=impl, chunk_size=d['chunk_size'],
                 target_area=row['width'] * row['height'], actual_area=row['width'] * row['height'])
            for row in rows for impl in config['implementations']]


def measurements(config):
    rng = random.Random(config['defaults']['seed'])
    result = []
    for repetition in range(1, config['defaults']['repetitions'] + 1):
        batch = configurations(config)
        rng.shuffle(batch)
        result.extend(dict(row, repetition=repetition) for row in batch)
    return result


def run(directory, config):
    import numpy as np
    if not os.environ.get('LSB_JOBID'):
        raise ValueError('Submit scaling_job.sh; MPI measurements require an allocation')
    slots = allocation(os.environ, config)
    hosts = list(slots)
    per_host_max = config['cluster']['slots_per_host']
    d = config['defaults']
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    for name in ('logs', 'correctness', 'sources'):
        (directory / name).mkdir()
    (directory / 'experiments.yaml').write_text(json.dumps(config, indent=2) + '\n')
    files = set(config['implementations'].values()) | {
        'Mandelbrot.py', 'run_scaling.py', 'scaling_job.sh', 'scaling.yaml', 'analyse_scaling.py',
        'test_scaling.py', 'mpi_correctness.py', 'mpi_probe.py', 'run_experiments.py', 'vendor/six.py'}
    for name in files:
        target = directory / 'sources' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / name, target)
    metadata = dict(job_id=os.environ['LSB_JOBID'], suite='scaling', status='preflight',
        started_utc=datetime.now(timezone.utc).isoformat(), hosts=hosts, allocated_slots=dict(slots),
        configuration=config, seed=d['seed'], probes=[], correctness=[], commands=[],
        modules=os.environ.get('LOADEDMODULES', '').split(':'),
        versions={name: importlib.metadata.version(name) for name in ('numpy', 'mpi4py', 'matplotlib')},
        source_hashes={name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in sorted(files)},
        git_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=HERE, text=True).strip())
    started = time.monotonic()
    deadline = float(os.environ.get('EXPERIMENT_BATCH_START', time.time())) + config['cluster']['walltime_seconds']

    def remaining():
        return deadline - time.time() - config['cluster']['analysis_reserve_seconds']

    def save():
        temp = directory / 'metadata.json.tmp'
        temp.write_text(json.dumps(metadata, indent=2) + '\n')
        temp.replace(directory / 'metadata.json')

    # One hostfile per host count, always the first hosts in LSF order (rank 0 on the first host).
    hostfiles = {}
    for count in sorted({1, 2, 4, 8, len(hosts)}):
        path = directory / f'hosts_{count}.txt'
        path.write_text(''.join(f'{h} slots={per_host_max} max_slots={per_host_max}\n' for h in hosts[:count]))
        hostfiles[count] = path

    def attempt(label, row, program, args, output=None):
        if remaining() <= 0:
            raise RuntimeError('No measurement budget remains')
        out, err = directory / 'logs' / f'{label}.out', directory / 'logs' / f'{label}.err'
        if output:
            os.environ['MANDELBROT_IMAGE_PATH'] = str(output)
        command = mpi_command(hostfiles[row['nodes']], row, program, args)
        metadata['commands'].append(dict(label=label, argv=command))
        save()
        runtime, status = timed_command(command, out, err, remaining())
        return dict(runtime_seconds=runtime, exit_status=status,
                    stdout_log=str(out.relative_to(directory)), stderr_log=str(err.relative_to(directory)))

    def require(info, label):
        if info['exit_status']:
            raise RuntimeError(f'{label} failed: {info}')

    try:
        save()
        # The shared probe check expects 8 ranks: verify every host count used by the node test.
        for count in config['experiments']['nodes']['hosts']:
            row = dict(nodes=count, ranks=8, ranks_per_host=8 // count)
            info = attempt(f'probe_{count}', row, HERE / 'mpi_probe.py', [])
            metadata['probes'].append(dict(nodes=count, **info)); save(); require(info, 'Placement probe')
            records = json.loads((directory / info['stdout_log']).read_text())
            metadata['cpu_model'] = check_probe(records, hosts[:count], 8 // count,
                expected_model=metadata.get('cpu_model'), expected_mpi=config['cluster']['mpi_version'])
            metadata['probes'][-1].update(validated=True, ranks=records); save()
        print('All placement probes passed', flush=True)
        for case, (width, height, chunk) in enumerate(config['preflight']['correctness_cases']):
            args = [chunk, f'{width}x{height}', d['xlim'], d['ylim']]
            reference = directory / 'correctness' / f'reference_{case}.npy'
            info = attempt(f'reference_{case}', dict(nodes=1, ranks=1, ranks_per_host=1),
                           HERE / 'mpi_correctness.py', [HERE / 'Mandelbrot.py', *args], reference)
            require(info, 'Serial reference')
            expected = np.load(reference)
            for ranks in config['preflight']['correctness_ranks']:
                count, per_host = placement(ranks, per_host_max)
                row = dict(nodes=count, ranks=ranks, ranks_per_host=per_host)
                for impl, filename in config['implementations'].items():
                    label = f'correctness_{case}_{ranks}_{impl}'
                    output = directory / 'correctness' / f'{label}.npy'
                    info = attempt(label, row, HERE / 'mpi_correctness.py', [HERE / filename, *args], output)
                    metadata['correctness'].append(dict(label=label, **info)); save(); require(info, label)
                    if not np.array_equal(np.load(output), expected):
                        raise RuntimeError(f'Output differs from serial reference: {label}')
                    metadata['correctness'][-1]['validated'] = True; save()
        print('All correctness checks passed against the serial reference', flush=True)
        metadata['status'] = 'measuring'; save()
        grid = measurements(config)
        with (directory / config['output']['csv']).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS); writer.writeheader(); stream.flush()
            for index, row in enumerate(grid, 1):
                label = (f'run_{index:03d}_{row["experiment"]}_{row["implementation"]}_r{row["repetition"]}'
                         f'_p{row["ranks"]}_n{row["nodes"]}_w{row["width"]}')
                print(f'{index}/{len(grid)} {label}', flush=True)
                info = attempt(label, row, HERE / config['implementations'][row['implementation']],
                               [row['chunk_size'], f'{row["width"]}x{row["height"]}', d['xlim'], d['ylim']])
                writer.writerow(dict(row, **info)); stream.flush(); os.fsync(stream.fileno()); save()
                require(info, label)
        metadata['status'] = 'measurements_complete'
    except BaseException as exc:
        metadata.update(status='failed', error=str(exc)); raise
    finally:
        metadata['elapsed_seconds'] = time.monotonic() - started; save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--results-dir', type=Path)
    args = parser.parse_args(); config = read_config()
    if args.dry_run:
        grid = measurements(config)
        counts = {e: sum(r['experiment'] == e for r in grid) for e in config['experiments']}
        print(f'{len(grid)} measurements ({counts}); seed {config["defaults"]["seed"]}')
    else:
        run(args.results_dir or HERE / 'results' / f'scaling_job_{os.environ["LSB_JOBID"]}', config)


if __name__ == '__main__':
    main()
