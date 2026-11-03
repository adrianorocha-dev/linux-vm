#!/usr/bin/env python3
"""Retain verified corresponding source outside the app; subsets are incomplete."""
import argparse
import configparser
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('license_notices', ROOT / 'scripts/license-notices.py')
notices = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notices)


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def run(*args, **kwargs):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs).stdout


def retention_required(manifest, key, item):
    if item.get('retention') != 'best-effort':
        return True
    components = [c for c in manifest['components'] if key in c['inputs']]
    def copyleft(component):
        # Bison's generated parser exception permits this larger work under chosen terms.
        expression = component['license'].replace('GPL-3.0-or-later WITH Bison-exception-2.2', '')
        return re.search(r'\b(?:A?GPL|LGPL)-', expression)
    notices.require(components and all(not copyleft(c) for c in components),
                    f'{key}: copyleft or unowned input cannot use best-effort retention')
    return False


def formula_sources(manifest, plan, cache):
    bottles = {key for key, item in manifest['inputs'].items() if 'bottle' in item['archive']}
    notices.require(bottles == set(plan['bottles']), 'source plan does not cover every bottle')
    records = {}
    for key in sorted(bottles):
        item = manifest['inputs'][key]
        path = cache / item['archive']
        notices.require(sha(path) == item['sha256'], f'{key}: bottle checksum differs')
        record = plan['bottles'][key]
        with tarfile.open(path) as archive:
            data = archive.extractfile(record['formula_member']).read()
        notices.require(notices.digest(data) == record['formula_sha256'], f'{key}: formula checksum differs')
        source = data.decode()
        primary = record['sources'][0]
        notices.require(re.search(r'^  url "([^"]+)"', source, re.M)[1] == primary['url'] and
                        re.search(r'^  sha256 "([a-f0-9]{64})"', source, re.M)[1] == primary['sha256'],
                        f'{key}: source differs from bottle formula')
        resources = re.findall(r'  resource "([^"]+)" do\n    url "([^"]+)"\n    sha256 "([a-f0-9]{64})"', source)
        for name, url, checksum in resources:
            notices.require(any(r.get('url') == url and r.get('sha256') == checksum for r in record['sources']),
                            f'{key}: uncovered formula resource {name}')
        patches = re.findall(r'^    file "([^"]+)"', source, re.M)
        notices.require(set(patches) == {r['formula_path'] for r in record['patches'] if 'formula_path' in r}, f'{key}: uncovered formula patch')
        for block in re.findall(r'^  patch(?: :[^\n]+)? do\n(.*?)^  end', source, re.M | re.S):
            match = re.search(r'url "([^"]+)".*?sha256 "([a-f0-9]{64})"', block, re.S)
            if match:
                notices.require(any(r['url'] == match[1] and r['sha256'] == match[2] for r in record['patches']),
                                f'{key}: uncovered external formula patch')
        if key == 'epoxy':
            commit = re.search(r'upstream_commit = "([a-f0-9]{40})"', source)[1]
            notices.require(any(r.get('commit') == commit and r['url'] == 'https://github.com/anholt/libepoxy.git'
                                for r in record['sources']), 'epoxy: uncovered implementation source')
        records[key] = data
    return records


