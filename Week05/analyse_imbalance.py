#!/usr/bin/env python3
"""Validate the imbalance suite, plot per-rank computation time and write SUMMARY.md."""
import argparse
import csv
import json
from pathlib import Path
from statistics import median
import sys

from run_imbalance import profile_records

TITLES = {'static_blocking': 'Static (cyclic)', 'dynamic_blocking': 'Dynamic (rank 0 manages)'}


def validate(directory):
    config = json.loads((directory / 'experiments.yaml').read_text())
    with (directory / config['output']['csv']).open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    expected = len(config['implementations']) * len(config['chunk_sizes']) * config['defaults']['repetitions']
    if len(rows) != expected or any(r['exit_status'] != '0' for r in rows):
        raise ValueError(f'Expected exactly {expected} successful records')
    keys = {(r['implementation'], int(r['chunk_size']), int(r['repetition'])) for r in rows}
    if len(keys) != expected:
        raise ValueError('Duplicate or missing configuration')
    profiles = {}
    for r in rows:
        key = (r['implementation'], int(r['chunk_size']), int(r['repetition']))
        profiles[key] = profile_records(directory / r['profile_log'], r['implementation'],
                                        int(r['width']), int(r['chunk_size']))
    return config, rows, profiles


def summarise(config, rows, profiles):
    """Median per-rank values and imbalance ratios for every implementation and chunk size."""
    reps = range(1, config['defaults']['repetitions'] + 1)
    result = {}
    for impl in config['implementations']:
        for chunk in config['chunk_sizes']:
            runs = [sorted(profiles[impl, chunk, rep], key=lambda r: r['rank']) for rep in reps]
            compute = [median(run[rank]['compute_seconds'] for run in runs) for rank in range(8)]
            chunks = [median(run[rank].get('chunks', 0) for run in runs) for rank in range(8)]
            # Static: all 8 ranks compute. Dynamic: only workers 1..7 compute.
            workers = range(8) if impl == 'static_blocking' else range(1, 8)
            def ratios(run):
                times = [run[rank]['compute_seconds'] for rank in workers]
                total = sum(run[rank]['compute_seconds'] for rank in range(8))
                return max(times) / (sum(times) / len(times)), max(times) / (total / 8)
            per_run = [ratios(run) for run in runs]
            runtime = median(float(r['runtime_seconds']) for r in rows
                             if r['implementation'] == impl and int(r['chunk_size']) == chunk)
            result[impl, chunk] = dict(compute=compute, chunks=chunks, runtime=runtime,
                max_over_mean=median(p[0] for p in per_run), max_over_ideal8=median(p[1] for p in per_run),
                total_compute=median(sum(r['compute_seconds'] for r in run) for run in runs))
    return result


