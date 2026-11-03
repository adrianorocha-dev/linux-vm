#!/usr/bin/env python3
"""Assemble notices and reject unreviewed bundle or Guest Tools contents."""
import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'licenses/manifest.json'


class LicenseError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise LicenseError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load(path=MANIFEST):
    return json.loads(path.read_text())


def component_version(component, root=ROOT):
    source = component.get('version_file')
    if source == 'macos/Resources/Info.plist':
        return plistlib.loads((root / source).read_bytes())['CFBundleShortVersionString']
    if source == 'guest/build.py':
        return re.search(r"^VERSION = '([^']+)'$", (root / source).read_text(), re.M)[1]
    require(source is None, f'unsupported version source: {source}')
    return component['version']


def release_blockers(manifest):
    blockers = list(manifest.get('release_blockers', []))
    contact = manifest['offer_contact'].strip()
    if not contact or contact.endswith('_UNSET'):
        blockers.append('set offer_contact in licenses/manifest.json before Developer ID signing')
    return blockers


def safe_path(name):
    path = PurePosixPath(name)
    require(name and not path.is_absolute() and '..' not in path.parts and str(path) == name,
            f'unsafe manifest path: {name!r}')
    return path


def shell_assignments(source):
    result = {}
    for line in source.splitlines():
        match = re.fullmatch(r'(?:readonly )?(\w+)=(.*)', line)
        if match:
            value = match[2].strip('"')
            result[match[1]] = re.sub(r'\$(\w+)|\$\{(\w+)\}',
                                    lambda m: result.get(m[1] or m[2], m[0]), value)
    return result


@contextmanager
def patched_checkout(root=ROOT):
    pins = shell_assignments((root / 'runtime/source-pins.sh').read_text())
    with tempfile.TemporaryDirectory() as directory:
        checkout = Path(directory) / 'try-omarchy'
        reference = root / '.deps/try-omarchy'
        command = ['git', 'clone', '--quiet', '--no-hardlinks', str(reference), str(checkout)] if reference.is_dir() else [
            'git', 'clone', '--quiet', '--depth=1', '--branch', pins['try_omarchy_tag'],
            'https://github.com/omacom/try-omarchy.git', str(checkout)]
        subprocess.run(command, check=True, capture_output=True)
        subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', pins['try_omarchy_commit']], check=True)
        subprocess.run(['git', '-C', str(checkout), 'apply', '--index', str(root / 'runtime/try-omarchy-v1.3.0.diff')], check=True)
        yield checkout


def tar_content_digest(path):
    with tarfile.open(path) as archive:
        entries = sorted((m.name, m.type.decode(), m.mode, m.linkname,
                          digest(archive.extractfile(m).read()) if m.isfile() else '') for m in archive)
    return digest(json.dumps(entries).encode())


def archive_matches(item, path):
    # Gitiles generates archives on request, so their bytes change while their contents don't.
    if 'content_sha256' in item:
        return tar_content_digest(path) == item['content_sha256']
    return digest(path.read_bytes()) == item['sha256']


def supplemental_archive(item, root=ROOT):
    path = root / 'build/license-inputs' / item['archive']
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix + '.partial')
        try:
            with urllib.request.urlopen(item['url'], timeout=60) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output)
            require(archive_matches(item, partial), f"{item['archive']}: downloaded checksum differs")
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    require(archive_matches(item, path), f"{item['archive']}: checksum differs")
    return path