class Collector:
    def __init__(self, stage, cache):
        self.stage = stage
        self.cache = cache
        self.artifacts = {}
        self.visited = set()

    def record(self, key, path, pin):
        self.artifacts[key] = dict(pin, path=path.relative_to(self.stage).as_posix(), bytes=path.stat().st_size,
                                   retained_sha256=sha(path))

    def download(self, key, item, existing=None):
        notices.safe_path(key)
        notices.safe_path(item['archive'])
        target = self.stage / 'archives' / key / item['archive']
        target.parent.mkdir(parents=True, exist_ok=True)
        cached = self.cache / 'downloads' / item['sha256']
        source = existing if existing and existing.is_file() else cached
        if not source.is_file():
            cached.parent.mkdir(parents=True, exist_ok=True)
            partial = cached.with_suffix('.partial')
            try:
                with urllib.request.urlopen(item['url'], timeout=60) as response, partial.open('wb') as output:
                    shutil.copyfileobj(response, output)
                notices.require(sha(partial) == item['sha256'], f'{key}: downloaded checksum differs')
                partial.replace(cached)
            finally:
                partial.unlink(missing_ok=True)
            source = cached
        notices.require(sha(source) == item['sha256'], f'{key}: checksum differs')
        shutil.copyfile(source, target)
        self.record(key, target, item)

    def git(self, key, item, local=None):
        notices.safe_path(key)
        commit = item['commit']
        notices.require(re.fullmatch('[a-f0-9]{40}', commit), f'{key}: invalid commit')
        identity = (item['url'], commit)
        if identity in self.visited:
            return
        self.visited.add(identity)
        repository = self.cache / 'git' / (hashlib.sha256(item['url'].encode()).hexdigest() + '.git')
        repository.parent.mkdir(parents=True, exist_ok=True)
        if not repository.exists():
            run('git', 'init', '--bare', '--quiet', str(repository))
        env = dict(os.environ, GIT_NO_REPLACE_OBJECTS='1')
        command = ['git', '--git-dir=' + str(repository)]
        try:
            run(*command, 'cat-file', '-e', commit + '^{commit}', env=env)
        except subprocess.CalledProcessError:
            if local and local.exists():
                try:
                    run(*command, 'fetch', '--quiet', '--depth=1', str(local), commit, env=env)
                except subprocess.CalledProcessError:
                    run(*command, 'fetch', '--quiet', '--depth=1', item['url'], commit, env=env)
            else:
                run(*command, 'fetch', '--quiet', '--depth=1', item['url'], commit, env=env)
        notices.require(run(*command, 'rev-parse', commit + '^{commit}', env=env).decode().strip() == commit,
                        f'{key}: commit differs')
        run(*command, 'fsck', '--full', '--no-reflogs', env=env)
        target = self.stage / 'git-sources' / key / (commit + '.tar.gz')
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('wb') as output:
            subprocess.run(command + ['archive', '--format=tar.gz', '--prefix=source/', commit], env=env,
                           stdout=output, check=True)
        self.record(key, target, item)
        links = [line.split(None, 3) for line in run(*command, 'ls-tree', '-r', commit, env=env).decode().splitlines()
                 if line.startswith('160000 ')]
        if not links:
            return
        modules = configparser.ConfigParser(interpolation=None)
        modules.read_string(run(*command, 'show', commit + ':.gitmodules', env=env).decode())
        urls = {modules[s]['path']: modules[s]['url'] for s in modules.sections()}
        for _, _, revision, path in links:
            notices.require(path in urls, f'{key}: missing submodule URL for {path}')
            url = urls[path]
            if url.startswith('.'):
                url = urllib.parse.urljoin(item['url'].rstrip('/') + '/', url)
            self.git(key + '/' + path, {'url': url, 'commit': revision})


