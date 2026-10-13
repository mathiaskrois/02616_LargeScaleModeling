#!/usr/bin/env python3
"""Retest only blocking-static chunk 1 and produce a labelled historical replacement."""
import csv
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from statistics import median

from run_experiments import allocation, check_probe, mpi_command, timed_command, FIELDS
from plot_experiments import identity, normalized, validated_medians, TITLES

HERE=Path(__file__).resolve().parent
OLD=HERE/'results/job_29611697'


def target(row):
    return row['experiment']=='chunk_size' and row['implementation']=='static_blocking' and int(row['chunk_size'])==1


def read_rows(path):
    with path.open(newline='') as stream: return list(csv.DictReader(stream))


def validate_retest(rows,old_rows):
    expected={identity(normalized(r)) for r in old_rows if target(r)}
    if len(rows)!=3 or {identity(normalized(r)) for r in rows}!=expected:
        raise ValueError('Need exactly the three original chunk-1 configurations')
    for row in rows:
        runtime=float(row['runtime_seconds'])
        if int(row['exit_status'])!=0 or not 0<runtime<float('inf'):
            raise ValueError('All three retests must succeed with positive finite runtimes')


def replacement_rows(old_rows,new_rows,job_id,revision):
    validate_retest(new_rows,old_rows)
    replacements={int(r['repetition']):r for r in new_rows}
    result=[]
    for old in old_rows:
        if target(old):
            row=dict(replacements[int(old['repetition'])],source_job_id=job_id,
                source_revision=revision,code_variant='interleaved blocking static')
            for key in ('stdout_log','stderr_log'): row[key]='../'+row[key]
        else:
            row=dict(old,source_job_id='29611697',source_revision='see original metadata',code_variant='historical unchanged')
            for key in ('stdout_log','stderr_log'): row[key]='../../job_29611697/'+row[key]
        result.append(row)
    return result


def validate_saved(directory):
    config=json.loads((directory/'experiments.yaml').read_text())
    old=read_rows(directory/'original_measurements.csv')
    new=read_rows(directory/'measurements.csv');validate_retest(new,old)
    derived=read_rows(directory/'updated_initial/measurements.csv')
    original_config=json.loads((directory/'updated_initial/experiments.yaml').read_text())
    validated_medians(derived,original_config)
    metadata=json.loads((directory/'metadata.json').read_text())
    if derived!=replacement_rows(old,new,metadata['job_id'],metadata['git_commit']):
        raise ValueError('Derived dataset differs outside the permitted replacement')
    if not metadata.get('correctness',{}).get('validated'):
        raise ValueError('Missing exact serial-reference comparison')
    return metadata,config,new,derived


