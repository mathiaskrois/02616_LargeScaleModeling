#!/usr/bin/env python3
"""Compare original and fixed blocking static on the complete heavier chunk grid."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
from statistics import median
import sys

from plot_experiments import validated_medians

VERSIONS={'static_blocking':'Original receive order','static_blocking_interleaved':'Fixed: receive each round'}


def validate(directory):
    config=json.loads((directory/'experiments.yaml').read_text())
    with (directory/'measurements.csv').open(newline='') as stream:
        rows=list(csv.DictReader(stream))
    points=validated_medians(rows,config)
    if len(rows)!=80 or len(points)!=16:
        raise ValueError('Need all 80 successful runs and 16 configurations')
    return config,rows,points


def analyse(directory):
    config,rows,points=validate(directory)
    try: import six
    except ModuleNotFoundError:
        sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'));import six
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    groups=defaultdict(list)
    for row in rows: groups[row['implementation'],int(row['chunk_size'])].append(float(row['runtime_seconds']))
    figures=directory/'figures';figures.mkdir(exist_ok=True)
    fig,axes=plt.subplots(1,2,figsize=(13,5),sharey=True)
    for ax in axes:
        for implementation,label in VERSIONS.items():
            series=sorted((p for p in points if p['implementation']==implementation),key=lambda p:p['chunk_size'])
            samples=[groups[implementation,p['chunk_size']] for p in series]
            ax.errorbar([p['chunk_size'] for p in series],[p['median_seconds'] for p in series],
                yerr=[[p['median_seconds']-min(v) for p,v in zip(series,samples)],
                      [max(v)-p['median_seconds'] for p,v in zip(series,samples)]],
                marker='o',capsize=4,label=label)
        ax.set_xlabel('Actual chunk size (rows)');ax.set_ylabel('Median complete runtime (s)')
        ax.set_ylim(bottom=0);ax.grid(alpha=.3);ax.legend(fontsize=9)
    axes[0].set_title('Heavier chunk-size sweep')
    axes[1].set_title('Same measurements: small chunks expanded');axes[1].set_xscale('log',base=2)
    axes[1].set_xticks(config['experiments']['threshold'],[str(c) for c in config['experiments']['threshold']])
    fig.text(.5,.015,'3000×3000; 8 ranks on the same 2 hosts; 100 iterations; median of 5 runs. Bars show min–max.',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.06,1,1))
    for suffix in ('png','pdf'):fig.savefig(figures/f'chunk_size_comparison.{suffix}',dpi=180)
    plt.close(fig)
    text=['# Heavier chunk-size comparison','',
        '## Observation: I expected chunk size 1 to be slow','',
        'This expectation is reasonable: chunk 1 creates 3000 chunks and many Send/Recv calls. However, each row has 3000 pixels of computation, and fine partitioning distributes unequal row costs. Whether message overhead dominates must be measured.',
        '', 'Both curves below are new measurements of the original and fixed versions in one allocation and software environment. No small-dataset replacement values or historical points are inserted.',
        '', '## Measurements','',
        '| Chunk rows | Original median s | Original min–max s | Fixed median s | Fixed min–max s | Original / fixed |',
        '|---:|---:|---|---:|---|---:|']
    summaries={}
    for chunk in config['experiments']['threshold']:
        old=groups['static_blocking',chunk];new=groups['static_blocking_interleaved',chunk]
        summaries[chunk]=dict(original=median(old),fixed=median(new))
        text.append(f'| {chunk} | {median(old):.3f} | {min(old):.3f}–{max(old):.3f} | {median(new):.3f} | {min(new):.3f}–{max(new):.3f} | {median(old)/median(new):.2f}× |')
    text+=['','## Does chunk 1 behave as expected?','']
    for version,field in [('Original receive order','original'),('Fixed receive order','fixed')]:
        best=min(summaries,key=lambda c:summaries[c][field]);one=summaries[1][field]
        ratio=one/summaries[best][field]
        text.append(f'- **{version}:** chunk 1 takes **{one:.3f} s**. The fastest observed median is chunk **{best}**, at **{summaries[best][field]:.3f} s**. Chunk 1 is **{ratio:.2f}×** that runtime.')
    text+=['','A lowest median is not proof of a statistically significant optimum. Consult the min–max ranges. Chunk 1 need not be slowest: its finer load balance can offset message overhead.',
        '', '## What changed in the implementation?','',
        'The original version finishes rank zero’s own computation before receiving every result from worker one, then worker two, and so on. Workers can wait in Send while they still have computation left.',
        'The fixed version retains cyclic static row assignment, identical arithmetic and blocking Send/Recv, but receives each round before starting the next. Both calculate the correct pixels; this addresses avoidable waiting, not a special arithmetic bug at chunk 1.',
        'At intermediate message sizes the original can lose parallelism when sends wait for receives. At chunk 375 each static rank has only one chunk, so a delayed send cannot hold up subsequent computation. Very coarse chunks can still suffer unequal row costs in either version.',
        'The earlier profiled diagnostic follow-up supports the receive-order explanation. This new comparison times uninstrumented versions; it does not measure the exact MPI buffering threshold.',
        '', '## Method and limits','',
        '80 complete MPI launch-to-exit runtimes, five repetitions per version/chunk; 3000×3000, default limits, 100 iterations, eight ranks on two allocated hosts with separate physical core bindings. All launches are sequential, randomized within each of five rounds using seed 261613.',
        'Both implementations passed exact serial-reference checks on three cases before timing: partial chunk-1 rounds, idle ranks with oversized chunks, and a large-message rectangular case. The full 3000×3000 timed images are not separately saved and compared.',
        'The same CPU model and software are used for both curves, but hosts are shared with other jobs. Error bars are observed ranges, not confidence intervals. Comparisons against older jobs remain subject to cross-job variation.',
        '', '![Heavier chunk-size comparison](figures/chunk_size_comparison.png)',
        '', '[Download PDF](figures/chunk_size_comparison.pdf)','']
    (directory/'SUMMARY.md').write_text('\n'.join(text))
    metadata=json.loads((directory/'metadata.json').read_text());metadata.update(status='complete',analysis=dict(successful_records=80,median_points=16,figures=['figures/chunk_size_comparison.png','figures/chunk_size_comparison.pdf'],summary='SUMMARY.md',chunk1_comparison=summaries[1]))
    temp=directory/'metadata.json.tmp';temp.write_text(json.dumps(metadata,indent=2)+'\n');temp.replace(directory/'metadata.json')
    print('Validated 80 runs; generated heavier comparison plot and observation report',flush=True)
    return figures


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('results_dir',type=Path)
    analyse(parser.parse_args().results_dir.resolve())
