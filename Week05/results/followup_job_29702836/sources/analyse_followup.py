#!/usr/bin/env python3
"""Validate all 175 follow-up measurements, plot ranges and generate a report."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
from statistics import median
import sys

from plot_experiments import validated_medians, normalized
from run_experiments import CONFIG_FIELDS
from run_followup import profile_records, PROFILED

TITLES={'static_blocking':'Blocking static (profiled)',
    'static_nonblocking':'Nonblocking static','dynamic_blocking':'Blocking dynamic',
    'dynamic_nonblocking':'Nonblocking dynamic',
    'static_blocking_interleaved':'Blocking static: interleaved rounds'}
FIGURES=('threshold','one_vs_two','rank_timings')


def validate(directory):
    config=json.loads((directory/'experiments.yaml').read_text())
    with (directory/'measurements.csv').open(newline='') as stream:
        rows=list(csv.DictReader(stream))
    points=validated_medians(rows,config)
    if len(rows)!=175 or len(points)!=35:
        raise ValueError('Expected exactly 175 successful records and 35 median points')
    for row in rows:
        if row['implementation'] in PROFILED:
            if not row.get('profile_log'):
                raise ValueError('Missing rank timing profile')
            profile_records(directory/row['profile_log'],int(row['width']),
                'original' if row['implementation']=='static_blocking' else 'interleaved')
    return config,rows,points


def analyse(directory):
    config,rows,points=validate(directory)
    try:
        import six
    except ModuleNotFoundError:
        sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
        import six
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    groups=defaultdict(list)
    for raw in rows:
        row=normalized(raw)
        groups[tuple(row[k] for k in CONFIG_FIELDS if k!='repetition')].append(float(row['runtime_seconds']))
    output=directory/'figures';output.mkdir(exist_ok=True)
    paths=[]
    def save(fig,name):
        for suffix in ('png','pdf'):
            p=output/f'{name}.{suffix}';fig.savefig(p,dpi=180);paths.append(p)
        plt.close(fig)
    for experiment,key,label,fixed in (
            ('threshold','chunk_size','Chunk size (rows)','8 ranks on 2 hosts'),
            ('one_vs_two','nodes','Physical hosts','8 total ranks; chunk size 10')):
        fig,axes=plt.subplots(2,3,figsize=(14,8),sharex=True,sharey=True)
        for ax,impl in zip(axes.flat,TITLES):
            series=sorted((p for p in points if p['experiment']==experiment and p['implementation']==impl),key=lambda p:p[key])
            values=[groups[tuple(p[k] for k in CONFIG_FIELDS if k!='repetition')] for p in series]
            ax.errorbar([p[key] for p in series],[p['median_seconds'] for p in series],
                yerr=[[p['median_seconds']-min(v) for p,v in zip(series,values)],
                      [max(v)-p['median_seconds'] for p,v in zip(series,values)]],marker='o',capsize=4)
            ax.set_title(TITLES[impl]);ax.set_xlabel(label);ax.set_ylabel('Complete runtime (s)')
            ax.set_xticks(config['experiments'][experiment]);ax.set_ylim(bottom=0);ax.grid(alpha=.3)
        axes.flat[-1].axis('off')
        fig.text(.5,.02,f'{fixed}; 3000×3000 pixels; 100 iterations. Median of 5 runs; error bars show min–max.',ha='center')
        fig.tight_layout(rect=(0,.05,1,1));save(fig,experiment)
    # Show where each rank spends time at chunk 12, across the five threshold runs.
    fig,axes=plt.subplots(1,2,figsize=(13,5),sharey=True)
    for ax,impl in zip(axes,('static_blocking','static_blocking_interleaved')):
        records=[profile_records(directory/r['profile_log'],3000,
            'original' if impl=='static_blocking' else 'interleaved') for r in rows
            if r['experiment']=='threshold' and r['implementation']==impl and int(r['chunk_size'])==12]
        bottom=np.zeros(8)
        for field,label in [('compute_seconds','Computation'),('send_seconds','Inside Send'),
                            ('receive_seconds','Inside Recv'),('final_barrier_seconds','Final barrier')]:
            values=np.array([median(next(p[field] for p in sample if p['rank']==rank) for sample in records) for rank in range(8)])
            ax.bar(range(8),values,bottom=bottom,label=label);bottom+=values
        ax.set_title(TITLES[impl]);ax.set_xlabel('Rank');ax.set_ylabel('Median duration per phase (s)');ax.set_xticks(range(8));ax.legend()
    fig.text(.5,.02,'3000×3000; 12-row chunks; 8 ranks on 2 hosts; five repetitions. MPI durations include waiting and transfer.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.05,1,1));save(fig,'rank_timings')
    text=['# Follow-up measurements', '',
        '175 successful complete launches; 35 configurations; median of five repetitions.',
        'The error bars show the full observed min–max range, not confidence intervals.', '',
        '## Runtime comparisons', '',
        '| Experiment | Implementation | Hosts | Chunk rows | Median s | Min s | Max s |',
        '|---|---|---:|---:|---:|---:|---:|']
    for p in sorted(points,key=lambda p:(p['experiment'],p['implementation'],p['nodes'],p['chunk_size'])):
        samples=groups[tuple(p[k] for k in CONFIG_FIELDS if k!='repetition')]
        text.append(f'| {p["experiment"]} | {TITLES[p["implementation"]]} | {p["nodes"]} | {p["chunk_size"]} | {p["median_seconds"]:.3f} | {min(samples):.3f} | {max(samples):.3f} |')
    text+=['','## Communication diagnostics','','| Version | Chunk rows | Median of maximum worker Send time (s) |', '|---|---:|---:|']
    for impl in ('static_blocking','static_blocking_interleaved'):
        for chunk in config['experiments']['threshold']:
            maxima=[]
            for r in rows:
                if r['experiment']=='threshold' and r['implementation']==impl and int(r['chunk_size'])==chunk:
                    profile=profile_records(directory/r['profile_log'],3000,'original' if impl=='static_blocking' else 'interleaved')
                    maxima.append(max(p['send_seconds'] for p in profile if p['rank']!=0))
            text.append(f'| {TITLES[impl]} | {chunk} | {median(maxima):.3f} |')
    def runtime(exp,impl,nodes,chunk):
        return next(p['median_seconds'] for p in points if p['experiment']==exp and p['implementation']==impl and p['nodes']==nodes and p['chunk_size']==chunk)
    text+=['','## Interpretation','','The interleaved variant changes receive order and how often rank zero receives; row assignment and pixel arithmetic are unchanged.']
    for chunk in config['experiments']['threshold']:
        ratio=runtime('threshold','static_blocking',2,chunk)/runtime('threshold','static_blocking_interleaved',2,chunk)
        text.append(f'- Chunk {chunk}: original/interleaved runtime ratio **{ratio:.2f}×**.')
    text+=['','The following ratios compare the same eight ranks and image size on one versus two hosts. A ratio above one means two hosts were faster:']
    for impl in TITLES:
        ratio=runtime('one_vs_two',impl,1,10)/runtime('one_vs_two',impl,2,10)
        text.append(f'- {TITLES[impl]}: one-host/two-host ratio **{ratio:.2f}×**.')
    text+=['','## Limits of interpretation','','All runs use one allocation, one CPU model, explicit core binding and sequential launches. Hosts remain shared with other jobs. Five repetitions quantify observed spread but do not establish statistical significance.',
        'Static blocking and its interleaved variant include timing instrumentation, a final barrier and profile output. The original four source files are preserved. Compare the variants within this suite; their complete runtimes are not identical measurement protocols to the historical suite.',
        'Time inside MPI calls includes waiting and communication; it is not pure network transfer time. The stacked plot sums medians of separate phases and is illustrative, not the median total runtime.',
        'A jump in Send time supports the receive-order explanation, but the specific MPI buffering/protocol threshold still requires MPI tracing.',
        'Output was checked for exact equality with the serial course reference on three cases and both placements before measurement. Timing success alone is not a large-image output comparison.',
        '', '## Figures', '']
    for name in FIGURES:
        text+= [f'![{name}](figures/{name}.png)',f'[PDF](figures/{name}.pdf)','']
    (directory/'SUMMARY.md').write_text('\n'.join(text)+'\n')
    metadata=json.loads((directory/'metadata.json').read_text())
    metadata.update(status='complete',analysis=dict(successful_records=len(rows),median_points=len(points),figures=[str(p) for p in paths],report='SUMMARY.md'))
    temp=directory/'metadata.json.tmp';temp.write_text(json.dumps(metadata,indent=2)+'\n');temp.replace(directory/'metadata.json')
    print('Validated 175 measurements and profiles; saved six figures and SUMMARY.md',flush=True)
    return paths


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('results_dir',type=Path)
    analyse(parser.parse_args().results_dir.resolve())