def analyse(directory):
    metadata,config,new,derived=validate_saved(directory)
    original_config=json.loads((directory/'updated_initial/experiments.yaml').read_text())
    points=validated_medians(derived,original_config)
    try: import six
    except ModuleNotFoundError:
        sys.path.insert(0,str(HERE/'vendor'));import six
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    figures=directory/'figures';figures.mkdir(exist_ok=True)
    fig,axes=plt.subplots(2,2,figsize=(11,8),sharex=True,sharey=True)
    subset=[p for p in points if p['experiment']=='chunk_size']
    for ax,impl in zip(axes.flat,TITLES):
        series=sorted((p for p in subset if p['implementation']==impl),key=lambda p:p['chunk_size'])
        if impl=='static_blocking':
            historical=[p for p in series if p['chunk_size']!=1]
        else: historical=series
        ax.plot([p['chunk_size'] for p in historical],[p['median_seconds'] for p in historical],marker='o',label='Historical implementation')
        if impl=='static_blocking':
            runtimes=[float(r['runtime_seconds']) for r in new];value=median(runtimes)
            ax.errorbar([1],[value],yerr=[[value-min(runtimes)],[max(runtimes)-value]],
                marker='D',color='purple',capsize=5,linestyle='none',label='Fixed receive order: chunk 1 only')
            ax.legend(fontsize=8)
        ax.set_title(TITLES[impl]);ax.set_xlabel('Actual chunk size (rows)');ax.set_ylabel('Median complete runtime (s)');ax.grid(alpha=.3)
        ax.set_ylim(bottom=0)
    fig.text(.5,.025,'1000×1000; 8 ranks on 2 hosts; 100 iterations; median of 3 runs.\nPurple point is new code/software; blue points are historical. They are not one unchanged-code sweep.',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.09,1,1))
    for suffix in ('png','pdf'): fig.savefig(figures/f'chunk_size.{suffix}',dpi=180)
    plt.close(fig)
    old_time=median(float(r['runtime_seconds']) for r in read_rows(directory/'original_measurements.csv') if target(r))
    new_time=median(float(r['runtime_seconds']) for r in new)
    text=f'''# Chunk-size-1 retest

Job **{metadata['job_id']}**: three successful runs of the fixed blocking-static implementation.

- Image: 1000×1000; eight ranks on two hosts; chunk 1; default limits; 100 iterations.
- Original chunk-1 median: **{old_time:.3f} s**.
- Updated chunk-1 median: **{new_time:.3f} s**, observed range {min(float(r['runtime_seconds']) for r in new):.3f}–{max(float(r['runtime_seconds']) for r in new):.3f} s.
- CPU: {metadata['cpu_model']}.
- Exact full-image equality with the serial reference passed before timing.

The receive order now interleaves computation and receiving after each cyclic round.
The original source is retained as Mandelbrot_blocking_static_legacy.py and in historical snapshots.

`updated_initial/measurements.csv` substitutes only the three blocking-static chunk-1 rows in a copy of the 240-row original dataset. The other 237 rows are unchanged except for explicit provenance and log-path references. Original raw files and plots are preserved.

The purple replacement point is intentionally not connected to the historical blocking-static line: the algorithms differ. The software stack also changed from Open MPI 5.0.8 / NumPy 2.3.1 to Open MPI 5.0.10 / NumPy 2.4.1. Therefore the difference cannot be attributed solely to the code change. The old chunk-1 result was not a failed measurement.

No other chunk sizes were rerun. The remaining shape belongs to the historical implementation; replacing one point does not establish a complete curve for the fixed implementation.

![Updated chunk-size figure](figures/chunk_size.png)

[PDF](figures/chunk_size.pdf)
'''
    (directory/'SUMMARY.md').write_text(text)
    metadata.update(status='complete',analysis=dict(successful_records=3,replaced_records=3,derived_records=240,median_seconds=new_time,figures=['figures/chunk_size.png','figures/chunk_size.pdf']))
    (directory/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(f'Chunk-1 retest complete: median {new_time:.3f} s; three labelled replacement records',flush=True)


def run(directory):
    import numpy as np
    config=json.loads((OLD/'experiments.yaml').read_text())
    config['suite']='chunk1_retest'
    config['cluster'].update(hosts=2,slots_per_host=4,mpi_version='5.0.10')
    slots=allocation(os.environ,config);hosts=list(slots)
    directory.mkdir(parents=True,exist_ok=False)
    for name in ('logs','correctness','sources','updated_initial'): (directory/name).mkdir()
    (directory/'experiments.yaml').write_text(json.dumps(config,indent=2)+'\n')
    shutil.copy2(OLD/'measurements.csv',directory/'original_measurements.csv')
    shutil.copy2(OLD/'metadata.json',directory/'original_metadata.json')
    shutil.copy2(OLD/'experiments.yaml',directory/'updated_initial/experiments.yaml')
    sources=['Mandelbrot_blocking_static.py','Mandelbrot_blocking_static_legacy.py','Mandelbrot.py',
        'mpi_correctness.py','mpi_probe.py','run_experiments.py','plot_experiments.py',
        'retest_chunk1.py','chunk1_job.sh','publish_results.py','test_chunk1.py']
    for name in sources: shutil.copy2(HERE/name,directory/'sources'/name)
    metadata=dict(status='preflight',suite='chunk1_retest',job_id=os.environ['LSB_JOBID'],
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE,text=True).strip(),
        started_utc=datetime.now(timezone.utc).isoformat(),hosts=hosts,allocated_slots=dict(slots),
        versions={name:importlib.metadata.version(name) for name in ('numpy','mpi4py','matplotlib')},
        modules=os.environ.get('LOADEDMODULES','').split(':'),
        source_hashes={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in sources},commands=[])
    def save(): (directory/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    hostfile=directory/'hosts.txt';hostfile.write_text(''.join(f'{h} slots=4 max_slots=4\n' for h in hosts))
    row=dict(nodes=2,ranks=8,ranks_per_host=4)
    def attempt(label,placement,program,args,output=None):
        if output: os.environ['MANDELBROT_IMAGE_PATH']=str(output)
        command=mpi_command(hostfile,placement,program,args)
        out,err=directory/'logs'/f'{label}.out',directory/'logs'/f'{label}.err'
        metadata['commands'].append(dict(label=label,argv=command));save()
        runtime,status=timed_command(command,out,err,600)
        return dict(runtime_seconds=runtime,exit_status=status,stdout_log=f'logs/{label}.out',stderr_log=f'logs/{label}.err')
    def require(info):
        if info['exit_status']: raise RuntimeError(f'MPI attempt failed: {info}')
    try:
        info=attempt('probe',row,HERE/'mpi_probe.py',[]);require(info)
        records=json.loads((directory/info['stdout_log']).read_text())
        metadata['cpu_model']=check_probe(records,hosts,4,expected_mpi='5.0.10')
        metadata['probe']=records;save()
        args=[1,'1000x1000','-2.2:0.75','-1.3:1.3']
        reference=directory/'correctness/serial.npy';fixed=directory/'correctness/fixed.npy'
        require(attempt('serial_reference',dict(nodes=2,ranks=1,ranks_per_host=1),HERE/'mpi_correctness.py',[HERE/'Mandelbrot.py',*args],reference))
        require(attempt('fixed_correctness',row,HERE/'mpi_correctness.py',[HERE/'Mandelbrot_blocking_static.py',*args],fixed))
        if not np.array_equal(np.load(reference),np.load(fixed)): raise ValueError('Fixed image differs from serial reference')
        metadata['correctness']=dict(validated=True,width=1000,height=1000,chunk_size=1);metadata['status']='measuring';save()
        original=read_rows(directory/'original_measurements.csv')
        templates=sorted((r for r in original if target(r)),key=lambda r:int(r['repetition']))
        new=[]
        with (directory/'measurements.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader()
            for template in templates:
                repetition=int(template['repetition']);print(f'Chunk-1 repetition {repetition}/3',flush=True)
                info=attempt(f'chunk1_r{repetition}',row,HERE/'Mandelbrot_blocking_static.py',args)
                record=dict(template,**info);writer.writerow(record);stream.flush();os.fsync(stream.fileno());new.append(record);require(info)
        derived=replacement_rows(original,new,metadata['job_id'],metadata['git_commit'])
        with (directory/'updated_initial/measurements.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=FIELDS+['source_job_id','source_revision','code_variant']);writer.writeheader();writer.writerows(derived)
        metadata['status']='measurements_complete';save();analyse(directory)
    except BaseException as exc:
        metadata.update(status='failed',error=str(exc));save();raise


if __name__=='__main__':
    run((HERE/'results'/f'chunk1_job_{os.environ["LSB_JOBID"]}').resolve())
