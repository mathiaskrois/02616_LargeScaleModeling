#!/usr/bin/env python3
"""Focused overnight suite: communication threshold and one versus two hosts."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import time

from run_experiments import allocation, check_probe, mpi_command, timed_command, FIELDS

HERE = Path(__file__).resolve().parent
PROFILED = {'static_blocking', 'static_blocking_interleaved'}


def read_config():
    return json.loads((HERE / 'followup.yaml').read_text())


def measurements(config):
    d = config['defaults']
    rows = []
    rng = random.Random(d['seed'])
    for repetition in range(1, d['repetitions']+1):
        batch = []
        for experiment, values in config['experiments'].items():
            for value in values:
                nodes = value if experiment == 'one_vs_two' else 2
                chunk = value if experiment == 'threshold' else d['chunk_size']
                for implementation in config['implementations']:
                    batch.append(dict(experiment=experiment, implementation=implementation,
                        repetition=repetition, nodes=nodes, ranks=d['ranks'],
                        ranks_per_host=d['ranks']//nodes, chunk_size=chunk,
                        width=d['width'], height=d['height'],
                        target_area=d['width']*d['height'], actual_area=d['width']*d['height']))
        rng.shuffle(batch)
        rows.extend(batch)
    return rows


def profile_records(path, width, mode):
    records = json.loads(Path(path).read_text())
    if len(records) != 8 or {r['rank'] for r in records} != set(range(8)):
        raise ValueError('Profile must contain eight distinct ranks')
    if sum(r['rows'] for r in records) != width or any(r['mode'] != mode for r in records):
        raise ValueError('Profile has incorrect computed rows or algorithm mode')
    for record in records:
        for key in ('compute_seconds', 'send_seconds', 'receive_seconds', 'algorithm_seconds', 'final_barrier_seconds'):
            if not isinstance(record[key], (int, float)) or not 0 <= record[key] < float('inf'):
                raise ValueError('Invalid profile timing')
    return records


def run(directory, config):
    import numpy as np
    if not os.environ.get('LSB_JOBID'):
        raise ValueError('Submit followup_job.sh; MPI measurements require an allocation')
    slots = allocation(os.environ, config)
    hosts = list(slots)
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    for name in ('logs', 'profiles', 'correctness', 'sources'):
        (directory/name).mkdir()
    (directory/'experiments.yaml').write_text(json.dumps(config, indent=2)+'\n')
    files = set(config['implementations'].values()) | {
        'Mandelbrot_blocking_static.py', 'Mandelbrot.py', 'run_followup.py', 'followup_job.sh',
        'followup.yaml', 'analyse_followup.py', 'mpi_correctness.py', 'mpi_probe.py',
        'run_experiments.py', 'plot_experiments.py', 'publish_results.py', 'test_followup.py',
        'vendor/six.py'}
    for name in files:
        target = directory/'sources'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE/name, target)
    metadata = dict(job_id=os.environ['LSB_JOBID'], suite='followup', status='preflight',
        started_utc=datetime.now(timezone.utc).isoformat(), hosts=hosts, allocated_slots=dict(slots),
        configuration=config, seed=config['defaults']['seed'], probes=[], correctness=[], pilots=[],
        commands=[], modules=os.environ.get('LOADEDMODULES','').split(':'),
        versions={name:importlib.metadata.version(name) for name in ('numpy','mpi4py','matplotlib')},
        source_hashes={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in sorted(files)},
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE,text=True).strip())
    started = time.monotonic()
    deadline = float(os.environ.get('EXPERIMENT_BATCH_START',time.time())) + config['cluster']['walltime_seconds']
    def remaining():
        return deadline-time.time()-config['cluster']['analysis_reserve_seconds']
    def save():
        temp=directory/'metadata.json.tmp'
        temp.write_text(json.dumps(metadata,indent=2)+'\n')
        temp.replace(directory/'metadata.json')
    hostfiles={}
    for nodes in (1,2):
        path=directory/f'hosts_{nodes}.txt'
        path.write_text(''.join(f'{host} slots=8 max_slots=8\n' for host in hosts[:nodes]))
        hostfiles[nodes]=path
    def attempt(label,row,program,args,output=None):
        if remaining() <= 0:
            raise RuntimeError('No measurement budget remains')
        out,err=directory/'logs'/f'{label}.out',directory/'logs'/f'{label}.err'
        profile=directory/'profiles'/f'{label}.json'
        os.environ['MANDELBROT_PROFILE_PATH']=str(profile)
        if output:
            os.environ['MANDELBROT_IMAGE_PATH']=str(output)
        command=mpi_command(hostfiles[row['nodes']],row,program,args)
        metadata['commands'].append(dict(label=label,argv=command))
        save()
        runtime,status=timed_command(command,out,err,remaining())
        info=dict(runtime_seconds=runtime,exit_status=status,
                  stdout_log=str(out.relative_to(directory)),stderr_log=str(err.relative_to(directory)),
                  profile_log=str(profile.relative_to(directory)) if profile.exists() else '')
        return info
    def require(info,label):
        if info['exit_status']:
            raise RuntimeError(f'{label} failed: {info}')
    try:
        save()
        for number,nodes in enumerate([1,2]+[2]*config['preflight']['launcher_repetitions']):
            row=dict(nodes=nodes,ranks=8,ranks_per_host=8//nodes)
            info=attempt(f'probe_{number:02d}',row,HERE/'mpi_probe.py',[])
            metadata['probes'].append(dict(nodes=nodes,**info));save();require(info,'Placement probe')
            records=json.loads((directory/info['stdout_log']).read_text())
            metadata['cpu_model']=check_probe(records,hosts[:nodes],8//nodes,
                expected_model=metadata.get('cpu_model'),expected_mpi=config['cluster']['mpi_version'])
            metadata['probes'][-1].update(validated=True,ranks=records);save()
        print('All placement and launcher probes passed',flush=True)
        # Use the unmodified course serial implementation as the independent reference.
        programs=dict(config['implementations'],static_blocking_uninstrumented='Mandelbrot_blocking_static.py')
        for case,(width,height,chunk) in enumerate(config['preflight']['correctness_cases']):
            reference=directory/'correctness'/f'reference_{case}.npy'
            args=[chunk,f'{width}x{height}',config['defaults']['xlim'],config['defaults']['ylim']]
            row=dict(nodes=1,ranks=1,ranks_per_host=1)
            info=attempt(f'reference_{case}',row,HERE/'mpi_correctness.py',[HERE/'Mandelbrot.py',*args],reference)
            require(info,'Serial reference')
            expected=np.load(reference)
            for nodes in (1,2):
                row=dict(nodes=nodes,ranks=8,ranks_per_host=8//nodes)
                for impl,filename in programs.items():
                    label=f'correctness_{case}_{nodes}_{impl}'
                    output=directory/'correctness'/f'{label}.npy'
                    info=attempt(label,row,HERE/'mpi_correctness.py',[HERE/filename,*args],output)
                    metadata['correctness'].append(dict(label=label,**info));save();require(info,label)
                    if not np.array_equal(np.load(output),expected):
                        raise RuntimeError(f'Output differs from serial reference: {label}')
                    metadata['correctness'][-1]['validated']=True;save()
        print('All 36 correctness checks passed against the serial reference',flush=True)
        metadata['status']='pilots';save()
        # Pilot both placements and both sides of the suspected threshold.
        for nodes in (1,2):
            for impl,filename in config['implementations'].items():
                for side in config['pilot']['sides']:
                    for chunk in config['pilot']['chunks']:
                        row=dict(nodes=nodes,ranks=8,ranks_per_host=8//nodes)
                        label=f'pilot_{nodes}_{impl}_{side}_{chunk}'
                        info=attempt(label,row,HERE/filename,[chunk,f'{side}x{side}',config['defaults']['xlim'],config['defaults']['ylim']])
                        metadata['pilots'].append(dict(implementation=impl,nodes=nodes,width=side,chunk_size=chunk,**info));save();require(info,label)
        grid=measurements(config)
        # Every measured image has the baseline size. Use the slower baseline pilot
        # for each implementation/placement, then double the full estimate.
        worst={(impl,nodes):max(p['runtime_seconds'] for p in metadata['pilots']
            if p['implementation']==impl and p['nodes']==nodes and p['width']==config['defaults']['width'])
            for impl in config['implementations'] for nodes in (1,2)}
        estimate=sum(worst[r['implementation'],r['nodes']] for r in grid)*config['pilot']['allowance_factor']
        metadata.update(estimated_suite_seconds=estimate,remaining_measurement_seconds=remaining());save()
        print(f'Pilot estimate with 2× allowance: {estimate/3600:.2f} hours; available: {remaining()/3600:.2f} hours',flush=True)
        if estimate>remaining():
            raise RuntimeError('Pilot estimate exceeds remaining allocation budget')
        metadata['status']='measuring';save()
        with (directory/'measurements.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=FIELDS+['profile_log']);writer.writeheader();stream.flush()
            for index,row in enumerate(grid,1):
                label=f'run_{index:03d}_{row["experiment"]}_{row["implementation"]}_r{row["repetition"]}_n{row["nodes"]}_c{row["chunk_size"]}'
                print(f'{index}/{len(grid)} {label}',flush=True)
                info=attempt(label,row,HERE/config['implementations'][row['implementation']],
                    [row['chunk_size'],f'{row["width"]}x{row["height"]}',config['defaults']['xlim'],config['defaults']['ylim']])
                writer.writerow(dict(row,**info));stream.flush();os.fsync(stream.fileno());save();require(info,label)
                if row['implementation'] in PROFILED:
                    profile_records(directory/info['profile_log'],row['width'],
                        'original' if row['implementation']=='static_blocking' else 'interleaved')
        metadata['status']='measurements_complete'
    except BaseException as exc:
        metadata.update(status='failed',error=str(exc));raise
    finally:
        metadata['elapsed_seconds']=time.monotonic()-started;save()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--results-dir',type=Path)
    args=parser.parse_args();config=read_config()
    if args.dry_run:
        grid=measurements(config)
        print(f'{len(grid)} measurements; 125 threshold tests + 50 placement tests; seed {config["defaults"]["seed"]}')
    else:
        run(args.results_dir or HERE/'results'/f'followup_job_{os.environ["LSB_JOBID"]}',config)


if __name__=='__main__':
    main()