def collect(args):
    manifest = notices.load()
    plan = json.loads((ROOT / 'licenses/source-inputs.json').read_text())
    requested = set(args.subset.split(',')) if args.subset else None
    items = dict(manifest['inputs'])
    expected_git = {c['id']: {k: c['source'][k] for k in ('url', 'commit')}
                    for c in manifest['components'] if 'commit' in c.get('source', {}) and 'input' not in c['source']}
    notices.require(expected_git == {key: {k: item[k] for k in ('url', 'commit')}
                                    for key, item in plan['extra_sources'].items()}, 'component git source plan differs')
    for key, value in plan['extra_sources'].items():
        items['source-' + key] = value
    for bottle in plan['bottles'].values():
        for item in bottle['sources'] + bottle['patches']:
            items[item['id']] = item
    notices.require(not requested or requested <= set(items), 'unknown subset input')
    notices.require(args.output.suffixes[-2:] == ['.tar', '.gz'], 'output must end in .tar.gz')
    notices.require(not args.output.exists(), 'output already exists')
    notices.require(all(p.suffix != '.app' for p in args.output.resolve().parents), 'source output must be outside the app')
    if not requested:
        gaps = plan['gaps'] + manifest.get('release_blockers', [])
        gaps += [c['id'] + ': incomplete license provenance' for c in manifest['components']
                 if c.get('license_status', '').startswith('incomplete')]
        notices.require(not gaps, 'complete source unavailable: ' + '; '.join(gaps))
        notices.require(not run('git', '-C', str(ROOT), 'status', '--porcelain').strip(), 'release source requires a clean checkout')
    formulas = formula_sources(manifest, plan, args.inputs)
    revision = run('git', '-C', str(ROOT), 'rev-parse', 'HEAD').decode().strip()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as directory:
        stage = Path(directory) / 'release-source'
        stage.mkdir()
        collector = Collector(stage, args.cache)
        optional_failures = {}
        for key, item in items.items():
            if requested and key not in requested:
                continue
            required = retention_required(manifest, key, item)
            print(f'retain-release-source: collecting {key}', file=sys.stderr, flush=True)
            try:
                if 'commit' in item and 'sha256' not in item:
                    prefix = item.get('archive', '').removesuffix('.tar.gz')
                    local = args.inputs / 'git' / (prefix + '.git')
                    if key == 'source-try-omarchy':
                        local = ROOT / '.deps/try-omarchy'
                    collector.git(key, item, local)
                else:
                    existing = args.inputs / item['archive']
                    if not existing.exists():
                        existing = ROOT / 'build/license-inputs' / item['archive']
                    collector.download(key, item, existing)
            except (OSError, ValueError, subprocess.CalledProcessError) as error:
                if required:
                    raise
                optional_failures[key] = str(error)
                print(f'retain-release-source: optional {key}: {error}', file=sys.stderr)
        formula_dir = stage / 'bottle-formulas'
        formula_dir.mkdir()
        for key, data in formulas.items():
            (formula_dir / (key + '.rb')).write_bytes(data)
        local = stage / 'linux-vm.tar.gz'
        with local.open('wb') as output:
            subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=tar.gz', '--prefix=linux-vm/', revision],
                           check=True, stdout=output)
        collector.record('linux-vm', local, {'commit': revision})
        for name in ('manifest.json', 'source-inputs.json'):
            shutil.copyfile(ROOT / 'licenses' / name, stage / name)
        report = {'complete': requested is None, 'revision': revision, 'subset': sorted(requested) if requested else None,
                  'gaps': plan['gaps'], 'findings': plan.get('findings', []),
                  'optional_failures': optional_failures, 'artifacts': collector.artifacts,
                  'artifact_bytes': sum(a['bytes'] for a in collector.artifacts.values()),
                  'retention': 'Keep through at least three years after the last distribution of this version.'}
        (stage / 'SOURCE-INDEX.json').write_text(json.dumps(report, indent=2) + '\n')
        checksums = {p.relative_to(stage).as_posix(): sha(p) for p in sorted(stage.rglob('*')) if p.is_file()}
        (stage / 'SHA256SUMS').write_text(''.join(f'{value}  {name}\n' for name, value in checksums.items()))
        partial = args.output.with_suffix('.gz.partial')
        try:
            with tarfile.open(partial, 'w:gz') as archive:
                archive.add(stage, arcname='release-source')
            verify_bundle(partial)
            partial.replace(args.output)
        finally:
            partial.unlink(missing_ok=True)
        checksum = sha(args.output)
        args.output.with_suffix(args.output.suffix + '.sha256').write_text(f'{checksum}  {args.output.name}\n')
        print(json.dumps({'path': str(args.output.resolve()), 'bytes': args.output.stat().st_size,
                          'complete': report['complete'], 'artifact_bytes': report['artifact_bytes'],
                          'artifacts': len(collector.artifacts), 'sha256': checksum}, indent=2))


def verify_bundle(path):
    with tarfile.open(path) as archive:
        prefix = 'release-source/'
        checksums = archive.extractfile(prefix + 'SHA256SUMS').read().decode()
        expected = {prefix + name: value for value, name in (line.split('  ', 1) for line in checksums.splitlines())}
        actual = {m.name for m in archive if m.isfile()} - {prefix + 'SHA256SUMS'}
        notices.require(actual == set(expected), 'retained source file inventory differs')
        for name, value in expected.items():
            data = archive.extractfile(name)
            notices.require(hashlib.file_digest(data, 'sha256').hexdigest() == value, f'retained checksum differs: {name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, default=ROOT / '.deps/source-archives')
    parser.add_argument('--cache', type=Path, default=ROOT / 'build/source-retention-cache')
    parser.add_argument('--subset', help='comma-separated input IDs; always marked incomplete')
    args = parser.parse_args()
    try:
        collect(args)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, tarfile.TarError) as error:
        print(f'retain-release-source: {error}', file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.decode(errors='replace').strip(), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