def verify_git_archive(item, path, directory):
    repository = directory / 'git' / (path.name.removesuffix('.tar.gz') + '.git')
    env = dict(os.environ, GIT_NO_REPLACE_OBJECTS='1')
    command = ['git', '--git-dir=' + str(repository)]
    actual = subprocess.check_output(command + ['rev-parse', item['commit'] + '^{commit}'], env=env, text=True).strip()
    require(actual == item['commit'], 'git source commit differs')
    subprocess.run(command + ['fsck', '--full', '--no-reflogs'], env=env, check=True, capture_output=True)
    with tempfile.TemporaryFile() as output:
        subprocess.run(command + ['archive', '--format=tar', '--prefix=' + path.name.removesuffix('.tar.gz') + '/', item['commit']],
                       env=env, stdout=output, check=True)
        output.seek(0)
        with tarfile.open(fileobj=output) as expected, tarfile.open(path) as archive:
            def entries(source):
                return {m.name: (m.type, m.mode, m.linkname, digest(source.extractfile(m).read()) if m.isfile() else '')
                        for m in source}
            require(entries(expected) == entries(archive), f"{path.name}: archive differs from verified git objects")


def source_notices(archive, subdir='', strip_components=1):
    parts = []
    for member in archive:
        name = '/'.join(member.name.split('/')[strip_components:])
        if not member.isfile() or not name.startswith(subdir) or not name.endswith(
                ('.c', '.h', '.cpp', '.cc', '.m', '.mm', '.py', '.S', '.inc', '.patch')):
            continue
        source = archive.extractfile(member).read().decode(errors='replace')
        pattern = r'\s*((?:(?://[^\n]*\n)|(?:/\*[\s\S]*?\*/)|\s)+)'
        if name.endswith('.py'):
            pattern = r'\s*((?:(?:\#[^\n]*\n)|\s)+)'
        match = re.match(pattern, source)
        if match and re.search(r'copyright|SPDX-License-Identifier|permission|redistribution', match[0], re.I):
            parts.append('==> ' + name + ' <==\n' + match[0].strip() + '\n')
    return '\n'.join(parts).encode()


def header_notices(archive, members):
    parts = []
    for name in members:
        source = archive.extractfile(name).read()
        comments = re.findall(rb'/\*[\s\S]*?\*/|(?://[^\n]*\n)+', source)
        comments = [c for c in comments if re.search(rb'copyright|SPDX-License-Identifier', c, re.I)]
        if comments:
            parts.append(b'==> ' + name.encode() + b' <==\n' + b'\n'.join(comments) + b'\n')
    return b'\n'.join(parts)


def validate_manifest(manifest, root=ROOT, identity='-'):
    require(manifest['schema_version'] == 1, 'unsupported manifest schema')
    ids = set()
    for component in manifest['components']:
        require(component['id'] not in ids, f"duplicate component: {component['id']}")
        ids.add(component['id'])
        for field in ('name', 'license', 'license_files', 'bundle_files'):
            require(component.get(field), f"{component['id']}: missing {field}")
        require(component_version(component, root), f"{component['id']}: missing version")
        for name in component['bundle_files']:
            safe_path(name)
        for name, target in component.get('bundle_symlinks', {}).items():
            safe_path(name)
            require(not PurePosixPath(target).is_absolute(), f'absolute bundle symlink: {name}')
        for name in component['license_files']:
            require(name in manifest['license_texts'], f"{component['id']}: missing license text: {name}")
        for key in component['inputs']:
            require(key in manifest['inputs'], f"{component['id']}: missing input {key}")
        for embedded in component.get('embedded_components', []):
            require(embedded['notice_input'] in component['inputs'], f"{embedded['name']}: missing notice input")
            require(set(embedded['license_files']) <= set(component['license_files']),
                    f"{embedded['name']}: missing embedded license files")
        source = component.get('source', {})
        if 'input' in source:
            require(source['input'] in component['inputs'] and
                    manifest['inputs'][source['input']]['commit'] == source['commit'],
                    f"{component['id']}: source input commit differs")
    for name, record in manifest['license_texts'].items():
        safe_path(name)
        path = root / 'licenses/texts' / name
        require(path.is_file() and path.stat().st_size, f'missing license text: {name}')
        require(digest(path.read_bytes()) == record['sha256'], f'license text changed: {name}')
    components = {c['id']: c for c in manifest['components']}
    for key, item in manifest['inputs'].items():
        if 'component' in item:
            component = components.get(item['component'])
            require(component is not None and key in component['inputs'],
                    f'{key}: missing component entry')
    contact = manifest['offer_contact'].strip()
    if identity != '-':
        # The marked sentinel is defined only in manifest.json.
        require(contact and not contact.endswith('_UNSET'),
                'set offer_contact in licenses/manifest.json before Developer ID signing')
        require(release_repository(root), 'set repository in scripts/release-config.json before Developer ID signing')
        require(not manifest.get('release_blockers'),
                'unresolved license provenance: ' + '; '.join(manifest['release_blockers']))
        require(all(not c.get('license_status', '').startswith('incomplete') for c in manifest['components']),
                'unresolved license provenance: a component still has incomplete license evidence')


