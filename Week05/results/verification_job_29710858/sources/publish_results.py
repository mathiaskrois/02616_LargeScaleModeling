#!/usr/bin/env python3
"""Validate and publish one completed job without changing the experiment checkout."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile

from plot_experiments import validated_medians

START = '<!-- latest-benchmark:start -->'
END = '<!-- latest-benchmark:end -->'


def validate(directory):
    metadata = json.loads((directory / 'metadata.json').read_text())
    if metadata.get('status') != 'complete':
        raise ValueError('Only completed suites can be published')
    config = json.loads((directory / 'experiments.yaml').read_text())
    if config.get('suite') == 'five_versions':
        from verify_and_benchmark import validate_saved
        validate_saved(directory)
        for name in ('SUMMARY.md', 'figures/benchmark_overview.png', 'figures/benchmark_overview.pdf'):
            if not (directory / name).is_file() or not (directory / name).stat().st_size:
                raise ValueError(f'Missing five-version output: {name}')
        return metadata, config, 5
    with (directory / config['output']['csv']).open(newline='') as stream:
        points = validated_medians(list(csv.DictReader(stream)), config)
    if config.get('suite') == 'followup':
        from analyse_followup import validate as validate_followup
        validate_followup(directory)
        figures = ('threshold', 'one_vs_two', 'rank_timings')
        if not (directory / 'SUMMARY.md').is_file():
            raise ValueError('Missing follow-up summary')
    else:
        figures = ('nodes', 'chunk_size', 'image_area')
    for experiment in figures:
        for suffix in ('png', 'pdf'):
            figure = directory / 'figures' / f'{experiment}.{suffix}'
            if not figure.is_file() or not figure.stat().st_size:
                raise ValueError(f'Missing figure: {figure.name}')
    return metadata, config, len(points)


def update_readme(content, directory, metadata, config):
    if config.get('suite') == 'five_versions':
        return update_five_version_readme(content, directory, metadata)
    if config.get('suite') == 'followup':
        return update_followup_readme(content, directory, metadata)
    relative = f'Week05/results/{directory.name}'
    model = metadata.get('cpu_model', 'See metadata.json for CPU model')
    defaults = config['defaults']
    block = (f'{START}\n## Latest completed benchmark\n\n'
             f'Job **{metadata["job_id"]}**: 240 successful measurements, three repetitions '
             f'per configuration, on the same allocated hosts. CPU: {model}.\n\n'
             f'Node and chunk tests: {defaults["width"]}×{defaults["height"]} pixels. '
             f'[Saved results]({relative}/metadata.json) include configuration, timings, '
             f'source snapshots, placement checks and logs.\n\n'
             + '\n\n'.join(f'### {name.replace("_", " ").title()}\n\n![{name.replace("_", " ").title()} runtime plot]({relative}/figures/{name}.png)\n\n[Download PDF]({relative}/figures/{name}.pdf)'
                         for name in ('nodes', 'chunk_size', 'image_area'))
             + f'\n{END}')
    if START in content and END in content:
        before, rest = content.split(START, 1)
        _, after = rest.split(END, 1)
        return before + block + after
    return content.rstrip() + '\n\n' + block + '\n'


def update_followup_readme(content, directory, metadata):
    start, end = '<!-- followup:start -->', '<!-- followup:end -->'
    relative = f'Week05/results/{directory.name}'
    block = (f'{start}\n## Completed diagnostic follow-up\n\n'
             f'Job **{metadata["job_id"]}**: **175 successful measurements**, five repetitions; '
             '3000×3000 pixels, eight ranks; chunks 8–12 and one versus two hosts.\n\n'
             f'[Results and interpretation]({relative}/SUMMARY.md). CPU: {metadata["cpu_model"]}.\n\n'
             + '\n\n'.join(f'![{name.replace("_", " ")} diagnostic plot]({relative}/figures/{name}.png)\n\n[PDF]({relative}/figures/{name}.pdf)'
                             for name in ('threshold', 'one_vs_two', 'rank_timings'))
             + f'\n{end}')
    if start in content and end in content:
        before, rest = content.split(start, 1)
        _, after = rest.split(end, 1)
        return before + block + after
    position = content.find(START)
    if position == -1:
        position = content.find('\n## ')
    if position == -1:
        position = len(content)
    return content[:position] + block + '\n\n' + content[position:]


def update_five_version_readme(content, directory, metadata):
    start,end='<!-- five-versions:start -->','<!-- five-versions:end -->'
    relative=f'Week05/results/{directory.name}'
    summary=(directory/'SUMMARY.md').read_text()
    table=summary.split('<!-- overview-table:start -->',1)[1].split('<!-- overview-table:end -->',1)[0].strip()
    block=(f'{start}\n## Correctness and compact five-version benchmark\n\n'
        '**72 full-image/chunk configurations passed exact `np.array_equal` checks** '
        'against the original serial Mandelbrot.py, covering every heavier image/chunk setting. '
        'All 15 benchmark outputs also matched, including 4500 row-chunk comparisons.\n\n'
        '3000×3000; chunk 10; 100 iterations; median of three fresh sequential runs. '
        'Serial uses one rank; MPI uses eight ranks on the same two hosts.\n\n'
        +table+'\n\n'
        f'CPU: {metadata["cpu_model"]}. Serial benchmark timing omits only its plotting section; '
        'all versions export arrays. Speedups compare complete workflows.\n\n'
        f'[Correctness evidence and methods]({relative}/SUMMARY.md) · '
        f'[Raw benchmark records]({relative}/measurements.csv)\n\n'
        f'![Five-version benchmark]({relative}/figures/benchmark_overview.png)\n\n'
        f'[PDF]({relative}/figures/benchmark_overview.pdf)\n{end}')
    if start in content and end in content:
        before,rest=content.split(start,1);_,after=rest.split(end,1)
        return before+block+after
    position=content.find(START)
    if position==-1:position=len(content)
    return content[:position]+block+'\n\n'+content[position:]


def publish(directory, dry_run=False):
    directory = directory.resolve()
    repo = Path(__file__).resolve().parents[1]
    if directory.parent != repo / 'Week05' / 'results':
        raise ValueError('Results must be a job directory in this repository')
    metadata, config, count = validate(directory)
    if dry_run:
        print(f'Validated job {metadata["job_id"]}: {count * config["defaults"]["repetitions"]} measurements, {count} medians, validated figure exports')
        return
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=repo, text=True).strip())
    credential_root = (repo / common).resolve().parent
    auth, gh = credential_root / '.github-auth', credential_root / '.tools' / 'gh'
    if auth.is_dir() and gh.is_file():
        env['GH_CONFIG_DIR'] = str(auth)
    def git(*args, cwd=repo, capture=False):
        command = ['git']
        if auth.is_dir() and gh.is_file():
            helper = f'!GH_CONFIG_DIR={shlex.quote(str(auth))} {shlex.quote(str(gh))} auth git-credential'
            command += ['-c', 'credential.helper=', '-c', f'credential.helper={helper}']
        return subprocess.run([*command, *args], cwd=cwd, env=env, check=True,
                              text=True, capture_output=capture).stdout
    remote = git('remote', 'get-url', 'origin', capture=True).strip()
    # Keep credentials and transient publication files in the already excluded directory.
    scratch = credential_root / '.tools'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='publish-', dir=scratch) as temporary:
        checkout = Path(temporary) / 'checkout'
        git('clone', '--branch', 'main', '--single-branch', remote, str(checkout))
        if auth.is_dir() and gh.is_file():
            helper = f'!GH_CONFIG_DIR={shlex.quote(str(auth))} {shlex.quote(str(gh))} auth git-credential'
            git('config', 'credential.helper', '', cwd=checkout)
            git('config', '--add', 'credential.helper', helper, cwd=checkout)
        for key in ('user.name', 'user.email'):
            git('config', key, git('config', '--get', key, capture=True).strip(), cwd=checkout)
        relative = Path('Week05') / 'results' / directory.name
        destination = checkout / relative
        if destination.exists():
            raise ValueError('This job directory is already published; refusing to overwrite it')
        shutil.copytree(directory, destination)
        readme = checkout / 'README.md'
        readme.write_text(update_readme(readme.read_text(), directory, metadata, config))
        git('add', '--', str(relative), 'README.md', cwd=checkout)
        git('commit', '--quiet', '-m', f'Publish completed Mandelbrot benchmark job {metadata["job_id"]}', cwd=checkout)
        # Concurrent teammate pushes are incorporated without force-pushing.
        for attempt in range(3):
            git('pull', '--rebase', 'origin', 'main', cwd=checkout)
            try:
                git('push', 'origin', 'HEAD:main', cwd=checkout)
                revision = git('rev-parse', 'HEAD', cwd=checkout, capture=True).strip()
                print(f'Published job {metadata["job_id"]} to {remote} at {revision}', flush=True)
                return
            except subprocess.CalledProcessError:
                if attempt == 2:
                    raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results_dir', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    publish(args.results_dir, args.dry_run)


if __name__ == '__main__':
    main()
