#!/usr/bin/env python3
"""Validate the scaling suite, plot speedup and node placement, and write SUMMARY.md."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
from statistics import median
import sys

from run_scaling import measurements

TITLES = {'static_nonblocking': 'Nonblocking static', 'dynamic_nonblocking': 'Nonblocking dynamic'}
STYLE = {'static_nonblocking': ('#2a78d6', 'o'), 'dynamic_nonblocking': ('#eb6834', 's')}


def key(row):
    return (row['experiment'], row['implementation'], int(row['ranks']), int(row['nodes']), int(row['width']))


def validate(directory):
    config = json.loads((directory / 'experiments.yaml').read_text())
    with (directory / config['output']['csv']).open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    expected = sorted((key(r), r['repetition']) for r in measurements(config))
    observed = sorted((key(r), int(r['repetition'])) for r in rows)
    if observed != expected or any(r['exit_status'] != '0' for r in rows):
        raise ValueError(f'Expected exactly the {len(expected)} configured, successful records')
    samples = defaultdict(list)
    for r in rows:
        samples[key(r)].append(float(r['runtime_seconds']))
    return config, rows, samples


def analyse(directory):
    config, rows, samples = validate(directory)
    d, e = config['defaults'], config['experiments']
    med = {k: median(v) for k, v in samples.items()}
    try:
        import six  # Required by dateutil in the cluster Matplotlib module.
    except ModuleNotFoundError:
        sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
        import six
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output = directory / 'figures'; output.mkdir(exist_ok=True)
    paths = []

    def save(fig, name):
        for suffix in ('png', 'pdf'):
            path = output / f'{name}.{suffix}'; fig.savefig(path, dpi=180); paths.append(path)
        plt.close(fig)

    ranks = e['scaling']['ranks']
    slots = config['cluster']['slots_per_host']
    scaling = {}
    for impl in config['implementations']:
        points = [next(k for k in med if k[:3] == ('scaling', impl, p)) for p in ranks]
        base = med[points[0]]
        scaling[impl] = [dict(ranks=k[2], nodes=k[3], median=med[k], low=min(samples[k]), high=max(samples[k]),
                              speedup=base / med[k], efficiency=base / med[k] / k[2]) for k in points]

    # Speedup and parallel efficiency, each relative to the same implementation on 1 rank.
    fig, (left, right) = plt.subplots(1, 2, figsize=(10, 4))
    left.plot(ranks, ranks, color='#52514e', linestyle='--', linewidth=1, label='Ideal ($S=P$)')
    # Dynamic computes on P-1 workers, so its ideal is S = max(1, P-1).
    workers = [max(1, p - 1) for p in ranks]
    left.plot(ranks, workers, color=STYLE['dynamic_nonblocking'][0], linestyle=':', linewidth=1.2,
              label='Ideal dynamic ($S=P-1$)')
    right.plot(ranks, [w / p for w, p in zip(workers, ranks)], color=STYLE['dynamic_nonblocking'][0],
               linestyle=':', linewidth=1.2)
    for impl, points in scaling.items():
        colour, marker = STYLE[impl]
        base = points[0]['median']
        # Error bars: speedup range from the fastest and slowest of the repetitions at P ranks.
        speed = [p['speedup'] for p in points]
        speed_err = [[s - base / p['high'] for s, p in zip(speed, points)],
                     [base / p['low'] - s for s, p in zip(speed, points)]]
        left.errorbar(ranks, speed, yerr=speed_err, color=colour, marker=marker, capsize=3, label=TITLES[impl])
        eff = [p['efficiency'] for p in points]
        eff_err = [[e - base / p['high'] / p['ranks'] for e, p in zip(eff, points)],
                   [base / p['low'] / p['ranks'] - e for e, p in zip(eff, points)]]
        right.errorbar(ranks, eff, yerr=eff_err, color=colour, marker=marker, capsize=3, label=TITLES[impl])
    for ax in (left, right):
        ax.set_xscale('log', base=2); ax.set_xticks(ranks); ax.set_xticklabels([str(p) for p in ranks])
        ax.minorticks_off(); ax.set_xlabel('MPI ranks $P$'); ax.grid(alpha=.3)
    left.set_yscale('log', base=2); left.set_yticks(ranks); left.set_yticklabels([str(p) for p in ranks])
    left.set_ylabel('Speedup $T_1/T_P$'); left.legend(frameon=False)
    right.axhline(1, color='#52514e', linestyle='--', linewidth=1)
    right.set_ylim(0, 1.15); right.set_ylabel('Parallel efficiency $T_1/(P\\,T_P)$')
    fig.text(.5, .01, f'{d["width"]}×{d["height"]}; chunk size {d["chunk_size"]}; up to {slots} ranks per host '
             f'(16 ranks = 2 hosts, 64 = 8 hosts); median of {d["repetitions"]} runs, '
             'error bars from the fastest and slowest run.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .05, 1, 1)); save(fig, 'speedup')

    # Fixed 8 ranks on 1/2/4/8 hosts for a small and a large image.
    hosts, sides = e['nodes']['hosts'], e['nodes']['sides']
    fig, axes = plt.subplots(1, len(sides), figsize=(10, 4))
    for ax, side in zip(axes, sides):
        for impl in config['implementations']:
            colour, marker = STYLE[impl]
            ks = [('nodes', impl, e['nodes']['ranks'], h, side) for h in hosts]
            ax.errorbar(hosts, [med[k] for k in ks],
                        yerr=[[med[k] - min(samples[k]) for k in ks], [max(samples[k]) - med[k] for k in ks]],
                        color=colour, marker=marker, capsize=3, label=TITLES[impl])
        ax.set_xscale('log', base=2); ax.set_xticks(hosts); ax.set_xticklabels([str(h) for h in hosts])
        ax.minorticks_off(); ax.set_ylim(bottom=0); ax.grid(alpha=.3)
        ax.set_title(f'{side}×{side} image'); ax.set_xlabel('Hosts'); ax.set_ylabel('Complete run time (s)')
    axes[0].legend(frameon=False)
    fig.text(.5, .01, f'{e["nodes"]["ranks"]} ranks in total; chunk size {d["chunk_size"]}; '
             f'median of {d["repetitions"]} runs; error bars show min–max.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .05, 1, 1)); save(fig, 'nodes')

    text = ['# Scaling and node-placement measurements', '',
            f'{len(rows)} successful runs; chunk size {d["chunk_size"]}; median of {d["repetitions"]} repetitions; '
            'complete launch-to-exit run times.', '',
            f'## Strong scaling ({d["width"]}×{d["height"]})', '',
            '| Implementation | Ranks | Hosts | Median (s) | Min–max (s) | Speedup | Efficiency |',
            '|---|---:|---:|---:|---|---:|---:|']
    for impl, points in scaling.items():
        for p in points:
            text.append(f'| {TITLES[impl]} | {p["ranks"]} | {p["nodes"]} | {p["median"]:.2f} | '
                        f'{p["low"]:.2f}–{p["high"]:.2f} | {p["speedup"]:.2f} | {p["efficiency"]:.3f} |')
    text += ['', f'## {e["nodes"]["ranks"]} ranks on different numbers of hosts', '',
             '| Image | Implementation | Hosts | Median (s) | Min–max (s) | Relative to 1 host |',
             '|---|---|---:|---:|---|---:|']
    for side in sides:
        for impl in config['implementations']:
            one = med['nodes', impl, e['nodes']['ranks'], hosts[0], side]
            for h in hosts:
                k = ('nodes', impl, e['nodes']['ranks'], h, side)
                text.append(f'| {side}×{side} | {TITLES[impl]} | {h} | {med[k]:.2f} | '
                            f'{min(samples[k]):.2f}–{max(samples[k]):.2f} | {med[k] / one:.3f} |')
    text += ['', '## Notes', '',
             'Speedup and efficiency use the same implementation on one rank as reference. The dynamic '
             'scheduler computes on P−1 workers (rank 0 manages) when P > 1; with one rank, rank 0 computes alone.',
             'Scaling runs fill hosts completely: up to 8 ranks on one host, 16 on two, 32 on four, 64 on eight.',
             'All runs share one allocation; hosts may also run other users\' jobs.',
             '', '## Figures', '']
    for name in ('speedup', 'nodes'):
        text += [f'![{name}](figures/{name}.png)', f'[PDF](figures/{name}.pdf)', '']
    (directory / 'SUMMARY.md').write_text('\n'.join(text) + '\n', encoding='utf-8')
    metadata_path = directory / 'metadata.json'
    metadata = json.loads(metadata_path.read_text())
    metadata.update(status='complete', analysis=dict(successful_records=len(rows),
                    figures=[str(p) for p in paths], report='SUMMARY.md'))
    temp = metadata_path.with_suffix('.json.tmp'); temp.write_text(json.dumps(metadata, indent=2) + '\n')
    temp.replace(metadata_path)
    print(f'Validated {len(rows)} measurements; saved {len(paths)} figures and SUMMARY.md', flush=True)
    return paths


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('results_dir', type=Path)
    analyse(parser.parse_args().results_dir.resolve())