def validate_pins(manifest, root=ROOT, deps=None):
    with patched_checkout(root) as checkout:
        validate_checkout_pins(manifest, checkout, root, deps)


def validate_checkout_pins(manifest, checkout, root=ROOT, deps=None):
    builder = (checkout / 'macos/build-qemu-gpu-runtime.sh').read_text()
    bottle_source = (checkout / 'macos/pinned-runtime-bottles.sh').read_text()
    shared_pins = shell_assignments((root / 'runtime/source-pins.sh').read_text())
    variables = shell_assignments(builder)
    rows = bottle_source.split('pinned_core_bottle_manifest()')[1].split('EOF')[1].strip().splitlines()
    bottles = {row.split('\t')[0]: row.split('\t') for row in rows}
    seen = set()
    for key, item in manifest['inputs'].items():
        if 'sha256' in item or 'content_sha256' in item:
            require(re.fullmatch('[a-f0-9]{64}', item.get('sha256') or item['content_sha256']), f'{key}: invalid sha256')
        else:
            require(re.fullmatch('[a-f0-9]{40}', item.get('commit', '')), f'{key}: invalid source commit')
        if item['pin_file'] == 'supplemental':
            continue
        if item['pin_file'] == 'build-qemu-gpu-runtime.sh':
            prefix = item['pin']
            if key in ('qemu', 'keycodemap'):
                require(variables[prefix + '_commit'] == shared_pins[prefix + '_commit'] == item['commit'],
                        f'{key}: source commit differs from shared pin')
                require(prefix + '_sha256' not in variables, f'{key}: obsolete archive hash pin')
            else:
                require(variables[prefix + '_sha256'] == item['sha256'], f'{key}: checksum differs from runtime pin')
            require(variables[prefix + '_archive_name'] == item['archive'], f'{key}: archive version differs from pin')
            require(variables[prefix + '_url'] == item.get('upstream_url', item['url']), f'{key}: URL differs from pin')
            if 'commit' in item:
                require(variables[prefix + '_commit'] == item['commit'], f'{key}: source commit differs from pin')
            seen.add(prefix + '_archive_name')
        else:
            formula, version, archive, _, checksum = bottles[item['pin']]
            require((version, checksum) == (item['version'], item['sha256']), f'{key}: bottle pin differs')
            require(item['url'] == f'https://ghcr.io/v2/homebrew/core/{formula}/blobs/sha256:{checksum}',
                    f'{key}: bottle URL differs')
            bottle_vars = shell_assignments(bottle_source)
            require(bottle_vars[archive[1:]] == item['archive'], f'{key}: bottle archive differs')
    require(seen == {key for key in variables if key.endswith('_archive_name')},
            'a runtime build input is missing from the inventory')
    require({item['pin'] for item in manifest['inputs'].values() if item['pin_file'] == 'pinned-runtime-bottles.sh'} == set(bottles),
            'a pinned bottle is missing from the inventory')
    app_script = (root / 'scripts/build-app.sh').read_text()
    require('source "$root/runtime/source-pins.sh"' in app_script, 'build-app does not load shared pins')
    require('pinned_git_source_archive https://github.com/qemu/qemu.git "$qemu_commit"' in app_script,
            'build-app does not verify QEMU by commit')
    components = {c['id']: c for c in manifest['components']}
    for key, item in manifest['inputs'].items():
        if item['pin_file'] == 'pinned-runtime-bottles.sh':
            component = components[item['component']]
            require(component['version'].split(' ')[0] == item['version'].split('_')[0],
                    f'{key}: component version differs from pin')
    require(components['angle']['version'].startswith(variables['angle_version'] + ' '), 'ANGLE version differs')
    require(components['keycodemapdb']['version'] == variables['keycodemap_commit'], 'keycodemapdb version differs')
    require(components['libfdt']['version'].endswith('+' + variables['dtc_commit']), 'libfdt commit differs')
    for component in manifest['components']:
        source = component.get('source', {})
        if 'path' in source:
            require(digest((root / source['path']).read_bytes()) == source['sha256'],
                    f"{component['id']}: local patch changed")
    sparkle = json.loads((root / 'macos/Package.resolved').read_text())['pins']
    sparkle = next(p for p in sparkle if p['identity'] == 'sparkle')['state']
    require(sparkle['version'] == components['sparkle']['version'] and
            sparkle['revision'] == components['sparkle']['source']['commit'], 'Sparkle package pin differs')
    expected_checkout = checkout
    require(shared_pins['try_omarchy_commit'] == components['try-omarchy']['source']['commit'], 'Try Omarchy shared pin differs')
    if deps and (deps / 'try-omarchy').is_dir():
        checkout = deps / 'try-omarchy'
        for name, expected in [('build-qemu-gpu-runtime.sh', builder), ('pinned-runtime-bottles.sh', bottle_source),
                               ('prepare-qemu-gpu-runtime.sh', (expected_checkout / 'macos/prepare-qemu-gpu-runtime.sh').read_text()),
                               ('pinned-git-source.sh', (expected_checkout / 'macos/pinned-git-source.sh').read_text())]:
            require((checkout / 'macos' / name).read_text() == expected, f'actual runtime script differs: {name}')
        source = components['try-omarchy']['source']
        actual = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
        require(actual == source['commit'], 'Try Omarchy commit differs')
        require(digest(subprocess.check_output(['git', '-C', str(checkout), 'archive', 'HEAD'])) == source['sha256'],
                'Try Omarchy source archive differs')
        for variable, relative in re.findall(r'^(\w+_patch)="\$native_dir/(patches/[^"\n]+)"$', builder, re.M):
            require(digest((checkout / 'macos' / relative).read_bytes()) == variables[variable + '_sha256'],
                    f'runtime patch differs: {relative}')
        # Do not build or modify the shared dependency checkout.
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            with (temp / 'source.tar').open('wb') as output:
                subprocess.run(['git', '-C', str(checkout), 'archive', 'HEAD', 'macos/Sources/OmarchyVMHelper'],
                               stdout=output, check=True)
            with tarfile.open(temp / 'source.tar') as archive:
                for member in archive:
                    if member.isfile():
                        target = temp / member.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.extractfile(member).read())
            diff = (root / 'runtime/try-omarchy-v1.3.0.diff').read_text()
            section = diff.split('diff --git a/macos/Sources/OmarchyVMHelper/main.swift ', 1)[1].split('\ndiff --git ', 1)[0]
            patch = '--- main.swift\n+++ main.swift\n' + section[section.index('@@ '):]
            target = temp / 'macos/Sources/OmarchyVMHelper/main.swift'
            subprocess.run(['patch', '--batch', str(target)], input=patch, text=True, capture_output=True, check=True)
            for path in (temp / 'macos/Sources/OmarchyVMHelper').rglob('*'):
                if path.is_file():
                    require(path.read_bytes() == (checkout / path.relative_to(temp)).read_bytes(),
                            'Try Omarchy helper differs from pinned source and local patch')
            expected = {p.relative_to(temp).as_posix() for p in (temp / 'macos/Sources/OmarchyVMHelper').rglob('*') if p.is_file()}
            actual = {p.relative_to(checkout).as_posix() for p in (checkout / 'macos/Sources/OmarchyVMHelper').rglob('*') if p.is_file()}
            require(actual == expected, 'uncovered Try Omarchy helper source file')


