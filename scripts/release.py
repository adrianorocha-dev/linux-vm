#!/usr/bin/env python3
"""Build, verify and retain a release before asking to publish it."""
import argparse
import base64
import copy
from datetime import datetime, timezone
from email.utils import format_datetime
import hashlib
import html
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPARKLE = 'http://www.andymatuschak.org/xml-namespaces/sparkle'
ET.register_namespace('sparkle', SPARKLE)
SPARKLE_VERSION = '2.10.0'
SPARKLE_SHA256 = 'c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c'
SPARKLE_URL = f'https://github.com/sparkle-project/Sparkle/releases/download/{SPARKLE_VERSION}/Sparkle-{SPARKLE_VERSION}.tar.xz'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(*args, cwd=ROOT, env=None, check=True):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise ValueError(f'command failed: {" ".join(str(a) for a in args)}\n{result.stdout}{result.stderr}')
    return result


def git(root, *args):
    return run('git', *args, cwd=root).stdout.strip()


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def valid_base64(value, length):
    try:
        return isinstance(value, str) and len(base64.b64decode(value, validate=True)) == length
    except ValueError:
        return False


def load_config(path, root, env):
    config = json.loads(path.read_text())
    require(isinstance(config, dict), 'release config must be a JSON object')
    missing = []
    repository = config.get('repository', '')
    if not isinstance(repository, str) or not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_-][A-Za-z0-9_.-]*', repository):
        missing.append('repository (public GitHub owner/name)')
    if not valid_base64(config.get('public_key'), 32):
        missing.append('public_key (Sparkle EdDSA public key)')
    directory = env.get('LINUXVM_RELEASE_SOURCE_DIR') or config.get('source_archive_directory', '')
    if not isinstance(directory, str) or not directory or '<' in directory or not Path(directory).expanduser().is_absolute():
        missing.append('source_archive_directory (absolute path, or LINUXVM_RELEASE_SOURCE_DIR)')
    require(not missing, f'incomplete release config {path}: ' + '; '.join(missing))
    directory = Path(directory).expanduser().resolve()
    require(not directory.is_relative_to(root.resolve()), 'source_archive_directory must be outside the repository')
    config['source_archive_directory'] = directory
    config['feed_url'] = f'https://github.com/{repository}/releases/latest/download/appcast.xml'
    return config


def read_info(path):
    with path.open('rb') as source:
        return plistlib.load(source)


def validate_version(version, info):
    require(re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version),
            'VERSION must be MAJOR.MINOR.PATCH without leading zeroes')
    require(info.get('CFBundleShortVersionString') == version,
            f'VERSION {version} does not match CFBundleShortVersionString')
    build = info.get('CFBundleVersion', '')
    require(isinstance(build, str) and re.fullmatch(r'[1-9][0-9]*', build),
            'CFBundleVersion must be a positive integer build number')
    require(re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,2}', info.get('LSMinimumSystemVersion', '')),
            'LSMinimumSystemVersion is missing or invalid')
    return int(build)


def check_checkout(root, version):
    require(git(root, 'branch', '--show-current') == 'main', 'release requires branch main')
    require(not git(root, 'status', '--porcelain', '--untracked-files=all'), 'release requires a clean checkout')
    run('git', 'fetch', 'origin', 'main:refs/remotes/origin/main', cwd=root)
    revision = git(root, 'rev-parse', 'HEAD')
    require(revision == git(root, 'rev-parse', 'refs/remotes/origin/main'), 'HEAD must equal origin/main')
    tag = f'v{version}'
    require(not git(root, 'tag', '--list', tag), f'tag {tag} already exists locally')
    require(not git(root, 'ls-remote', '--tags', 'origin', f'refs/tags/{tag}'), f'tag {tag} already exists on origin')
    return revision


