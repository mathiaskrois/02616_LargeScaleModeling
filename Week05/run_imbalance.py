#!/usr/bin/env python3
"""Per-rank computation time for static and dynamic scheduling across chunk sizes."""
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
MODES = {'static_blocking': 'interleaved', 'dynamic_blocking': 'dynamic'}


def read_config():
    return json.loads((HERE / 'imbalance.yaml').read_text())


def measurements(config):
    d = config['defaults']
    rng = random.Random(d['seed'])
    rows = []
    for repetition in range(1, d['repetitions'] + 1):
        batch = [dict(experiment='imbalance', implementation=impl, repetition=repetition,
                      nodes=d['nodes'], ranks=d['ranks'], ranks_per_host=d['ranks'] // d['nodes'],
                      chunk_size=chunk, width=d['width'], height=d['height'],
                      target_area=d['width'] * d['height'], actual_area=d['width'] * d['height'])
                 for chunk in config['chunk_sizes'] for impl in config['implementations']]
        rng.shuffle(batch)
        rows.extend(batch)
    return rows


def profile_records(path, implementation, width, chunk):
    records = json.loads(Path(path).read_text())
    if len(records) != 8 or {r['rank'] for r in records} != set(range(8)):
        raise ValueError('Profile must contain eight distinct ranks')
    if sum(r['rows'] for r in records) != width or any(r['mode'] != MODES[implementation] for r in records):
        raise ValueError('Profile has incorrect computed rows or algorithm mode')
    for record in records:
        for key in ('compute_seconds', 'send_seconds', 'receive_seconds', 'algorithm_seconds', 'final_barrier_seconds'):
            if not isinstance(record[key], (int, float)) or not 0 <= record[key] < float('inf'):
                raise ValueError('Invalid profile timing')
    if implementation == 'dynamic_blocking':
        manager = next(r for r in records if r['rank'] == 0)
        if manager['rows'] or sum(r['chunks'] for r in records) != math.ceil(width / chunk):
            raise ValueError('Dynamic profile has an incorrect chunk count')
    return records