def validate_archives(manifest, directory, root=ROOT):
    archives = {}
    for key, item in manifest['inputs'].items():
        path = supplemental_archive(item, root) if item['pin_file'] == 'supplemental' else directory / item['archive']
        require(path.is_file(), f'{key}: archive missing')
        if 'sha256' in item or 'content_sha256' in item:
            require(archive_matches(item, path), f'{key}: archive checksum differs')
        else:
            verify_git_archive(item, path, directory)
        archives[key] = path
    angle = next(c for c in manifest['components'] if c['id'] == 'angle')
    with tarfile.open(archives['angle-source']) as archive:
        prefix = 'angle-' + angle['source']['commit'] + '/'
        deps = archive.extractfile(prefix + 'DEPS').read().decode()
        for key in angle['inputs']:
            item = manifest['inputs'][key]
            if key not in ('angle-source', 'angle-chromium-license') and 'commit' in item:
                require(item['commit'] in deps, f'{key}: revision differs from ANGLE DEPS')
        base = archive.extractfile(prefix + 'src/common/base/README.chromium').read().decode()
        require(manifest['inputs']['angle-chromium-license']['commit'] in base,
                'Chromium base notice revision differs')
    library = directory.parent / 'try-omarchy/macos/.build/qemu-gpu-runtime/lib/libGLESv2.dylib'
    if library.exists():
        require(angle['source']['evidence'].encode() in library.read_bytes(), 'ANGLE binary version differs')
    for key in manifest['inputs']:
        records = [(name, value) for name, value in manifest['license_texts'].items() if value.get('input') == key]
        evidence = [c['version_evidence'] for c in manifest['components'] if c.get('version_evidence', {}).get('input') == key]
        if not records and not evidence:
            continue
        if records and all(r['mode'] == 'raw' for _, r in records):
            for name, record in records:
                require(digest(archives[key].read_bytes()) == record['sha256'],
                        f'license text differs from pinned input: {name}')
            continue
        with tarfile.open(archives[key]) as archive:
            for name, record in records:
                if record['mode'] == 'source-notices':
                    data = source_notices(archive, record['subdir'], record.get('strip_components', 1))
                elif record['mode'] == 'header-notices':
                    data = header_notices(archive, record['members'])
                else:
                    data = archive.extractfile(record['member']).read()
                    if record['mode'] == 'line-comment':
                        data = data.split(b'#ifndef', 1)[0]
                    elif record['mode'] == 'comment':
                        data = data[:data.index(b'*/') + 2] + b'\n'
                require(digest(data) == record['sha256'], f'license text differs from pinned input: {name}')
            for record in evidence:
                require(record['contains'] in archive.extractfile(record['member']).read().decode(),
                        f"version differs from pinned input: {record['member']}")
            for component in manifest['components']:
                record = component.get('version_evidence', {})
                if record.get('input') != key:
                    continue
                data = archive.extractfile(record['member']).read().decode()
                if component['id'] == 'qemu':
                    actual = data.strip()
                elif component['id'] in ('virgl', 'slirp'):
                    actual = re.search(r"\bversion\s*:\s*'([^']+)'", data)[1]
                elif component['id'] == 'libfdt':
                    actual = '.'.join(re.search(r'^' + field + r' = (\d+)$', data, re.M)[1]
                                      for field in ('VERSION', 'PATCHLEVEL', 'SUBLEVEL'))
                else:
                    actual = re.search(r'EDK2_STABLE = (\S+)', data)[1]
                require(component['version'].startswith(actual), f"{component['id']}: inventory version differs from archive")
    for name, record in manifest['license_texts'].items():
        if 'local' in record:
            require(digest((root / record['local']).read_bytes()) == record['sha256'], f'local attribution changed: {name}')