def parse_feed(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError(f'invalid published appcast XML: {error}') from error
    require(root.tag == 'rss' and len(root.findall('channel')) == 1, 'appcast must have one RSS channel')
    return root.find('channel').findall('item')


def item_build(item):
    enclosure = item.find('enclosure')
    value = item.findtext(f'{{{SPARKLE}}}version')
    if value is None and enclosure is not None:
        value = enclosure.get(f'{{{SPARKLE}}}version')
    require(value is not None and re.fullmatch(r'[1-9][0-9]*', value), 'published feed has a missing or noninteger build number')
    return int(value)


def check_build(build, previous):
    require(all(build > item_build(item) for item in previous),
            f'CFBundleVersion {build} must be greater than every published build number')


def download(url, target):
    with urllib.request.urlopen(url, timeout=60) as response, target.open('wb') as output:
        shutil.copyfileobj(response, output)


def published_feed(config, directory):
    repository = config['repository']
    metadata = json.loads(run('gh', 'api', f'repos/{repository}').stdout)
    require(metadata.get('private') is False, f'{repository} must be an existing public repository')
    latest = run('gh', 'api', f'repos/{repository}/releases/latest', check=False)
    if latest.returncode:
        require('HTTP 404' in latest.stderr, f'cannot read latest release: {latest.stderr}')
        releases = json.loads(run('gh', 'api', '--paginate', '--slurp', f'repos/{repository}/releases').stdout)
        require(not any(not release.get('draft', False) for page in releases for release in page),
                'published releases exist but there is no latest stable release; inspect the feed manually')
        return None
    release = json.loads(latest.stdout)
    require(any(asset['name'] == 'appcast.xml' for asset in release['assets']),
            'latest release is missing appcast.xml; refusing to discard update history')
    target = directory / 'published-appcast.xml'
    download(config['feed_url'], target)
    data = target.read_bytes()
    parse_feed(data)
    return data


def markdown_html(markdown):
    """Render the documented notes subset; raw HTML is always escaped."""
    def inline(value):
        tokens = []
        def protect(match):
            tokens.append('<code>' + html.escape(match[1]) + '</code>')
            return f'\x00{len(tokens) - 1}\x00'
        value = re.sub(r'`([^`]+)`', protect, value)
        value = html.escape(value)
        def link(match):
            url = html.unescape(match[2])
            if not re.match(r'https?://[^\s]+$', url):
                return match[0]
            return f'<a href="{html.escape(url, quote=True)}">{match[1]}</a>'
        value = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, value)
        value = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', value)
        value = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', value)
        return re.sub(r'\x00([0-9]+)\x00', lambda m: tokens[int(m[1])], value)

    output, paragraph = [], []
    listing = False
    def flush():
        if paragraph:
            output.append('<p>' + inline(' '.join(paragraph)) + '</p>')
            paragraph.clear()
    for line in markdown.splitlines() + ['']:
        heading = re.fullmatch(r'(#{1,6})\s+(.+)', line)
        bullet = re.fullmatch(r'[-*] (.+)', line)
        if listing and not bullet:
            output.append('</ul>')
            listing = False
        if not line.strip():
            flush()
        elif heading:
            flush()
            level = len(heading[1])
            output.append(f'<h{level}>{inline(heading[2])}</h{level}>')
        elif bullet:
            flush()
            if not listing:
                output.append('<ul>')
                listing = True
            output.append('<li>' + inline(bullet[1]) + '</li>')
        else:
            paragraph.append(line.strip())
    return '\n'.join(output)


def dmg_name(version):
    return f'LinuxVM-{version}.dmg'


def appcast(version, info, config, signature, length, notes, previous, now=None):
    require(valid_base64(signature, 64), 'sign_update did not return a valid EdDSA signature')
    require(length > 0, 'DMG is empty')
    check_build(int(info['CFBundleVersion']), previous)
    root = ET.Element('rss', {'version': '2.0'})
    channel = ET.SubElement(root, 'channel')
    ET.SubElement(channel, 'title').text = 'Linux VM updates'
    ET.SubElement(channel, 'link').text = config['feed_url']
    ET.SubElement(channel, 'description').text = 'Linux VM releases'
    item = ET.SubElement(channel, 'item')
    ET.SubElement(item, 'title').text = f'Linux VM {version}'
    for name, value in [('version', info['CFBundleVersion']), ('shortVersionString', version),
                        ('minimumSystemVersion', info['LSMinimumSystemVersion'])]:
        ET.SubElement(item, f'{{{SPARKLE}}}{name}').text = value
    ET.SubElement(item, 'pubDate').text = format_datetime(now or datetime.now(timezone.utc), usegmt=True)
    ET.SubElement(item, 'description').text = markdown_html(notes)
    ET.SubElement(item, 'enclosure', {
        'url': f'https://github.com/{config["repository"]}/releases/download/v{version}/{dmg_name(version)}',
        f'{{{SPARKLE}}}edSignature': signature,
        'length': str(length), 'type': 'application/octet-stream',
    })
    channel.extend(copy.deepcopy(previous))
    ET.indent(root)
    data = ET.tostring(root, encoding='utf-8', xml_declaration=True) + b'\n'
    require(len(parse_feed(data)) == len(previous) + 1, 'generated appcast failed validation')
    return data


