"""Source retention integrity, recursive git inputs and incomplete-bundle labels."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from argparse import Namespace

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('retention', ROOT / 'scripts/retain-release-source.py')
retention = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retention)


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], stderr=subprocess.PIPE, text=True).strip()


class RetentionTests(unittest.TestCase):
    def test_cached_source_checksum_is_verified_before_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / 'stage'
            stage.mkdir()
            source = root / 'source.tar.gz'
            source.write_bytes(b'source')
            item = {'archive': source.name, 'url': 'https://example.invalid/source',
                    'sha256': hashlib.sha256(b'source').hexdigest()}
            collector = retention.Collector(stage, root / 'cache')
            collector.download('fixture', item, source)
            self.assertEqual(collector.artifacts['fixture']['bytes'], 6)
            source.write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, 'checksum differs'):
                collector.download('fixture', item, source)

    def test_git_sources_retain_pinned_submodules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / 'child'
            parent = root / 'parent'
            for path in (child, parent):
                path.mkdir()
                git(path, 'init', '--quiet')
                (path / 'payload').write_text(path.name)
                git(path, 'add', '.')
                git(path, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--quiet', '-m', 'source')
            git(parent, '-c', 'protocol.file.allow=always', 'submodule', 'add', '--quiet', str(child), 'vendor/child')
            git(parent, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--quiet', '-am', 'submodule')
            stage = root / 'stage'
            stage.mkdir()
            collector = retention.Collector(stage, root / 'cache')
            revision = git(parent, 'rev-parse', 'HEAD')
            collector.git('fixture', {'url': str(parent), 'commit': revision})
            self.assertEqual(set(collector.artifacts), {'fixture', 'fixture/vendor/child'})
            record = collector.artifacts['fixture/vendor/child']
            self.assertEqual(record['commit'], git(child, 'rev-parse', 'HEAD'))
            with tarfile.open(stage / record['path']) as archive:
                self.assertEqual(archive.extractfile('source/payload').read(), b'child')
            with self.assertRaisesRegex(ValueError, 'invalid commit'):
                collector.git('invalid', {'url': str(parent), 'commit': 'main'})

    @unittest.skipUnless((ROOT / '.deps/source-archives').is_dir(), 'bottles not installed')
    def test_every_formula_source_resource_and_patch_is_pinned(self):
        manifest = retention.notices.load()
        plan = json.loads((ROOT / 'licenses/source-inputs.json').read_text())
        retention.formula_sources(manifest, plan, ROOT / '.deps/source-archives')
        broken = copy.deepcopy(plan)
        broken['bottles']['bottle-zstd']['sources'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'source differs'):
            retention.formula_sources(manifest, broken, ROOT / '.deps/source-archives')
        broken = copy.deepcopy(plan)
        broken['bottles']['bottle-glib']['patches'] = []
        with self.assertRaisesRegex(ValueError, 'uncovered formula patch'):
            retention.formula_sources(manifest, broken, ROOT / '.deps/source-archives')

    def test_final_container_rejects_modified_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.tar.gz'
            for content, valid in ((b'original', True), (b'modified', False)):
                with tarfile.open(path, 'w:gz') as archive:
                    for name, data in [('payload', content), ('SHA256SUMS', (hashlib.sha256(b'original').hexdigest() + '  payload\n').encode())]:
                        member = tarfile.TarInfo('release-source/' + name)
                        member.size = len(data)
                        archive.addfile(member, io.BytesIO(data))
                if valid:
                    retention.verify_bundle(path)
                else:
                    with self.assertRaisesRegex(ValueError, 'retained checksum differs'):
                        retention.verify_bundle(path)

    def test_copyleft_inputs_cannot_be_optional(self):
        manifest = retention.notices.load()
        self.assertFalse(retention.retention_required(manifest, 'angle-source', manifest['inputs']['angle-source']))
        for key in ('qemu', 'bottle-glib', 'bottle-gettext', 'bottle-libusb'):
            item = dict(manifest['inputs'][key], retention='best-effort')
            with self.assertRaisesRegex(ValueError, 'copyleft'):
                retention.retention_required(manifest, key, item)

    def test_content_pinned_archives_are_downloaded_not_fetched_with_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git(root, 'init', '--quiet')
            (root / 'licenses').mkdir()
            item = {'retention': 'best-effort', 'archive': 'vma.tar.gz', 'commit': 'c' * 40, 'content_sha256': 'd' * 64,
                    'url': 'https://chromium.googlesource.com/example/+archive/' + 'c' * 40 + '.tar.gz'}
            manifest = {'components': [{'id': 'angle', 'inputs': ['angle-vma'], 'license': 'MIT'}], 'inputs': {'angle-vma': item}}
            (root / 'licenses/manifest.json').write_text(json.dumps(manifest))
            (root / 'licenses/source-inputs.json').write_text(json.dumps({'extra_sources': {}, 'bottles': {}, 'gaps': []}))
            git(root, 'add', '.')
            git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--quiet', '-m', 'fixture')
            args = Namespace(subset=None, output=root / 'complete.tar.gz', inputs=root, cache=root / 'cache')
            downloaded = []

            def download(collector, key, item, existing):
                downloaded.append(key)
                payload = collector.stage / key
                payload.write_bytes(b'archive')
                collector.record(key, payload, item)

            with patch.object(retention, 'ROOT', root), patch.object(retention.notices, 'load', return_value=manifest), \
                    patch.object(retention, 'formula_sources', return_value={}), \
                    patch.object(retention.Collector, 'download', download), \
                    patch.object(retention.Collector, 'git', side_effect=AssertionError('fetched with git')):
                retention.collect(args)
            self.assertEqual(downloaded, ['angle-vma'])

    def test_optional_angle_failure_does_not_hide_required_source_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git(root, 'init', '--quiet')
            (root / 'licenses').mkdir()
            manifest = {'components': [{'id': 'angle', 'inputs': ['angle-source'], 'license': 'BSD-3-Clause'},
                                       {'id': 'qemu', 'inputs': ['qemu'], 'license': 'GPL-2.0-only'}],
                        'inputs': {'angle-source': {'retention': 'best-effort', 'archive': 'angle.tar.gz'}, 'qemu': {'archive': 'qemu.tar.gz'}}}
            (root / 'licenses/manifest.json').write_text(json.dumps(manifest))
            (root / 'licenses/source-inputs.json').write_text(json.dumps({'extra_sources': {}, 'bottles': {}, 'gaps': []}))
            git(root, 'add', '.')
            git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--quiet', '-m', 'fixture')
            args = Namespace(subset=None, output=root / 'complete.tar.gz', inputs=root, cache=root / 'cache')

            def download(collector, key, item, existing):
                if key == 'angle-source':
                    raise OSError('optional ANGLE unavailable')
                payload = collector.stage / key
                payload.write_bytes(b'required source')
                collector.record(key, payload, item)

            with patch.object(retention, 'ROOT', root), patch.object(retention.notices, 'load', return_value=manifest), \
                    patch.object(retention, 'formula_sources', return_value={}), \
                    patch.object(retention.Collector, 'download', download):
                retention.collect(args)
            with tarfile.open(args.output) as archive:
                index = json.load(archive.extractfile('release-source/SOURCE-INDEX.json'))
            self.assertTrue(index['complete'])
            self.assertIn('angle-source', index['optional_failures'])
            self.assertIn('qemu', index['artifacts'])
            args.output.unlink()
            with patch.object(retention, 'ROOT', root), patch.object(retention.notices, 'load', return_value=manifest), \
                    patch.object(retention, 'run', side_effect=[b'', b'test-revision']), \
                    patch.object(retention, 'formula_sources', return_value={}), \
                    patch.object(retention.Collector, 'download', side_effect=OSError('required source missing')):
                with self.assertRaisesRegex(OSError, 'required source missing'):
                    retention.collect(args)
            self.assertFalse(args.output.exists())


if __name__ == '__main__':
    unittest.main()
