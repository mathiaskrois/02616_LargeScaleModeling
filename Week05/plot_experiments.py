#!/usr/bin/env python3
"""Validate a complete saved suite and plot three sets of median runtimes."""
import argparse
from collections import defaultdict
import csv
import json
import math
import sys
from pathlib import Path
from statistics import median

from run_experiments import CONFIG_FIELDS, measurements

TITLES = {'static_blocking': 'Blocking static', 'static_nonblocking': 'Nonblocking static',
          'dynamic_blocking': 'Blocking dynamic', 'dynamic_nonblocking': 'Nonblocking dynamic'}
ORDER = list(TITLES)
INTEGER_FIELDS = ['repetition', 'nodes', 'ranks', 'ranks_per_host', 'chunk_size',
                  'width', 'height', 'actual_area']


def normalized(row):
    result = dict(row)
    for key in INTEGER_FIELDS:
        result[key] = int(row[key])
    result['target_area'] = float(row['target_area'])
    return result


def identity(row):
    return tuple(row[key] for key in CONFIG_FIELDS)


def validated_medians(rows, config):
    """Reject missing, duplicate, failed or off-grid attempts before plotting."""
    expected = {identity(normalized(row)) for row in measurements(config)}
    seen = set()
    groups = defaultdict(list)
    for raw in rows:
        row = normalized(raw)
        key = identity(row)
        if key not in expected or key in seen:
            raise ValueError('Unexpected configuration or duplicate repetition')
        if int(row['exit_status']) != 0:
            raise ValueError('Failed measurements cannot produce median points')
        runtime = float(row['runtime_seconds'])
        if not math.isfinite(runtime) or runtime <= 0:
            raise ValueError('Runtime must be finite and positive')
        seen.add(key)
        group = tuple(row[k] for k in CONFIG_FIELDS if k != 'repetition')
        groups[group].append((row, runtime))
    if seen != expected:
        raise ValueError(f'Incomplete suite: {len(seen)} of {len(expected)} successful measurements')
    medians = []
    for samples in groups.values():
        if len(samples) != config['defaults']['repetitions']:
            raise ValueError('Incomplete repetition group')
        row = {k: v for k, v in samples[0][0].items() if k != 'repetition'}
        row['median_seconds'] = median(runtime for _, runtime in samples)
        medians.append(row)
    return medians


def plot_results(result_dir, output_dir=None):
    result_dir = Path(result_dir)
    config = json.loads((result_dir / 'experiments.yaml').read_text())
    with (result_dir / config['output']['csv']).open(newline='') as stream:
        points = validated_medians(list(csv.DictReader(stream)), config)
    try:
        import six  # Required by dateutil in the cluster Matplotlib module.
    except ModuleNotFoundError:
        sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
        import six
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output_dir = Path(output_dir) if output_dir else result_dir / 'figures'
    output_dir.mkdir(parents=True, exist_ok=True)
    defaults = config['defaults']
    dimensions = f"{defaults['width']}×{defaults['height']}"
    ranks, nodes, chunk = defaults['ranks'], defaults['nodes'], defaults['chunk_size']
    settings = {
        'nodes': ('nodes', 'Physical nodes', f'{ranks} total ranks; {dimensions} pixels; chunk size {chunk} rows.'),
        'chunk_size': ('chunk_size', 'Chunk size (rows)', f'{ranks} total ranks on the first {nodes} hosts; {dimensions} pixels.'),
        'image_area': ('actual_area', 'Actual image area (pixels)', f'{ranks} total ranks on the first {nodes} hosts; chunk size {chunk} rows.')}
    paths = []
    for experiment, (key, xlabel, caption) in settings.items():
        fig, axes = plt.subplots(2, 2, figsize=(10, 7), sharex=True, sharey=True)
        subset = [p for p in points if p['experiment'] == experiment]
        xmax, xmin = max(p[key] for p in subset), min(p[key] for p in subset)
        ymax = max(p['median_seconds'] for p in subset)
        for ax, impl in zip(axes.flat, ORDER):
            series = sorted((p for p in subset if p['implementation'] == impl), key=lambda p: p[key])
            ax.plot([p[key] for p in series], [p['median_seconds'] for p in series], marker='o')
            ax.set_title(TITLES[impl])
            ax.set_xlim(xmin - (xmax-xmin)*0.04, xmax + (xmax-xmin)*0.04)
            ax.set_ylim(0, ymax * 1.1)
            ax.set_xlabel(xlabel)
            ax.set_ylabel('Median complete runtime (s)')
            ax.grid(alpha=0.3)
            if experiment == 'nodes':
                ax.set_xticks(config['experiments']['nodes']['values'])
        fig.text(0.5, 0.025, caption + f"\nImage limits {defaults['xlim']}, {defaults['ylim']}; {defaults['iterations']} iterations; median of {defaults['repetitions']} repetitions.",
                 ha='center', fontsize=10)
        fig.tight_layout(rect=(0, 0.09, 1, 1))
        for extension in ['png', 'pdf']:
            path = output_dir / f'{experiment}.{extension}'
            fig.savefig(path, dpi=180)
            paths.append(path)
        plt.close(fig)
    # Acceptance includes all six exported files, not just figure construction.
    if len(paths) != 6 or any(not path.is_file() or path.stat().st_size == 0 for path in paths):
        raise RuntimeError('Missing figure output')
    metadata_path = result_dir / 'metadata.json'
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        metadata.update(status='complete', analysis=dict(successful_records=240,
                        figures=[str(p.resolve()) for p in paths]))
        temporary = metadata_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(metadata, indent=2) + '\n')
        temporary.replace(metadata_path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results_dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    paths = plot_results(args.results_dir, args.output_dir)
    print('Validated 240 successful measurements; saved ' + ', '.join(str(p) for p in paths))


if __name__ == '__main__':
    main()