def sparkle_tools(root):
    tools = root / '.deps' / f'sparkle-{SPARKLE_VERSION}' / 'bin'
    if all(os.access(tools / name, os.X_OK) for name in ('sign_update', 'generate_keys')):
        return tools
    archive = root / '.deps' / f'Sparkle-{SPARKLE_VERSION}.tar.xz'
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        partial = archive.with_suffix('.partial')
        try:
            download(SPARKLE_URL, partial)
            require(sha(partial) == SPARKLE_SHA256, 'Sparkle archive SHA-256 mismatch')
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    require(sha(archive) == SPARKLE_SHA256, 'Sparkle archive SHA-256 mismatch')
    with tarfile.open(archive) as source:
        for name in ('sign_update', 'generate_keys'):
            members = [m for m in source if m.name.removeprefix('./') == f'bin/{name}']
            require(len(members) == 1 and members[0].isfile(), f'Sparkle archive is missing bin/{name}')
            tools.mkdir(parents=True, exist_ok=True)
            (tools / name).write_bytes(source.extractfile(members[0]).read())
            (tools / name).chmod(0o755)
    return tools


def verify_app(app, info, config):
    built = read_info(app / 'Contents/Info.plist')
    expected = {key: info[key] for key in ('CFBundleShortVersionString', 'CFBundleVersion', 'LSMinimumSystemVersion')}
    expected.update(SUFeedURL=config['feed_url'], SUPublicEDKey=config['public_key'])
    for key, value in expected.items():
        require(built.get(key) == value, f'built app {key} differs: expected {value!r}, got {built.get(key)!r}')


def verify_dmg(dmg, root):
    run('codesign', '--verify', '--strict', dmg, cwd=root)
    run('spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature', '--verbose=2', dmg, cwd=root)
    run('xcrun', 'stapler', 'validate', dmg, cwd=root)


def verify_public(config, version, dmg, feed, directory):
    urls = [(config['feed_url'], feed),
            (f'https://github.com/{config["repository"]}/releases/download/v{version}/{dmg.name}', dmg)]
    for index, (url, expected) in enumerate(urls):
        target = directory / f'.public-check-{index}'
        try:
            for attempt in range(5):
                try:
                    download(url, target)
                    require(sha(target) == sha(expected), f'public bytes differ: {url}')
                    if expected == feed:
                        require(parse_feed(target.read_bytes())[0].findtext(f'{{{SPARKLE}}}shortVersionString') == version,
                                'public feed does not list the new version first')
                    break
                except (OSError, ValueError):
                    if attempt == 4:
                        raise
                    time.sleep(2)
        finally:
            target.unlink(missing_ok=True)


