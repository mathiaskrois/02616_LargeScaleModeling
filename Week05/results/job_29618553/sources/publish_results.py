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
    with (directory / config['output']['csv']).open(newline='') as stream:
        points = validated_medians(list(csv.DictReader(stream)), config)
    for experiment in ('nodes', 'chunk_size', 'image_area'):
        for suffix in ('png', 'pdf'):
            figure = directory / 'figures' / f'{experiment}.{suffix}'
            if not figure.is_file() or not figure.stat().st_size:
                raise ValueError(f'Missing figure: {figure.name}')
    return metadata, config, len(points)


def update_readme(content, directory, metadata, config):
    relative = f'Week05/results/{directory.name}'
    model = metadata.get('cpu_model', 'See metadata.json for CPU model')
    defaults = config['defaults']
    block = (f'{START}\n## Latest completed benchmark\n\n'
             f'Job **{metadata["job_id"]}**: 240 successful measurements, three repetitions '
             f'per configuration, on the same allocated hosts. CPU: {model}.\n\n'
             f'Node and chunk tests: {defaults["width"]}×{defaults["height"]} pixels. '
             f'[Saved results]({relative}/metadata.json) include configuration, timings, '
             f'source snapshots, placement checks and logs.\n\n'
             + '\n'.join(f'- [{name.replace("_", " ").title()} figure]({relative}/figures/{name}.png)'
                         for name in ('nodes', 'chunk_size', 'image_area'))
             + f'\n{END}')
    if START in content and END in content:
        before, rest = content.split(START, 1)
        _, after = rest.split(END, 1)
        return before + block + after
    return content.rstrip() + '\n\n' + block + '\n'


def publish(directory, dry_run=False):
    directory = directory.resolve()
    repo = Path(__file__).resolve().parents[1]
    if directory.parent != repo / 'Week05' / 'results':
        raise ValueError('Results must be a job directory in this repository')
    metadata, config, count = validate(directory)
    if dry_run:
        print(f'Validated job {metadata["job_id"]}: 240 measurements, {count} medians, six figures')
        return
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    auth, gh = repo / '.github-auth', repo / '.tools' / 'gh'
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
    scratch = repo / '.tools'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='publish-', dir=scratch) as temporary:
        checkout = Path(temporary) / 'checkout'
        git('clone', '--branch', 'main', '--single-branch', remote, str(checkout))
        if auth.is_dir() and gh.is_file():
            import shlex
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
        git('commit', '-m', f'Publish completed Mandelbrot benchmark job {metadata["job_id"]}', cwd=checkout)
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
