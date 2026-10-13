#!/usr/bin/env python3
"""Exact serial-reference checks for the heavy grid and a matched five-version benchmark."""
import argparse
import ast
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
from statistics import median
import subprocess
import time

from run_experiments import allocation, check_probe, mpi_command, timed_command, read_config

HERE=Path(__file__).resolve().parent
TITLES={'serial_reference':'Original Mandelbrot.py', 'static_blocking':'Blocking static',
        'static_nonblocking':'Nonblocking static','dynamic_blocking':'Blocking dynamic',
        'dynamic_nonblocking':'Nonblocking dynamic'}
FIELDS=['implementation','repetition','ranks','width','height','chunk_size','runtime_seconds',
        'exit_status','np_array_equal','chunk_checks','image_sha256','stdout_log','stderr_log']


def serial_calculation_namespace(program):
    """Execute the original serial statements up to its plotting-only section."""
    tree=ast.parse(Path(program).read_text())
    plotting=next(i for i,node in enumerate(tree.body) if isinstance(node,ast.Import)
                  and any(alias.name=='matplotlib.pyplot' for alias in node.names))
    prefix=ast.Module(body=tree.body[:plotting],type_ignores=[])
    namespace={'__name__':'__main__','__file__':str(program)}
    exec(compile(prefix,str(program),'exec'),namespace)
    return namespace


def cases(config):
    d=config['defaults']
    return sorted({(side,side,d['chunk_size']) for side in config['experiments']['image_area']['sides']} |
        {(d['width'],d['height'],chunk) for chunk in [d['chunk_size'],*config['experiments']['chunk_size']['values']]})


def compare_images(actual,reference,chunk):
    import numpy as np
    equal=bool(np.array_equal(actual,reference))
    if not equal or actual.shape!=reference.shape or actual.dtype!=reference.dtype:
        raise ValueError('Final image differs from serial reference (values, shape or dtype)')
    blocks=0
    for start in range(0,reference.shape[0],chunk):
        if not np.array_equal(actual[start:start+chunk],reference[start:start+chunk]):
            raise ValueError(f'Chunk starting at row {start} differs from serial reference')
        blocks+=1
    return blocks,hashlib.sha256(actual).hexdigest()


def validate_saved(directory):
    config=json.loads((directory/'experiments.yaml').read_text())
    metadata=json.loads((directory/'metadata.json').read_text())
    expected={(impl,*case) for impl in config['parallel_implementations'] for case in cases(config['heavy_config'])}
    evidence=metadata.get('correctness',[])
    if len(evidence)!=len(expected) or {(r['implementation'],r['width'],r['height'],r['chunk_size']) for r in evidence}!=expected:
        raise ValueError('Incomplete or duplicate heavy-grid correctness checks')
    if any(not r.get('np_array_equal') or r['exit_status']!=0 or r['chunk_checks']!=math.ceil(r['width']/r['chunk_size']) for r in evidence):
        raise ValueError('A final image or chunk comparison failed')
    with (directory/'measurements.csv').open(newline='') as stream:rows=list(csv.DictReader(stream))
    identities={(r['implementation'],int(r['repetition'])) for r in rows}
    wanted={(impl,rep) for impl in TITLES for rep in (1,2,3)}
    if len(rows)!=15 or identities!=wanted:
        raise ValueError('Need all 15 distinct five-version benchmark runs')
    for row in rows:
        runtime=float(row['runtime_seconds'])
        if (int(row['exit_status'])!=0 or row['np_array_equal']!='True' or not 0<runtime<float('inf')
                or (int(row['width']),int(row['height']),int(row['chunk_size']))!=(3000,3000,10)
                or int(row['ranks'])!=(1 if row['implementation']=='serial_reference' else 8)
                or int(row['chunk_checks'])!=300):
            raise ValueError('Invalid or incorrect benchmark record')
    return config,metadata,rows