def run(directory, config):
    import numpy as np
    if not os.environ.get('LSB_JOBID'):
        raise ValueError('Submit imbalance_job.sh; MPI measurements require an allocation')
    slots = allocation(os.environ, config)
    hosts = list(slots)
    d = config['defaults']
    per_host = d['ranks'] // d['nodes']
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    for name in ('logs', 'profiles', 'correctness', 'sources'):
        (directory / name).mkdir()
    (directory / 'experiments.yaml').write_text(json.dumps(config, indent=2) + '\n')
    files = set(config['implementations'].values()) | {
        'Mandelbrot_static_profiled.py', 'Mandelbrot_blocking_dynamic.py', 'Mandelbrot.py',
        'run_imbalance.py', 'imbalance_job.sh', 'imbalance.yaml', 'analyse_imbalance.py',
        'test_imbalance.py', 'mpi_correctness.py', 'mpi_probe.py', 'run_experiments.py', 'vendor/six.py'}
    for name in files:
        target = directory / 'sources' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / name, target)
    metadata = dict(job_id=os.environ['LSB_JOBID'], suite='imbalance', status='preflight',
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

    hostfile = directory / 'hosts.txt'
    hostfile.write_text(''.join(f'{host} slots={per_host} max_slots={per_host}\n' for host in hosts))
    serial_hostfile = directory / 'hosts_serial.txt'
    serial_hostfile.write_text(f'{hosts[0]} slots=1 max_slots=1\n')

    def attempt(label, row, program, args, output=None):
        if remaining() <= 0:
            raise RuntimeError('No measurement budget remains')
        out, err = directory / 'logs' / f'{label}.out', directory / 'logs' / f'{label}.err'
        profile = directory / 'profiles' / f'{label}.json'
        os.environ['MANDELBROT_PROFILE_PATH'] = str(profile)
        if output:
            os.environ['MANDELBROT_IMAGE_PATH'] = str(output)
        command = mpi_command(serial_hostfile if row['ranks'] == 1 else hostfile, row, program, args)
        metadata['commands'].append(dict(label=label, argv=command))
        save()
        runtime, status = timed_command(command, out, err, remaining())
        return dict(runtime_seconds=runtime, exit_status=status,
                    stdout_log=str(out.relative_to(directory)), stderr_log=str(err.relative_to(directory)),
                    profile_log=str(profile.relative_to(directory)) if profile.exists() else '')

    def require(info, label):
        if info['exit_status']:
            raise RuntimeError(f'{label} failed: {info}')

    mpi_row = dict(ranks=d['ranks'], ranks_per_host=per_host)
    try:
        save()
        for number in range(1 + config['preflight']['launcher_repetitions']):
            info = attempt(f'probe_{number:02d}', mpi_row, HERE / 'mpi_probe.py', [])
            metadata['probes'].append(info); save(); require(info, 'Placement probe')
            records = json.loads((directory / info['stdout_log']).read_text())
            metadata['cpu_model'] = check_probe(records, hosts, per_host,
                expected_model=metadata.get('cpu_model'), expected_mpi=config['cluster']['mpi_version'])
            metadata['probes'][-1].update(validated=True, ranks=records); save()
        print('All placement and launcher probes passed', flush=True)
        # The profiled versions must reproduce the unmodified serial course code exactly.
        for case, (width, height, chunk) in enumerate(config['preflight']['correctness_cases']):
            args = [chunk, f'{width}x{height}', d['xlim'], d['ylim']]
            reference = directory / 'correctness' / f'reference_{case}.npy'
            info = attempt(f'reference_{case}', dict(ranks=1, ranks_per_host=1),
                           HERE / 'mpi_correctness.py', [HERE / 'Mandelbrot.py', *args], reference)
            require(info, 'Serial reference')
            expected = np.load(reference)
            for impl, filename in config['implementations'].items():
                label = f'correctness_{case}_{impl}'
                output = directory / 'correctness' / f'{label}.npy'
                info = attempt(label, mpi_row, HERE / 'mpi_correctness.py', [HERE / filename, *args], output)
                metadata['correctness'].append(dict(label=label, **info)); save(); require(info, label)
                if not np.array_equal(np.load(output), expected):
                    raise RuntimeError(f'Output differs from serial reference: {label}')
                profile_records(directory / info['profile_log'], impl, width, chunk)
                metadata['correctness'][-1]['validated'] = True; save()
        print('All correctness checks passed against the serial reference', flush=True)
        metadata['status'] = 'measuring'; save()
        grid = measurements(config)
        with (directory / config['output']['csv']).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS + ['profile_log']); writer.writeheader(); stream.flush()
            for index, row in enumerate(grid, 1):
                label = f'run_{index:03d}_{row["implementation"]}_r{row["repetition"]}_c{row["chunk_size"]}'
                print(f'{index}/{len(grid)} {label}', flush=True)
                info = attempt(label, row, HERE / config['implementations'][row['implementation']],
                               [row['chunk_size'], f'{row["width"]}x{row["height"]}', d['xlim'], d['ylim']])
                writer.writerow(dict(row, **info)); stream.flush(); os.fsync(stream.fileno()); save()
                require(info, label)
                profile_records(directory / info['profile_log'], row['implementation'], row['width'], row['chunk_size'])
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
        print(f'{len(grid)} measurements: {len(config["implementations"])} implementations x '
              f'{len(config["chunk_sizes"])} chunk sizes x {config["defaults"]["repetitions"]} repetitions; '
              f'seed {config["defaults"]["seed"]}')
    else:
        run(args.results_dir or HERE / 'results' / f'imbalance_job_{os.environ["LSB_JOBID"]}', config)


if __name__ == '__main__':
    main()
