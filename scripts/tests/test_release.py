"""Release gates and publication ordering without signing, network or GitHub."""
import base64
from contextlib import redirect_stdout
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('release', ROOT / 'scripts/release.py')
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
KEY = base64.b64encode(b'k' * 32).decode()
SIGNATURE = base64.b64encode(b's' * 64).decode()
INFO = {'CFBundleShortVersionString': '0.1.0', 'CFBundleVersion': '2', 'LSMinimumSystemVersion': '15.0'}
CONFIG = {'repository': 'fixture-owner/unused-release-fixture', 'public_key': KEY,
          'feed_url': 'https://github.com/fixture-owner/unused-release-fixture/releases/latest/download/appcast.xml'}
EARLIER = f'''<rss xmlns:sparkle="{release.SPARKLE}" version="2.0"><channel><title>Updates</title>
<item><title>Linux VM 0.0.9</title><sparkle:version>1</sparkle:version><sparkle:shortVersionString>0.0.9</sparkle:shortVersionString>
<sparkle:minimumSystemVersion>15.0</sparkle:minimumSystemVersion><pubDate>Mon, 02 Nov 2026 12:00:00 GMT</pubDate>
<description>&lt;p&gt;Earlier notes.&lt;/p&gt;</description><enclosure url="https://example.invalid/LinuxVM-0.0.9.dmg" length="10" sparkle:edSignature="{SIGNATURE}" type="application/octet-stream" /></item>
</channel></rss>'''.encode()


