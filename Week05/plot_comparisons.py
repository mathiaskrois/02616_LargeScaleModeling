#!/usr/bin/env python3
"""Export overlaid implementations or a single implementation from a saved suite."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import sys

from plot_experiments import TITLES, ORDER, normalized, validated_medians
from run_experiments import CONFIG_FIELDS

STYLES = {
    'static_blocking': ('#0072B2', '-', 'o'),
    'static_nonblocking': ('#E69F00', '--', 's'),
    'dynamic_blocking': ('#009E73', '-.', '^'),
    'dynamic_nonblocking': ('#CC79A7', ':', 'D'),
}


def plot_comparisons(results_dir, implementation=None):
    results_dir = Path(results_dir)
    config = json.loads((results_dir / 'experiments.yaml').read_text())
    with (results_dir / config['output']['csv']).open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    points = validated_medians(rows, config)
    samples = defaultdict(list)
    for raw in rows:
        row = normalized(raw)
        samples[tuple(row[k] for k in CONFIG_FIELDS if k != 'repetition')].append(float(row['runtime_seconds']))
    try:
        import six
    except ModuleNotFoundError:
        sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
        import six
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    defaults = config['defaults']
    output = results_dir / 'figures' / (implementation or 'overlaid')
    output.mkdir(parents=True, exist_ok=True)
    settings = {
        'nodes': ('nodes', 'Physical nodes', f"{defaults['ranks']} total ranks; {defaults['width']}×{defaults['height']} pixels; chunk {defaults['chunk_size']} rows"),
        'chunk_size': ('chunk_size', 'Chunk size (rows)', f"{defaults['ranks']} ranks on {defaults['nodes']} hosts; {defaults['width']}×{defaults['height']} pixels"),
        'image_area': ('actual_area', 'Actual image area (pixels)', f"{defaults['ranks']} ranks on {defaults['nodes']} hosts; chunk {defaults['chunk_size']} rows"),
    }
    paths = []
    for experiment, (key, xlabel, fixed) in settings.items():
        fig, ax = plt.subplots(figsize=(10, 6))
        for impl in ([implementation] if implementation else ORDER):
            series = sorted((p for p in points if p['experiment'] == experiment and p['implementation'] == impl), key=lambda p: p[key])
            ranges = [samples[tuple(p[k] for k in CONFIG_FIELDS if k != 'repetition')] for p in series]
            lower = [p['median_seconds'] - min(v) for p, v in zip(series, ranges)]
            upper = [max(v) - p['median_seconds'] for p, v in zip(series, ranges)]
            color, linestyle, marker = STYLES[impl]
            ax.errorbar([p[key] for p in series], [p['median_seconds'] for p in series],
                        yerr=[lower, upper], color=color, linestyle=linestyle,
                        marker=marker, linewidth=2, markersize=6, capsize=3,
                        label=TITLES[impl])
        ax.set_title(f"{TITLES[implementation] if implementation else 'Four MPI implementations'} — {experiment.replace('_', ' ')}\n{results_dir.name}")
        ax.set_xlabel(xlabel)
        ax.set_ylabel('Median complete runtime (s)')
        ax.set_ylim(bottom=0)
        ax.grid(alpha=0.25)
        ax.legend(loc='best')
        if experiment == 'nodes':
            ax.set_xticks(config['experiments']['nodes']['values'])
        fig.text(0.5, 0.025, fixed + f"\n{defaults['iterations']} iterations; median of {defaults['repetitions']} repetitions; bars show min–max.\nImage limits: {defaults['xlim']}, {defaults['ylim']}.", ha='center', fontsize=9)
        fig.tight_layout(rect=(0, 0.13, 1, 1))
        for extension in ('png', 'pdf'):
            path = output / f'{experiment}.{extension}'
            fig.savefig(path, dpi=180)
            paths.append(path)
        plt.close(fig)
    return paths


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results_dir', type=Path)
    parser.add_argument('--implementation', choices=ORDER)
    args = parser.parse_args()
    for path in plot_comparisons(args.results_dir, args.implementation):
        print(path)
