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

    def test_complete_archive_refuses_known_source_gaps(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['python3', str(ROOT / 'scripts/retain-release-source.py'),
                                     '--output', str(Path(directory) / 'complete.tar.gz')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('complete source unavailable: ANGLE', result.stderr)
            self.assertFalse((Path(directory) / 'complete.tar.gz').exists())


if __name__ == '__main__':
    unittest.main()