class ReleaseLogicTests(unittest.TestCase):
    def test_version_and_info_checks(self):
        self.assertEqual(release.validate_version('0.1.0', INFO), 2)
        for version in ('1.0', 'v0.1.0', '0.1.0-beta', '../0.1.0', '00.1.0', '0.2.0'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                release.validate_version(version, INFO)
        for build in ('0', '-1', '1.2', '02', '', 2):
            with self.subTest(build=build), self.assertRaisesRegex(ValueError, 'CFBundleVersion'):
                release.validate_version('0.1.0', dict(INFO, CFBundleVersion=build))
        with self.assertRaisesRegex(ValueError, 'LSMinimumSystemVersion'):
            release.validate_version('0.1.0', dict(INFO, LSMinimumSystemVersion=''))

    def test_build_must_exceed_every_item_including_legacy_enclosure_version(self):
        previous = release.parse_feed(EARLIER)
        legacy = ET.fromstring(f'<item xmlns:sparkle="{release.SPARKLE}"><enclosure sparkle:version="9" /></item>')
        release.check_build(10, previous + [legacy])
        for build in (1, 2, 9):
            with self.subTest(build=build), self.assertRaisesRegex(ValueError, 'greater than every'):
                release.check_build(build, previous + [legacy])
        for bad in ('<item/>', '<item><enclosure/></item>', f'<item xmlns:sparkle="{release.SPARKLE}"><sparkle:version>1.2</sparkle:version></item>'):
            with self.assertRaisesRegex(ValueError, 'build number'):
                release.check_build(10, [ET.fromstring(bad)])

    def test_appcast_round_trip_and_history_preservation(self):
        previous = release.parse_feed(EARLIER)
        original = ET.tostring(previous[0])
        data = release.appcast('0.1.0', INFO, CONFIG, SIGNATURE, 123, '# New\n\n- Better & faster', previous,
                               datetime(2026, 11, 3, 12, tzinfo=timezone.utc))
        items = release.parse_feed(data)
        self.assertEqual(len(items), 2)
        item = items[0]
        self.assertEqual(item.findtext(f'{{{release.SPARKLE}}}version'), '2')
        self.assertEqual(item.findtext(f'{{{release.SPARKLE}}}shortVersionString'), '0.1.0')
        self.assertEqual(item.findtext(f'{{{release.SPARKLE}}}minimumSystemVersion'), '15.0')
        self.assertEqual(item.findtext('pubDate'), 'Tue, 03 Nov 2026 12:00:00 GMT')
        self.assertIn('<li>Better &amp; faster</li>', item.findtext('description'))
        enclosure = item.find('enclosure')
        self.assertEqual(enclosure.get('length'), '123')
        self.assertEqual(enclosure.get(f'{{{release.SPARKLE}}}edSignature'), SIGNATURE)
        self.assertEqual(enclosure.get('url'), 'https://github.com/fixture-owner/unused-release-fixture/releases/download/v0.1.0/LinuxVM-0.1.0.dmg')
        self.assertEqual(ET.tostring(previous[0]), original)
        # Indentation may change insignificant whitespace, but every earlier field survives.
        self.assertEqual(items[1].findtext('description'), previous[0].findtext('description'))
        self.assertEqual(items[1].find('enclosure').attrib, previous[0].find('enclosure').attrib)
        self.assertEqual(release.item_build(items[1]), 1)
        self.assertEqual(len(release.parse_feed(release.appcast('0.1.0', INFO, CONFIG, SIGNATURE, 1, 'Notes', []))), 1)
        with self.assertRaisesRegex(ValueError, 'signature'):
            release.appcast('0.1.0', INFO, CONFIG, 'invalid', 1, 'Notes', [])

    def test_malformed_feeds_fail_closed(self):
        for data in (b'not XML', b'<rss/>', b'<rss><channel/><channel/></rss>', b'<html/>'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                release.parse_feed(data)

    def test_markdown_subset_escapes_html_and_unsafe_links(self):
        rendered = release.markdown_html('# Changes\n\nA **bold** and *small* `a < b` change.\nNext line.\n\n- One\n- [Two](https://example.com/?a=1&b=2)\n\n<script>alert(1)</script>\n\n[bad](javascript:alert)')
        self.assertIn('<h1>Changes</h1>', rendered)
        self.assertIn('<p>A <strong>bold</strong> and <em>small</em> <code>a &lt; b</code> change. Next line.</p>', rendered)
        self.assertIn('<ul>\n<li>One</li>', rendered)
        self.assertIn('<a href="https://example.com/?a=1&amp;b=2">Two</a>', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('href="javascript:', rendered)
        self.assertIn('<code>**literal**</code>', release.markdown_html('`**literal**`'))

    def test_asset_name_has_no_spaces(self):
        self.assertEqual(release.dmg_name('12.34.56'), 'LinuxVM-12.34.56.dmg')

    def test_config_placeholders_refuse_before_any_external_work(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            config.write_text(json.dumps({'repository': '<owner>/<repo>', 'public_key': '<public key>',
                                          'source_archive_directory': '<absolute directory>'}))
            with patch.object(release, 'run') as command:
                with self.assertRaisesRegex(ValueError, r'incomplete release config.*repository.*public_key.*source_archive_directory'):
                    release.release('0.1.0', dry_run=True, config_path=config)
            command.assert_not_called()

    def test_complete_config_derives_feed_and_keeps_source_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'repo'
            root.mkdir()
            path = root / 'config.json'
            config = dict(CONFIG, source_archive_directory=str(Path(directory) / 'archives'))
            path.write_text(json.dumps(config))
            loaded = release.load_config(path, root, {})
            self.assertEqual(loaded['feed_url'], CONFIG['feed_url'])
            config['source_archive_directory'] = str(root / 'retained')
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, 'outside the repository'):
                release.load_config(path, root, {})
            override = str(Path(directory) / 'elsewhere')
            self.assertEqual(release.load_config(path, root, {'LINUXVM_RELEASE_SOURCE_DIR': override})['source_archive_directory'], Path(override).resolve())

    def test_checkout_preconditions(self):
        cases = [(['topic'], 'branch main'), (['main', ' M README.md'], 'clean checkout'),
                 (['main', '', 'abc', 'def'], 'equal origin/main'),
                 (['main', '', 'abc', 'abc', 'v0.1.0'], 'exists locally'),
                 (['main', '', 'abc', 'abc', '', 'remote-tag'], 'exists on origin')]
        for values, message in cases:
            with self.subTest(message=message), patch.object(release, 'git', side_effect=values), patch.object(release, 'run'):
                with self.assertRaisesRegex(ValueError, message):
                    release.check_checkout(ROOT, '0.1.0')
        with patch.object(release, 'git', side_effect=['main', '', 'abc', 'abc', '', '']), patch.object(release, 'run') as command:
            self.assertEqual(release.check_checkout(ROOT, '0.1.0'), 'abc')
        self.assertIn('fetch', command.call_args.args)

    def test_built_info_must_match(self):
        with patch.object(release, 'read_info', return_value=dict(INFO, SUFeedURL=CONFIG['feed_url'], SUPublicEDKey=KEY)):
            release.verify_app(Path('/unused'), INFO, CONFIG)
        for field in ('CFBundleVersion', 'CFBundleShortVersionString', 'LSMinimumSystemVersion', 'SUFeedURL', 'SUPublicEDKey'):
            info = dict(INFO, SUFeedURL=CONFIG['feed_url'], SUPublicEDKey=KEY)
            info[field] = 'wrong'
            with self.subTest(field=field), patch.object(release, 'read_info', return_value=info):
                with self.assertRaisesRegex(ValueError, field):
                    release.verify_app(Path('/unused'), INFO, CONFIG)

    def test_published_feed_errors_never_become_empty_history(self):
        def result(code, stdout='', stderr=''):
            return subprocess.CompletedProcess([], code, stdout, stderr)
        cases = [([result(0, '{"private": true}')], 'public repository'),
                 ([result(0, '{"private": false}'), result(1, stderr='HTTP 403')], 'cannot read latest'),
                 ([result(0, '{"private": false}'), result(0, '{"assets": []}')], 'missing appcast.xml'),
                 ([result(0, '{"private": false}'), result(1, stderr='HTTP 404'),
                   result(0, '[[{"draft": false}]]')], 'published releases exist')]
        for commands, error in cases:
            with self.subTest(error=error), patch.object(release, 'run', side_effect=commands), patch.object(release, 'download') as download:
                with self.assertRaisesRegex(ValueError, error):
                    release.published_feed(CONFIG, Path('/unused'))
                download.assert_not_called()

    def test_sparkle_download_is_checksum_gated_and_extracts_only_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'fixture.tar.xz'
            with tarfile.open(archive, 'w:xz') as output:
                for name in ('./bin/sign_update', './bin/generate_keys', '../escape'):
                    data = b'fixture'
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    output.addfile(member, io.BytesIO(data))
            def fetch(url, target):
                shutil.copyfile(archive, target)
            with patch.object(release, 'download', side_effect=fetch):
                with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    release.sparkle_tools(root)
                self.assertFalse((root / '.deps/sparkle-2.10.0/bin/sign_update').exists())
                with patch.object(release, 'SPARKLE_SHA256', release.sha(archive)):
                    tools = release.sparkle_tools(root)
                    self.assertTrue(os.access(tools / 'sign_update', os.X_OK))
                    self.assertTrue(os.access(tools / 'generate_keys', os.X_OK))
                    self.assertFalse((root / 'escape').exists())
                    release.sparkle_tools(root)

    def test_public_verification_rejects_wrong_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dmg, feed = root / 'LinuxVM-0.1.0.dmg', root / 'appcast.xml'
            dmg.write_bytes(b'expected')
            feed.write_bytes(release.appcast('0.1.0', INFO, CONFIG, SIGNATURE, 8, 'Notes', []))
            def fetch(url, target):
                target.write_bytes(b'wrong')
            with patch.object(release, 'download', side_effect=fetch), patch.object(release.time, 'sleep'):
                with self.assertRaisesRegex(ValueError, 'public bytes differ'):
                    release.verify_public(CONFIG, '0.1.0', dmg, feed, root)


STUB = '''#!/usr/bin/env python3
import json, os, pathlib, plistlib, subprocess, sys
root = pathlib.Path(os.environ['STUB_ROOT'])
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with (root / 'commands.jsonl').open('a') as log:
    log.write(json.dumps([name] + args) + '\\n')
if os.environ.get('STUB_FAIL') == name:
    print('fixture command failed', file=sys.stderr); sys.exit(1)
if name == 'git':
    if args[:2] == ['branch', '--show-current']: print('main')
    elif args[:1] == ['rev-parse']: print('a' * 40)
elif name == 'gh':
    if args[0] == 'api':
        if args[-1].endswith('/releases/latest'):
            if os.environ.get('STUB_FIRST_RELEASE'):
                print('gh: Not Found (HTTP 404)', file=sys.stderr); sys.exit(1)
            print(json.dumps({'assets': [{'name': 'appcast.xml'}]}))
        elif args[-1].endswith('/releases'): print('[[]]')
        else: print(json.dumps({'private': False}))
elif name == 'generate_keys': print(os.environ['STUB_PUBLIC_KEY'])
elif name == 'sign_update':
    if '-p' in args: print(os.environ['STUB_SIGNATURE'])
elif name == 'build-runtime.sh':
    runtime = root / '.deps/try-omarchy/macos/.build/qemu-gpu-runtime/bin/qemu-system-aarch64'
    runtime.parent.mkdir(parents=True); runtime.write_text('stub'); runtime.chmod(0o755)
elif name == 'build-app.sh':
    assert os.environ['LINUXVM_SIGN_IDENTITY'] == 'Developer ID Application: Fixture (TEST)'
    info = plistlib.loads((root / 'macos/Resources/Info.plist').read_bytes())
    info.update(SUFeedURL=os.environ['LINUXVM_UPDATE_FEED'], SUPublicEDKey=os.environ['LINUXVM_UPDATE_KEY'])
    target = root / 'build/Linux VM.app/Contents/Info.plist'
    target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(plistlib.dumps(info))
    subprocess.run(['codesign', '--sign', os.environ['LINUXVM_SIGN_IDENTITY'], str(target.parent.parent)], check=True)
elif name == 'package-dmg.sh':
    assert os.environ['LINUXVM_NOTARY_PROFILE'] == 'linuxvm-notary'
    subprocess.run(['xcrun', 'notarytool', 'submit', 'fixture', '--keychain-profile', 'linuxvm-notary'], check=True)
    (root / 'build/Linux VM 0.1.0.dmg').write_bytes(b'fixture DMG bytes\\n')
elif name == 'retain-release-source.py':
    import hashlib, io, tarfile
    target = pathlib.Path(args[args.index('--output') + 1]); target.parent.mkdir(parents=True, exist_ok=True)
    index = json.dumps({'complete': True, 'revision': 'a' * 40}).encode()
    with tarfile.open(target, 'w:gz') as archive:
        member = tarfile.TarInfo('release-source/SOURCE-INDEX.json'); member.size = len(index)
        archive.addfile(member, io.BytesIO(index))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(target.suffix + '.sha256').write_text(f'{digest}  {target.name}\\n')
'''


class ReleaseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / 'repo'
        self.root.mkdir()
        for relative in ('macos/Resources', 'scripts', 'docs/releases', 'stub-bin', '.deps/sparkle-2.10.0/bin'):
            (self.root / relative).mkdir(parents=True)
        (self.root / 'macos/Resources/Info.plist').write_bytes(plistlib.dumps(INFO))
        (self.root / 'docs/releases/0.1.0.md').write_text('# Linux VM 0.1.0\n\n- **Fixture** release.\n- [Details](https://example.invalid/notes).\n')
        self.config = self.root / 'scripts/release-config.json'
        self.config.write_text(json.dumps(dict(CONFIG, source_archive_directory=str(Path(self.scratch.name) / 'retained'))))
        for name in ('git', 'gh', 'codesign', 'spctl', 'xcrun'):
            self.stub(self.root / 'stub-bin' / name)
        for name in ('build-runtime.sh', 'build-app.sh', 'package-dmg.sh', 'retain-release-source.py'):
            self.stub(self.root / 'scripts' / name)
        for name in ('generate_keys', 'sign_update'):
            self.stub(self.root / '.deps/sparkle-2.10.0/bin' / name)
        self.env = dict(os.environ, PATH=str(self.root / 'stub-bin') + os.pathsep + os.environ['PATH'],
                        STUB_ROOT=str(self.root), STUB_PUBLIC_KEY=KEY, STUB_SIGNATURE=SIGNATURE,
                        LINUXVM_SIGN_IDENTITY='Developer ID Application: Fixture (TEST)')
        for key in ('LINUXVM_NOTARY_PROFILE', 'LINUXVM_RELEASE_SOURCE_DIR', 'STUB_FIRST_RELEASE'):
            self.env.pop(key, None)
        self.downloads = []

    def stub(self, path):
        path.write_text(STUB)
        path.chmod(0o755)

    def fetch(self, url, target):
        self.downloads.append(url)
        if url == CONFIG['feed_url']:
            target.write_bytes(EARLIER)
        else:
            self.fail(f'unexpected network download: {url}')

    def execute(self, dry_run=True, fetch=None):
        output = io.StringIO()
        with patch.dict(os.environ, self.env, clear=True), patch.object(release, 'download', side_effect=fetch or self.fetch), redirect_stdout(output):
            directory = release.release('0.1.0', dry_run, self.config, root=self.root, env=self.env)
        return directory, output.getvalue()

    def commands(self):
        return [json.loads(line) for line in (self.root / 'commands.jsonl').read_text().splitlines()]

    def test_stubbed_dry_run_leaves_expected_artifacts_and_no_public_mutations(self):
        with patch('builtins.input', side_effect=AssertionError('dry run must not prompt')):
            directory, output = self.execute()
        self.assertEqual((directory / 'LinuxVM-0.1.0.dmg').read_bytes(), b'fixture DMG bytes\n')
        self.assertEqual(len(release.parse_feed((directory / 'appcast.xml').read_bytes())), 2)
        self.assertIn('build 2', output)
        self.assertIn('Keep this archive for at least three years', output)
        self.assertIn('Nothing was tagged, pushed or published', output)
        commands = self.commands()
        self.assertIn(['xcrun', 'stapler', 'validate', str(directory / 'LinuxVM-0.1.0.dmg')], commands)
        self.assertTrue(any(c[:2] == ['sign_update', '--verify'] for c in commands))
        self.assertFalse(any(c[:2] in (['git', 'push'], ['git', 'tag']) and c[2] != '--list' for c in commands))
        self.assertFalse(any(c[:2] == ['gh', 'release'] for c in commands))
        artifact_output = os.environ.get('LINUXVM_TEST_RELEASE_ARTIFACTS')
        if artifact_output:
            target = Path(artifact_output)
            target.mkdir(parents=True, exist_ok=True)
            for name in ('appcast.xml', 'LinuxVM-0.1.0.dmg', 'summary.txt'):
                shutil.copyfile(directory / name, target / name)
            (target / 'dry-run-output.txt').write_text(output)

    def test_a_later_run_reuses_the_retained_source_of_the_same_commit(self):
        with patch('builtins.input', side_effect=AssertionError('dry run must not prompt')):
            self.execute()
            directory, output = self.execute()
        self.assertIn('Reusing the retained source', output)
        self.assertEqual(sum(c[0] == 'retain-release-source.py' for c in self.commands()), 1)
        source = next((Path(self.scratch.name) / 'retained').glob('*-source.tar.gz'))
        release.check_retained_source(source, 'a' * 40)
        with self.assertRaisesRegex(ValueError, 'not a complete archive'):
            release.check_retained_source(source, 'b' * 40)
        source.with_suffix(source.suffix + '.sha256').write_text('0' * 64 + '  x\n')
        with self.assertRaisesRegex(ValueError, 'does not match its checksum file'):
            release.check_retained_source(source, 'a' * 40)

    def test_cli_dry_run_with_temporary_config(self):
        shutil.copyfile(ROOT / 'scripts/release.py', self.root / 'scripts/release.py')
        self.env['STUB_FIRST_RELEASE'] = '1'
        result = subprocess.run([sys.executable, str(self.root / 'scripts/release.py'), '0.1.0', '--dry-run',
                                 '--config', str(self.config)], cwd=self.root, env=self.env, text=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Dry run complete', result.stdout)
        directory = self.root / 'build/release/0.1.0'
        self.assertTrue((directory / 'LinuxVM-0.1.0.dmg').exists())
        self.assertEqual(len(release.parse_feed((directory / 'appcast.xml').read_bytes())), 1)
        self.assertFalse(any(c[:2] == ['gh', 'release'] or c[:2] == ['git', 'push'] for c in self.commands()))
        artifact_output = os.environ.get('LINUXVM_TEST_RELEASE_ARTIFACTS')
        if artifact_output:
            target = Path(artifact_output) / 'cli'
            target.mkdir(parents=True, exist_ok=True)
            for name in ('appcast.xml', 'LinuxVM-0.1.0.dmg', 'summary.txt'):
                shutil.copyfile(directory / name, target / name)
            (target / 'dry-run-output.txt').write_text(result.stdout)

    def test_first_release_needs_no_existing_feed(self):
        self.env['STUB_FIRST_RELEASE'] = '1'
        directory, _ = self.execute()
        self.assertEqual(len(release.parse_feed((directory / 'appcast.xml').read_bytes())), 1)
        self.assertFalse(self.downloads)

    def test_missing_notes_and_identity_fail_before_commands(self):
        notes = self.root / 'docs/releases/0.1.0.md'
        notes.unlink()
        with self.assertRaisesRegex(ValueError, 'notes are missing'):
            self.execute()
        notes.write_text('Notes')
        self.env['LINUXVM_SIGN_IDENTITY'] = '-'
        with self.assertRaisesRegex(ValueError, 'Developer ID Application'):
            self.execute()
        self.assertFalse((self.root / 'commands.jsonl').exists())

    def test_published_build_blocks_before_signing(self):
        (self.root / 'macos/Resources/Info.plist').write_bytes(plistlib.dumps(dict(INFO, CFBundleVersion='1')))
        with self.assertRaisesRegex(ValueError, 'greater than every'):
            self.execute()
        self.assertFalse(any(c[0] in ('generate_keys', 'build-app.sh', 'sign_update') for c in self.commands()))

    def test_failed_notarization_stops_before_update_signing_or_publication(self):
        self.env['STUB_FAIL'] = 'xcrun'
        with self.assertRaisesRegex(ValueError, 'fixture command failed'):
            self.execute()
        self.assertFalse(any(c[0] == 'sign_update' or c[:2] == ['gh', 'release'] for c in self.commands()))

    def test_wrong_key_refuses_before_building_or_signing(self):
        self.env['STUB_PUBLIC_KEY'] = base64.b64encode(b'x' * 32).decode()
        with self.assertRaisesRegex(ValueError, 'keychain EdDSA public key differs'):
            self.execute()
        self.assertFalse(any(c[0] in ('build-app.sh', 'sign_update') for c in self.commands()))

    def test_cancel_does_not_publish(self):
        with patch('builtins.input', return_value='no'):
            _, output = self.execute(dry_run=False)
        self.assertIn('Publication cancelled', output)
        self.assertFalse(any(c[:2] == ['gh', 'release'] or c[:2] == ['git', 'push'] for c in self.commands()))

    def test_publish_orders_tag_draft_and_publication_then_checks_public_bytes(self):
        def fetch(url, target):
            if url == CONFIG['feed_url'] and len(self.downloads) < 2:
                return self.fetch(url, target)
            self.downloads.append(url)
            directory = self.root / 'build/release/0.1.0'
            shutil.copyfile(directory / ('appcast.xml' if url == CONFIG['feed_url'] else 'LinuxVM-0.1.0.dmg'), target)
        with patch('builtins.input', return_value='publish'):
            _, output = self.execute(dry_run=False, fetch=fetch)
        commands = self.commands()
        tag = next(i for i, c in enumerate(commands) if c[:3] == ['git', 'tag', '-a'])
        push = next(i for i, c in enumerate(commands) if c[:2] == ['git', 'push'])
        draft = next(i for i, c in enumerate(commands) if c[:3] == ['gh', 'release', 'create'])
        publish = next(i for i, c in enumerate(commands) if c[:3] == ['gh', 'release', 'edit'])
        self.assertLess(tag, push)
        self.assertLess(push, draft)
        self.assertLess(draft, publish)
        self.assertIn('--draft', commands[draft])
        self.assertIn('--draft=false', commands[publish])
        self.assertIn('--latest', commands[publish])
        self.assertEqual(len(self.downloads), 4)
        self.assertIn('Published and verified', output)

    def test_changed_feed_after_confirmation_refuses_to_publish(self):
        count = 0
        def fetch(url, target):
            nonlocal count
            count += 1
            target.write_bytes(EARLIER if count == 1 else EARLIER.replace(b'Earlier notes.', b'Changed notes.'))
        with patch('builtins.input', return_value='publish'), self.assertRaisesRegex(ValueError, 'feed changed'):
            self.execute(dry_run=False, fetch=fetch)
        self.assertFalse(any(c[:2] == ['git', 'push'] for c in self.commands()))


if __name__ == '__main__':
    unittest.main()
