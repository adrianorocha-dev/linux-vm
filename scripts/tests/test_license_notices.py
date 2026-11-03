import copy
import importlib.util
from pathlib import Path
import shutil
import tempfile
import io
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('license_notices', ROOT / 'scripts/license-notices.py')
notices = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notices)


class LicenseTests(unittest.TestCase):
    def setUp(self):
        self.manifest = notices.load()

    def test_manifest_texts_and_release_gates(self):
        notices.validate_manifest(self.manifest)
        with self.assertRaisesRegex(notices.LicenseError, 'offer_contact'):
            notices.validate_manifest(self.manifest, identity='Developer ID Application: test')
        self.manifest['offer_contact'] = 'source@example.invalid'
        with self.assertRaisesRegex(notices.LicenseError, 'unresolved license provenance'):
            notices.validate_manifest(self.manifest, identity='Developer ID Application: test')
        self.manifest['release_blockers'] = []
        with self.assertRaisesRegex(notices.LicenseError, 'incomplete license evidence'):
            notices.validate_manifest(self.manifest, identity='Developer ID Application: test')
        for component in self.manifest['components']:
            component.pop('license_status', None)
        notices.validate_manifest(self.manifest, identity='Developer ID Application: test')

    def test_upstream_pins_with_local_diff_and_build_app_pins(self):
        notices.validate_pins(self.manifest, deps=ROOT / '.deps')

    def test_changed_pin_and_component_version_fail(self):
        broken = copy.deepcopy(self.manifest)
        broken['inputs']['slirp']['sha256'] = '0' * 64
        with self.assertRaisesRegex(notices.LicenseError, 'checksum differs'):
            notices.validate_pins(broken)
        broken = copy.deepcopy(self.manifest)
        next(c for c in broken['components'] if c['id'] == 'glib')['version'] = '99.0'
        with self.assertRaisesRegex(notices.LicenseError, 'component version differs'):
            notices.validate_pins(broken)

    def test_git_commit_pin_change_fails(self):
        self.manifest['inputs']['qemu']['commit'] = '0' * 40
        with self.assertRaisesRegex(notices.LicenseError, 'source commit differs'):
            notices.validate_pins(self.manifest)

    @unittest.skipUnless((ROOT / '.deps/source-archives/git').is_dir(), 'git sources not installed')
    def test_git_archive_members_are_verified_without_a_transport_hash(self):
        item = self.manifest['inputs']['keycodemap']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'git').symlink_to(ROOT / '.deps/source-archives/git', target_is_directory=True)
            path = root / item['archive']
            with tarfile.open(path, 'w:gz') as archive:
                member = tarfile.TarInfo('injected.c')
                member.size = 8
                archive.addfile(member, io.BytesIO(b'injected'))
            with self.assertRaisesRegex(notices.LicenseError, 'archive differs from verified git objects'):
                notices.verify_git_archive(item, path, root)

    @unittest.skipUnless((ROOT / '.deps/source-archives').is_dir(), 'pinned dependency archives are not installed')
    def test_versions_and_license_bytes_from_actual_pinned_inputs(self):
        notices.validate_archives(self.manifest, ROOT / '.deps/source-archives')
        broken = copy.deepcopy(self.manifest)
        next(c for c in broken['components'] if c['id'] == 'qemu')['version'] = '99.0'
        with self.assertRaisesRegex(notices.LicenseError, 'inventory version differs'):
            notices.validate_archives(broken, ROOT / '.deps/source-archives')

    def make_bundle(self, directory):
        bundle = Path(directory) / 'Test.app'
        for component in self.manifest['components']:
            for name in component['bundle_files']:
                if name in component.get('optional_files', []):
                    continue
                path = bundle / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'test fixture')
        for component in self.manifest['components']:
            for name, target in component.get('bundle_symlinks', {}).items():
                path = bundle / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(target)
        notices.write_notices(self.manifest, bundle)
        return bundle

    def test_uncovered_dylib_macho_and_resource_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.make_bundle(directory)
            notices.validate_bundle(self.manifest, bundle)
            for name, data in [('Contents/Resources/runtime/lib/new.dylib', b'\xcf\xfa\xed\xfe'),
                               ('Contents/Helpers/new-tool', b'\xca\xfe\xba\xbe'),
                               ('Contents/Resources/new-component.dat', b'new'),
                               ('Contents/Frameworks/Sparkle.framework/Versions/B/new.dylib', b'new')]:
                path = bundle / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                with self.assertRaisesRegex(notices.LicenseError, 'uncovered bundle file'):
                    notices.validate_bundle(self.manifest, bundle)
                path.unlink()

    def test_removing_component_fails(self):
        self.manifest['components'] = [c for c in self.manifest['components'] if c['id'] != 'glib']
        with self.assertRaisesRegex(notices.LicenseError, 'missing component entry'):
            notices.validate_manifest(self.manifest)
        self.manifest = notices.load()
        self.manifest['components'] = [c for c in self.manifest['components'] if c['id'] != 'libfdt']
        with self.assertRaisesRegex(notices.LicenseError, 'missing component entry'):
            notices.validate_manifest(self.manifest)

    def test_missing_source_license_and_missing_bundled_license_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'licenses', root / 'licenses')
            name = self.manifest['components'][0]['license_files'][0]
            (root / 'licenses/texts' / name).unlink()
            with self.assertRaisesRegex(notices.LicenseError, 'missing license text'):
                notices.validate_manifest(self.manifest, root)
            bundle = self.make_bundle(directory)
            (bundle / 'Contents/Resources/Licenses/GPL-2.0.txt').unlink()
            with self.assertRaisesRegex(notices.LicenseError, 'missing bundled notices'):
                notices.validate_bundle(self.manifest, bundle)

    def test_symlinks_and_empty_component_directories_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.make_bundle(directory)
            path = bundle / 'Contents/Frameworks/Unlisted.framework'
            path.mkdir(parents=True)
            with self.assertRaisesRegex(notices.LicenseError, 'uncovered bundle directory'):
                notices.validate_bundle(self.manifest, bundle)
            shutil.rmtree(path)
            path = bundle / 'Contents/Resources/link'
            path.symlink_to('/tmp')
            with self.assertRaisesRegex(notices.LicenseError, 'unreviewed bundle symlink'):
                notices.validate_bundle(self.manifest, bundle)

    def test_explicit_framework_style_symlinks_stay_inside_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = self.make_bundle(directory)
            name = 'Contents/Resources/runtime/lib/alias.dylib'
            self.manifest['components'][0]['bundle_symlinks'] = {name: 'libglib-2.0.0.dylib'}
            link = bundle / name
            link.symlink_to('libglib-2.0.0.dylib')
            notices.write_notices(self.manifest, bundle)
            notices.validate_bundle(self.manifest, bundle)
            link.unlink()
            link.symlink_to('/tmp')
            with self.assertRaisesRegex(notices.LicenseError, 'symlink target differs'):
                notices.validate_bundle(self.manifest, bundle)

    @unittest.skipUnless((ROOT / '.deps/try-omarchy/macos/.build/qemu-gpu-runtime').is_dir(), 'runtime not installed')
    def test_every_actual_runtime_file_is_covered(self):
        runtime = ROOT / '.deps/try-omarchy/macos/.build/qemu-gpu-runtime'
        actual = {'Contents/Resources/runtime/' + p.relative_to(runtime).as_posix()
                  for p in runtime.rglob('*') if p.is_file()}
        covered = {name for c in self.manifest['components'] for name in c['bundle_files']
                   if name.startswith('Contents/Resources/runtime/')}
        self.assertEqual(actual, covered)
        self.assertEqual(len(list((runtime / 'lib').glob('*.dylib'))), 15)

    @unittest.skipUnless((ROOT / 'guest/dist/guest-tools.iso').exists(), 'Guest Tools disc not built')
    def test_actual_disc_and_package_members(self):
        iso = ROOT / 'guest/dist/guest-tools.iso'
        notices.validate_guest(self.manifest, iso)
        broken = copy.deepcopy(self.manifest)
        del broken['guest_files']['deb:data/usr/lib/linuxvm/clock.py']
        with self.assertRaisesRegex(notices.LicenseError, 'Guest Tools source file'):
            notices.validate_guest(broken, iso)

    def test_runtime_member_pins_are_covered_offline(self):
        with notices.patched_checkout() as checkout:
            source = (checkout / 'macos/pinned-runtime-bottles.sh').read_text()
        rows = source.split('pinned_runtime_member_manifest()')[1].split('EOF')[1].strip().splitlines()
        covered = {name for c in self.manifest['components'] for name in c['bundle_files']}
        for row in rows:
            relative = row.split('\t')[-1]
            self.assertIn('Contents/Resources/runtime/' + relative, covered)
        for name in ['libEGL.dylib', 'libGLESv2.dylib', 'libepoxy.0.dylib', 'libvirglrenderer.1.dylib']:
            self.assertIn('Contents/Resources/runtime/lib/' + name, covered)


if __name__ == '__main__':
    unittest.main()