def release(version, dry_run=False, config_path=None, root=ROOT, env=None):
    env = dict(os.environ if env is None else env)
    config = load_config(config_path or root / 'scripts/release-config.json', root, env)
    info = read_info(root / 'macos/Resources/Info.plist')
    build = validate_version(version, info)
    notes_path = root / 'docs/releases' / f'{version}.md'
    require(notes_path.is_file() and notes_path.read_text().strip(), f'release notes are missing or empty: {notes_path}')
    identity = env.get('LINUXVM_SIGN_IDENTITY', '')
    require(identity.startswith('Developer ID Application: ') and identity.removeprefix('Developer ID Application: ').strip(),
            'set LINUXVM_SIGN_IDENTITY to a Developer ID Application identity')
    env.update(LINUXVM_NOTARY_PROFILE=env.get('LINUXVM_NOTARY_PROFILE') or 'linuxvm-notary',
               LINUXVM_UPDATE_FEED=config['feed_url'], LINUXVM_UPDATE_KEY=config['public_key'])
    revision = check_checkout(root, version)
    directory = root / 'build/release' / version
    directory.mkdir(parents=True, exist_ok=True)
    old_feed = published_feed(config, directory)
    previous = parse_feed(old_feed) if old_feed is not None else []
    check_build(build, previous)
    source = config['source_archive_directory'] / f'linux-vm-{version}-{revision[:12]}-source.tar.gz'
    require(not source.exists(), f'retained source already exists; keep it safe and choose another archive directory: {source}')
    tools = sparkle_tools(root)
    public_key = run(tools / 'generate_keys', '-p', cwd=root).stdout.strip()
    require(public_key == config['public_key'], 'keychain EdDSA public key differs from release config; run generate_keys during setup')
    runtime = root / '.deps/try-omarchy/macos/.build/qemu-gpu-runtime/bin/qemu-system-aarch64'
    if not os.access(runtime, os.X_OK):
        print('Building runtime…', flush=True)
        run(root / 'scripts/build-runtime.sh', cwd=root, env=env)
    print('Building and signing app…', flush=True)
    run(root / 'scripts/build-app.sh', cwd=root, env=env)
    app = root / 'build/Linux VM.app'
    verify_app(app, info, config)
    print('Packaging and notarizing DMG…', flush=True)
    run(root / 'scripts/package-dmg.sh', cwd=root, env=env)
    verify_app(app, info, config)
    dmg = directory / dmg_name(version)
    shutil.copyfile(root / 'build' / f'Linux VM {version}.dmg', dmg)
    verify_dmg(dmg, root)
    signature = run(tools / 'sign_update', '-p', dmg, cwd=root).stdout.strip()
    require(valid_base64(signature, 64), 'sign_update did not return a valid EdDSA signature')
    run(tools / 'sign_update', '--verify', dmg, signature, cwd=root)
    feed = directory / 'appcast.xml'
    feed.write_bytes(appcast(version, info, config, signature, dmg.stat().st_size, notes_path.read_text(), previous))
    print('Retaining release source…', flush=True)
    run(sys.executable, root / 'scripts/retain-release-source.py', '--output', source, cwd=root, env=env)
    require(source.is_file(), f'source retention did not produce {source}')
    notes = directory / 'release-notes.md'
    shutil.copyfile(notes_path, notes)
    hashes = {path: sha(path) for path in (dmg, feed, notes, source)}
    summary = (f'Linux VM {version} (build {build})\nCommit: {revision}\nTag: v{version} on origin\n'
               f'Public repository: {config["repository"]}\nFeed: {config["feed_url"]}\n'
               f'DMG: {dmg} ({dmg.stat().st_size} bytes, SHA-256 {hashes[dmg]})\n'
               f'Appcast: {feed} ({len(previous) + 1} items)\nRelease notes: {notes}\n'
               f'Retained source: {source}\nKeep this archive for at least three years after this version’s last distribution.\n')
    (directory / 'summary.txt').write_text(summary)
    print('\n' + summary, flush=True)
    if dry_run:
        print('Dry run complete. Nothing was tagged, pushed or published.')
        return directory
    if input('Push the tag and publish this release? Type publish to continue: ').strip() != 'publish':
        print('Publication cancelled. Artifacts were kept.')
        return directory
    require(check_checkout(root, version) == revision, 'HEAD changed during the release')
    require(published_feed(config, directory) == old_feed, 'published feed changed during the release; rebuild with the current history')
    require(all(sha(path) == value for path, value in hashes.items()), 'release artifacts changed after verification')
    tag = f'v{version}'
    run('git', 'tag', '-a', tag, revision, '-m', f'Linux VM {version}', cwd=root)
    run('git', 'push', 'origin', f'refs/tags/{tag}', cwd=root)
    run('gh', 'release', 'create', tag, '--repo', config['repository'], '--draft',
        '--title', f'Linux VM {version}', '--notes-file', notes, dmg, feed, cwd=root)
    run('gh', 'release', 'edit', tag, '--repo', config['repository'], '--draft=false', '--latest', cwd=root)
    verify_public(config, version, dmg, feed, directory)
    print(f'Published and verified https://github.com/{config["repository"]}/releases/tag/{tag}')
    return directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version', metavar='VERSION')
    parser.add_argument('--dry-run', action='store_true', help='build, sign, notarize and retain source, then stop before publication')
    parser.add_argument('--config', type=Path, help='release config JSON (default: scripts/release-config.json)')
    args = parser.parse_args(argv)
    try:
        release(args.version, args.dry_run, args.config)
    except (OSError, ValueError, KeyError, tarfile.TarError, EOFError, KeyboardInterrupt) as error:
        print(f'release: {error}\nAny prepared artifacts are kept in build/release/{args.version}/. If publication started, inspect the origin tag and public release before retrying.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