def analyse(directory):
    config, rows, profiles = validate(directory)
    summary = summarise(config, rows, profiles)
    try:
        import six  # Required by dateutil in the cluster Matplotlib module.
    except ModuleNotFoundError:
        sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
        import six
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    chunks = config['chunk_sizes']
    output = directory / 'figures'; output.mkdir(exist_ok=True)
    paths = []

    def save(fig, name):
        for suffix in ('png', 'pdf'):
            path = output / f'{name}.{suffix}'; fig.savefig(path, dpi=180); paths.append(path)
        plt.close(fig)

    # Per-rank computation time: one panel per implementation and chunk size.
    fig, axes = plt.subplots(2, len(chunks), figsize=(3 * len(chunks), 6.5), sharex=True, sharey=True)
    for row_axes, impl in zip(axes, config['implementations']):
        for ax, chunk in zip(row_axes, chunks):
            s = summary[impl, chunk]
            ax.bar(range(8), s['compute'], color='#2a78d6')
            ax.axhline(s['total_compute'] / 8, color='#52514e', linestyle='--', linewidth=1)
            ax.set_title(f'{TITLES[impl]}\nchunk {chunk}', fontsize=9)
            ax.set_xticks(range(8)); ax.grid(axis='y', alpha=.3)
            if ax is row_axes[0]:
                ax.set_ylabel('Computation time (s)')
            if impl == list(config['implementations'])[-1]:
                ax.set_xlabel('Rank')
    d = config['defaults']
    fig.text(.5, .01, f'{d["width"]}×{d["height"]}; {d["ranks"]} ranks on {d["nodes"]} hosts; '
             f'median of {d["repetitions"]} runs per rank. '
             'Dashed line: total computation time / 8 (perfect balance over 8 ranks).', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .04, 1, 1)); save(fig, 'rank_compute')

    # Imbalance ratio: slowest rank versus perfect balance over 8 ranks.
    fig, ax = plt.subplots(figsize=(6.3, 3.6))
    for impl, colour, marker in (('static_blocking', '#2a78d6', 'o'), ('dynamic_blocking', '#eb6834', 's')):
        ax.plot(chunks, [summary[impl, c]['max_over_ideal8'] for c in chunks], color=colour,
                marker=marker, label=TITLES[impl])
    ax.axhline(1, color='#52514e', linestyle='--', linewidth=1)
    ax.axhline(8 / 7, color='#52514e', linestyle=':', linewidth=1)
    ax.set_xscale('log'); ax.set_xticks(chunks); ax.set_xticklabels([str(c) for c in chunks])
    ax.minorticks_off(); ax.set_ylim(bottom=0)
    ax.set_xlabel('Chunk size (rows, log scale)'); ax.set_ylabel('Slowest rank / (total / 8)')
    ax.grid(axis='y', alpha=.3); ax.legend(frameon=False)
    fig.tight_layout(); save(fig, 'imbalance_ratio')

    d = config['defaults']
    setup = f'{d["width"]}×{d["height"]}; {d["ranks"]} ranks on {d["nodes"]} hosts'
    text = ['# Load-imbalance measurements', '',
            f'{len(rows)} successful runs; {setup}; median of '
            f'{config["defaults"]["repetitions"]} repetitions. Computation time excludes MPI calls.', '',
            '## Imbalance per chunk size', '',
            '| Implementation | Chunk rows | Runtime (s) | Max/mean over computing ranks | Slowest / (total/8) |',
            '|---|---:|---:|---:|---:|']
    for impl in config['implementations']:
        for chunk in chunks:
            s = summary[impl, chunk]
            text.append(f'| {TITLES[impl]} | {chunk} | {s["runtime"]:.2f} | {s["max_over_mean"]:.3f} | {s["max_over_ideal8"]:.3f} |')
    text += ['', '## Median computation time per rank (s)', '',
             '| Implementation | Chunk rows | ' + ' | '.join(f'Rank {r}' for r in range(8)) + ' |',
             '|---|---:|' + '---:|' * 8]
    for impl in config['implementations']:
        for chunk in chunks:
            text.append(f'| {TITLES[impl]} | {chunk} | ' + ' | '.join(f'{v:.1f}' for v in summary[impl, chunk]['compute']) + ' |')
    text += ['', '## Dynamic scheduler: median chunks computed per worker', '',
             '| Chunk rows | ' + ' | '.join(f'Rank {r}' for r in range(1, 8)) + ' |', '|---:|' + '---:|' * 7]
    for chunk in chunks:
        text.append(f'| {chunk} | ' + ' | '.join(f'{v:g}' for v in summary['dynamic_blocking', chunk]['chunks'][1:]) + ' |')
    text += ['', '## Notes', '',
             'Static uses Mandelbrot_blocking_static_interleaved.py (same algorithm as Mandelbrot_blocking_static.py, '
             'with timers). Dynamic uses Mandelbrot_dynamic_profiled.py (same algorithm as Mandelbrot_blocking_dynamic.py, '
             'with timers). Both reproduced the serial reference exactly before measurement.',
             'Computation time per rank does not depend on blocking versus nonblocking communication for static '
             'scheduling, since the row assignment is identical.',
             '', '## Figures', '']
    for name in ('rank_compute', 'imbalance_ratio'):
        text += [f'![{name}](figures/{name}.png)', f'[PDF](figures/{name}.pdf)', '']
    (directory / 'SUMMARY.md').write_text('\n'.join(text) + '\n', encoding='utf-8')
    metadata_path = directory / 'metadata.json'
    metadata = json.loads(metadata_path.read_text())
    metadata.update(status='complete', analysis=dict(successful_records=len(rows),
                    figures=[str(p) for p in paths], report='SUMMARY.md'))
    temp = metadata_path.with_suffix('.json.tmp'); temp.write_text(json.dumps(metadata, indent=2) + '\n')
    temp.replace(metadata_path)
    print(f'Validated {len(rows)} measurements and profiles; saved {len(paths)} figures and SUMMARY.md', flush=True)
    return paths


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('results_dir', type=Path)
    analyse(parser.parse_args().results_dir.resolve())