def iso_files(image):
    # Read the Joliet tree so names match the disc's long UTF-16 filenames.
    for offset in range(16 * 2048, len(image), 2048):
        require(image[offset + 1:offset + 6] == b'CD001', 'invalid ISO volume descriptor')
        if image[offset] == 255:
            break
        if image[offset] != 2:
            continue
        record = image[offset + 156:offset + 190]
        cursor = int.from_bytes(record[2:6], 'little') * 2048
        end = cursor + int.from_bytes(record[10:14], 'little')
        files = {}
        while cursor < end:
            size = image[cursor]
            if not size:
                cursor = (cursor // 2048 + 1) * 2048
                continue
            record = image[cursor:cursor + size]
            raw = record[33:33 + record[32]]
            if raw not in (b'\x00', b'\x01'):
                require(not record[25] & 2, 'uncovered directory on Guest Tools disc')
                name = raw.decode('utf-16-be').removesuffix(';1')
                require(name not in files, f'duplicate ISO member: {name}')
                start = int.from_bytes(record[2:6], 'little') * 2048
                length = int.from_bytes(record[10:14], 'little')
                files[name] = image[start:start + length]
            cursor += size
        return files
    raise LicenseError('Guest Tools disc has no Joliet tree')


def deb_files(data):
    require(data.startswith(b'!<arch>\n'), 'invalid Guest Tools Debian package')
    cursor = 8
    result = {}
    while cursor < len(data):
        header = data[cursor:cursor + 60]
        name = header[:16].decode().strip().removesuffix('/')
        size = int(header[48:58])
        require(header[58:60] == b'`\n' and name not in result, 'invalid Debian archive member')
        result[name] = data[cursor + 60:cursor + 60 + size]
        cursor += 60 + size + size % 2
    require(set(result) == {'debian-binary', 'control.tar.gz', 'data.tar.gz'}, 'uncovered Debian archive member')
    require(result['debian-binary'] == b'2.0\n', 'unexpected Debian format')
    files = {}
    for section in ('control', 'data'):
        with tarfile.open(fileobj=io.BytesIO(result[section + '.tar.gz'])) as archive:
            for member in archive:
                name = member.name.removeprefix('./')
                safe_path(name)
                require(member.isfile() or member.isdir(), f'unsupported guest package entry: {name}')
                if member.isfile():
                    key = 'deb:' + section + '/' + name
                    require(key not in files, f'duplicate guest package entry: {name}')
                    files[key] = archive.extractfile(member).read()
    return files


def validate_guest(manifest, iso, root=ROOT):
    expected = manifest['guest_files']
    source_paths = {record['source'] for record in expected.values() if 'source' in record}
    actual_paths = {p.relative_to(root).as_posix() for folder in ('guest/files', 'guest/debian', 'guest/iso')
                    for p in (root / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    require(source_paths == actual_paths, 'uncovered or removed Guest Tools source file')
    disc = iso_files(iso.read_bytes())
    version = component_version(next(c for c in manifest['components'] if c['id'] == 'guest'), root)
    package = f'linuxvm-guest_{version}_all.deb'
    require(set(disc) == {package, 'install.sh', 'README.txt'}, 'uncovered Guest Tools disc file')
    files = deb_files(disc[package])
    md5sums = files.pop('deb:control/md5sums')
    expected_md5 = ''.join(f"{hashlib.md5(data, usedforsecurity=False).hexdigest()}  {name.removeprefix('deb:data/')}\n"
                         for name, data in sorted(files.items()) if name.startswith('deb:data/')).encode()
    require(sorted(md5sums.splitlines()) == sorted(expected_md5.splitlines()), 'Guest Tools md5sums differ')
    files.update({'iso:/' + name: disc[name] for name in ('install.sh', 'README.txt')})
    require(set(files) == set(expected), 'uncovered or removed file inside Guest Tools package')
    require(files['deb:data/usr/lib/linuxvm/version.py'] == f'VERSION = {version!r}\n'.encode(),
            'Guest Tools disc version differs; rebuild the disc')


def release_repository(root=ROOT):
    try:
        repository = json.loads((root / 'scripts/release-config.json').read_text()).get('repository', '')
    except (OSError, ValueError, AttributeError):
        return None
    return repository if isinstance(repository, str) and re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', repository) else None


def notices(manifest, root=ROOT):
    revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    version = component_version(next(c for c in manifest['components'] if c['id'] == 'linux-vm'), root)
    repository = release_repository(root) or '<repository not configured>'
    release_page = f'https://github.com/{repository}/releases/tag/v{version}'
    lines = ['Linux VM — third-party notices and provenance', '', 'Build source revision: ' + revision,
             'Local modifications may be present; see the accompanying manifest.json.', '',
             'SOURCE CODE', '',
             'The complete corresponding source code for the GPL and LGPL software in',
             'this copy is published with this version’s release, next to the app:',
             f'  {release_page}',
             f'  linux-vm-{version}-source.tar.gz',
             'It includes QEMU, the LGPL libraries, all local and upstream patches,',
             'interface definitions, and the scripts used to control compilation and',
             'installation. Linux VM’s own source is in the repository, and this build',
             'came from the revision above.',
             'Questions and source requests: ' + manifest['offer_contact'], '',
             'See LGPL-REPLACEMENT.txt for replacing LGPL libraries in a personal copy.',
             'Linux VM’s own code and artwork are available under the MIT License; see Linux-VM.txt.', '']
    if release_blockers(manifest):
        lines += ['DEVELOPMENT BUILD — unresolved provenance (public release is blocked):']
        lines += release_blockers(manifest) + ['']
    for component in manifest['components']:
        lines += [component['name'], 'Version: ' + component_version(component, root), 'License: ' + component['license'],
                  'License files: ' + ', '.join(component['license_files'])]
        for key in component['inputs']:
            item = manifest['inputs'][key]
            lines += ['Input: ' + item['url']]
            if 'sha256' in item:
                lines += ['SHA-256: ' + item['sha256']]
            if 'content_sha256' in item:
                lines += ['Content SHA-256: ' + item['content_sha256']]
            if 'commit' in item:
                lines += ['Commit: ' + item['commit'], 'Archive format: ' + item['format']]
        if 'source' in component:
            lines += ['Source: ' + json.dumps(component['source'], ensure_ascii=False, sort_keys=True)]
        for embedded in component.get('embedded_components', []):
            lines += [f"Embedded notice: {embedded['name']}; {embedded['license']}; revision {embedded['revision']}",
                      '  Evidence: ' + embedded['graph_evidence']]
        lines += ['Bundle files:'] + ['  ' + name for name in component['bundle_files']]
        if component.get('notes'):
            lines += [component['notes']]
        if component.get('license_status'):
            lines += ['License evidence: ' + component['license_status']]
        if component['id'] in ('guest', 'try-omarchy'):
            lines += ['Guest Tools members:'] + ['  ' + name for name in manifest['guest_files']]
        lines += ['']
    lines += ['All pinned inputs (including tools that do not ship):',
              'See manifest.json for archive names, checksums, versions and scopes.']
    return '\n'.join(lines) + '\n'


def write_notices(manifest, bundle, root=ROOT):
    destination = bundle / 'Contents/Resources/Licenses'
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for name in manifest['license_texts']:
        shutil.copyfile(root / 'licenses/texts' / name, destination / name)
    shutil.copyfile(root / 'licenses/LGPL-REPLACEMENT.txt', destination / 'LGPL-REPLACEMENT.txt')
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    (destination / 'NOTICES.txt').write_text(notices(manifest, root))


def validate_bundle(manifest, bundle, root=ROOT):
    covered = {name for component in manifest['components'] for name in component['bundle_files']}
    links = {name: target for component in manifest['components']
             for name, target in component.get('bundle_symlinks', {}).items()}
    covered |= set(links)
    required = {name for component in manifest['components'] for name in component['bundle_files']
                if name not in component.get('optional_files', [])}
    required |= set(links)
    license_dir = 'Contents/Resources/Licenses/'
    generated = {license_dir + name for name in manifest['license_texts']}
    generated |= {license_dir + name for name in ('manifest.json', 'NOTICES.txt', 'LGPL-REPLACEMENT.txt')}
    # Only the outer app's exact signature metadata file is added by codesign.
    signature = 'Contents/_CodeSignature/CodeResources'
    found = set()
    for path in sorted(bundle.rglob('*')):
        name = path.relative_to(bundle).as_posix()
        if path.is_symlink():
            require(name in links, f'unreviewed bundle symlink: {name}')
            require(str(path.readlink()) == links[name], f'bundle symlink target differs: {name}')
            require(path.resolve().is_relative_to(bundle.resolve()) and path.exists(),
                    f'bundle symlink escapes the bundle or is broken: {name}')
            found.add(name)
            continue
        if path.is_dir():
            require(any(entry.startswith(name + '/') for entry in covered | generated | {signature}),
                    f'uncovered bundle directory: {name}')
            continue
        require(path.is_file(), f'unsupported bundle entry: {name}')
        require(name in covered | generated | {signature}, f'uncovered bundle file: {name}')
        if name == signature:
            require(not path.stat().st_mode & 0o111 and path.read_bytes().startswith(b'<?xml'),
                    'unexpected executable or non-XML signature metadata')
        found.add(name)
    require(required <= found, 'missing covered bundle files: ' + ', '.join(sorted(required - found)))
    require(generated <= found, 'missing bundled notices: ' + ', '.join(sorted(generated - found)))
    destination = bundle / license_dir
    for name, record in manifest['license_texts'].items():
        require(digest((destination / name).read_bytes()) == record['sha256'], f'bundled license differs: {name}')
    require(json.loads((destination / 'manifest.json').read_text()) == manifest, 'bundled manifest differs')
    require((destination / 'NOTICES.txt').read_text() == notices(manifest, root), 'bundled notices differ')
    require((destination / 'LGPL-REPLACEMENT.txt').read_bytes() == (root / 'licenses/LGPL-REPLACEMENT.txt').read_bytes(),
            'bundled LGPL instructions differ')
    iso = bundle / 'Contents/Resources/guest-tools.iso'
    if iso.exists():
        validate_guest(manifest, iso, root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--write', action='store_true', help='copy texts and generate notices before validation')
    parser.add_argument('--inputs', action='store_true', help='verify the actual dependency scripts and archives')
    parser.add_argument('--identity', default='-')
    args = parser.parse_args()
    try:
        manifest = load(args.manifest)
        validate_manifest(manifest, identity=args.identity)
        if args.inputs:
            validate_pins(manifest, deps=ROOT / '.deps')
            validate_archives(manifest, ROOT / '.deps/source-archives')
        if args.write:
            require(args.bundle is not None, '--write requires --bundle')
            write_notices(manifest, args.bundle)
        if args.bundle:
            validate_bundle(manifest, args.bundle)
    except (LicenseError, OSError, KeyError, subprocess.CalledProcessError, ValueError, tarfile.TarError) as error:
        print(f'license-notices: {error}', file=sys.stderr)
        return 1
    print(f"license-notices: inventory files and coverage OK ({len(release_blockers(manifest))} unresolved release blockers)")
    for blocker in release_blockers(manifest):
        print('license-notices: release blocker: ' + blocker)
    return 0


if __name__ == '__main__':
    sys.exit(main())