def report(directory):
    config,metadata,rows=validate_saved(directory)
    groups={impl:[float(r['runtime_seconds']) for r in rows if r['implementation']==impl] for impl in TITLES}
    serial=median(groups['serial_reference'])
    table=['| Version | Ranks | Median (s) | Min–max (s) | Speedup | Exact image/chunks |',
           '|---|---:|---:|---|---:|---|']
    for impl,title in TITLES.items():
        values=groups[impl]
        table.append(f'| {title} | {1 if impl=="serial_reference" else 8} | {median(values):.3f} | {min(values):.3f}–{max(values):.3f} | {serial/median(values):.2f}× | 3/3 passed |')
    text=['# Correctness and five-version benchmark','',
          f'Job **{metadata["job_id"]}**, after full sweep **{config["parent_job_id"]}**. CPU: {metadata["cpu_model"]}.','',
          '## Correctness','',
          f'All **{len(metadata["correctness"])}** implementation/image/chunk combinations passed. Each assembled image and each contiguous row chunk was compared with the original serial Mandelbrot.py using np.array_equal. Shape and dtype also match.',
          'The checks cover all ten area-sweep sizes, the 3000×3000 baseline, and all seven heavy chunk sizes. Checks use eight MPI ranks on two hosts; the four/eight-host timing placements are not repeated here. Source hashes match the running full suite.',
          'All fifteen benchmark outputs also passed exact image equality and 300 separate 10-row chunk comparisons. Compressed reference/output arrays, hashes, logs and per-case evidence are archived.',
          '', '```python','assert np.array_equal(image, reference)',
          'for start in range(0, image.shape[0], chunk_size):',
          '    assert np.array_equal(image[start:start + chunk_size],',
          '                          reference[start:start + chunk_size])','```','',
          'Exact equality is appropriate because these versions preserve the same per-pixel arithmetic, coordinates and 100-iteration limit. The original convention of leaving non-escaping pixels at zero is preserved.',
          '', '## Compact benchmark overview','',
          '3000×3000 pixels, chunk 10, default limits, 100 iterations; serial uses one rank, MPI versions use eight ranks on the same two hosts. All fifteen runs execute sequentially with three shuffled repetition rounds, seed 261614.',
          '', '<!-- overview-table:start -->',*table,'<!-- overview-table:end -->','',
          'Median complete launch-to-exit runtimes include MPI/Python startup and final array export. Serial benchmark runs execute the original source statements through the end of calculation and omit its plotting-only section, matching the MPI programs. Reference-generation runs still execute the complete original script. Speedups compare complete calculation/export workflows, not isolated arithmetic kernels. Array comparison and compression happen after timing.',
          'These are new matched benchmark measurements for all five versions; timings are not mixed across allocations with the 240-run sweep. Shared hosts can still introduce variation; min–max ranges are not confidence intervals.',
          '', '## Full-image correctness evidence','',
          '| Implementation | Image | Chunk rows | Image equal | Chunks checked |',
          '|---|---|---:|---|---:|']
    for row in metadata['correctness']:
        text.append(f'| {TITLES[row["implementation"]]} | {row["width"]}×{row["height"]} | {row["chunk_size"]} | True | {row["chunk_checks"]} |')
    (directory/'SUMMARY.md').write_text('\n'.join(text)+'\n')
    try: import six
    except ModuleNotFoundError:
        sys_path=__import__('sys').path;sys_path.insert(0,str(HERE/'vendor'));import six
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    figure,axis=plt.subplots(figsize=(9,5))
    names=list(TITLES);values=[median(groups[name]) for name in names]
    axis.bar(range(5),values,yerr=[[m-min(groups[n]) for n,m in zip(names,values)],
                                 [max(groups[n])-m for n,m in zip(names,values)]],capsize=5)
    axis.set_xticks(range(5),list(TITLES.values()),rotation=15,ha='right');axis.set_ylabel('Median complete runtime (s)')
    axis.set_title('Five versions: 3000×3000, chunk 10; median of 3 runs')
    figure.text(.5,.015,'Serial: 1 rank. MPI: 8 ranks on 2 hosts. Plotting omitted; all export arrays; bars show min–max.',ha='center',fontsize=8)
    figure.tight_layout(rect=(0,.04,1,1));(directory/'figures').mkdir(exist_ok=True)
    for suffix in ('png','pdf'):figure.savefig(directory/'figures'/f'benchmark_overview.{suffix}',dpi=180)
    plt.close(figure)
    metadata.update(status='complete',analysis=dict(successful_records=15,correctness_checks=len(metadata['correctness']),benchmark_image_checks=15,benchmark_chunk_checks=4500,report='SUMMARY.md'))
    (directory/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')


def run(directory,parent):
    import numpy as np
    parent_meta=json.loads((parent/'metadata.json').read_text())
    if parent_meta.get('status')!='complete':raise ValueError('Parent full suite must finish successfully first')
    heavy=parent_meta['configuration'];parallel=heavy['implementations'];programs={'serial_reference':'Mandelbrot.py',**parallel}
    cluster=dict(heavy['cluster'],hosts=2,slots_per_host=4)
    hosts=list(allocation(os.environ,dict(cluster=cluster)))
    directory.mkdir(parents=True,exist_ok=False)
    for name in ('logs','images','scratch','sources'):(directory/name).mkdir()
    config=dict(suite='five_versions',parent_job_id=parent_meta['job_id'],heavy_config=heavy,
        defaults=dict(heavy['defaults'],repetitions=3),parallel_implementations=parallel,implementations=programs,
        seed=261614,output=dict(csv='measurements.csv'))
    (directory/'experiments.yaml').write_text(json.dumps(config,indent=2)+'\n')
    files=set(programs.values())|{'mpi_correctness.py','mpi_probe.py','verify_and_benchmark.py',
        'verify_benchmark_job.sh','test_five_versions.py','run_experiments.py','publish_results.py'}
    for name in files:shutil.copy2(HERE/name,directory/'sources'/name)
    hashes={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in files}
    for name in programs.values():
        if hashes[name]!=parent_meta['source_hashes'][name]:raise ValueError(f'Source changed since full suite: {name}')
    metadata=dict(job_id=os.environ['LSB_JOBID'],status='preflight',configuration=config,hosts=hosts,
        cpu_model=parent_meta['cpu_model'],source_hashes=hashes,correctness=[],commands=[],
        versions={p:importlib.metadata.version(p) for p in ('numpy','mpi4py','matplotlib')},
        modules=os.environ.get('LOADEDMODULES','').split(':'),started_utc=datetime.now(timezone.utc).isoformat(),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE,text=True).strip())
    def save():(directory/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    hostfile=directory/'hosts.txt';hostfile.write_text(''.join(f'{h} slots=4 max_slots=4\n' for h in hosts))
    deadline=float(os.environ.get('EXPERIMENT_BATCH_START',time.time()))+5.8*3600
    def execute(label,impl,width,height,chunk):
        output=directory/'scratch'/f'{label}.npy';os.environ['MANDELBROT_IMAGE_PATH']=str(output)
        os.environ['MANDELBROT_SERIAL_CALCULATION_ONLY']='1' if impl=='serial_reference' and label.startswith('benchmark_') else '0'
        row=dict(ranks=1 if impl=='serial_reference' else 8,ranks_per_host=1 if impl=='serial_reference' else 4)
        command=mpi_command(hostfile,row,HERE/'mpi_correctness.py',[HERE/programs[impl],chunk,f'{width}x{height}',heavy['defaults']['xlim'],heavy['defaults']['ylim']])
        metadata['commands'].append(dict(label=label,argv=command));save()
        out,err=directory/'logs'/f'{label}.out',directory/'logs'/f'{label}.err'
        seconds,status=timed_command(command,out,err,max(.01,deadline-time.time()))
        record=dict(implementation=impl,width=width,height=height,chunk_size=chunk,ranks=row['ranks'],runtime_seconds=seconds,exit_status=status,stdout_log=f'logs/{label}.out',stderr_log=f'logs/{label}.err')
        if status:metadata['failed_attempt']=record;save();raise RuntimeError(f'Failed {label}: {status}')
        return record,output
    try:
        command=mpi_command(hostfile,dict(ranks=8,ranks_per_host=4),HERE/'mpi_probe.py',[])
        out,err=directory/'logs/probe.out',directory/'logs/probe.err'
        _,status=timed_command(command,out,err,120)
        if status:raise RuntimeError('Placement probe failed')
        records=json.loads(out.read_text());check_probe(records,hosts,4,expected_model=parent_meta['cpu_model'],expected_mpi='5.0.10')
        metadata['probe']=records;metadata['status']='correctness';save()
        references={}
        for width,height,chunk in cases(heavy):
            key=(width,height)
            if key not in references:
                _,output=execute(f'reference_{width}_{height}','serial_reference',width,height,chunk)
                reference=np.load(output);target=directory/'images'/f'reference_{width}_{height}.npz'
                np.savez_compressed(target,image=reference);references[key]=target;output.unlink()
            else:
                with np.load(references[key]) as archive:reference=archive['image']
            for impl in parallel:
                label=f'check_{impl}_{width}_{height}_c{chunk}';record,output=execute(label,impl,width,height,chunk)
                actual=np.load(output)
                try:blocks,digest=compare_images(actual,reference,chunk)
                except ValueError:
                    record['np_array_equal']=False;metadata['correctness'].append(record);save();raise
                record.update(np_array_equal=True,chunk_checks=blocks,image_sha256=digest)
                metadata['correctness'].append(record);save()
                np.savez_compressed(directory/'images'/f'{label}.npz',image=actual);output.unlink();del actual
            del reference
            print(f'Passed all four final-image/chunk checks: {width}×{height}, chunk {chunk}',flush=True)
        metadata['status']='benchmark';save()
        with np.load(references[3000,3000]) as archive:reference=archive['image']
        rng=random.Random(config['seed'])
        with (directory/'measurements.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader();stream.flush()
            for repetition in (1,2,3):
                order=list(programs);rng.shuffle(order)
                for impl in order:
                    print(f'Benchmark {repetition}/3: {impl}',flush=True)
                    record,output=execute(f'benchmark_{impl}_r{repetition}',impl,3000,3000,10)
                    actual=np.load(output);record['repetition']=repetition
                    try:blocks,digest=compare_images(actual,reference,10)
                    except ValueError:
                        record.update(np_array_equal=False,chunk_checks=0,image_sha256='');writer.writerow(record);stream.flush();os.fsync(stream.fileno());raise
                    record.update(np_array_equal=True,chunk_checks=blocks,image_sha256=digest)
                    writer.writerow(record);stream.flush();os.fsync(stream.fileno())
                    if repetition==1:np.savez_compressed(directory/'images'/f'benchmark_{impl}.npz',image=actual)
                    output.unlink();del actual
        metadata['status']='measurements_complete';save();report(directory)
    except BaseException as exc:
        metadata.update(status='failed',error=str(exc));save();raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--results-dir',type=Path);parser.add_argument('--parent-results',type=Path,required=True)
    args=parser.parse_args();run((args.results_dir or HERE/'results'/f'verification_job_{os.environ["LSB_JOBID"]}').resolve(),args.parent_results.resolve())
