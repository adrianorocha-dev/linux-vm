"""Independent binary-format checks: no builder or license-reader parsing helpers."""
import gzip
import hashlib
import importlib.util
import io
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rpm_builder', ROOT / 'build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def read_header(blob, start, region):
    assert blob[start:start + 8] == bytes.fromhex('8eade80100000000')
    n, size = struct.unpack_from('>II', blob, start + 8)
    store = start + 16 + n * 16
    end = store + size
    tags = {}
    ids = []
    for i in range(n):
        tag, kind, offset, count = struct.unpack_from('>4I', blob, start + 16 + i * 16)
        ids.append(tag)
        pos = store + offset
        assert pos < end
        if kind in (3, 4, 5):
            width, code = {3: (2, 'H'), 4: (4, 'I'), 5: (8, 'Q')}[kind]
            assert offset % width == 0 and pos + count * width <= end
            value = list(struct.unpack_from('>' + str(count) + code, blob, pos))
        elif kind == 7:
            value = blob[pos:pos + count]
        else:
            assert kind in (6, 8, 9)
            value = []
            for _ in range(count):
                stop = blob.index(0, pos, end)
                value.append(blob[pos:stop].decode())
                pos = stop + 1
            if kind == 6:
                assert count == 1
                value = value[0]
        tags[tag] = value
    assert ids == sorted(set(ids)) and ids[0] == region
    assert tags[region] == struct.pack('>IIiI', region, 7, -16 * n, 16)
    return tags, end, blob[start:end]


def read_cpio(raw):
    pos = 0
    files = {}
    while True:
        assert raw[pos:pos + 6] == b'070701'
        fields = [int(raw[pos + i:pos + i + 8], 16) for i in range(6, 110, 8)]
        inode, mode, uid, gid, links, mtime, size, major, minor, rmajor, rminor, namesize, check = fields
        name = raw[pos + 110:pos + 110 + namesize]
        assert name[-1:] == b'\0'
        name = name[:-1].decode()
        pos = (pos + 110 + namesize + 3) // 4 * 4
        content = raw[pos:pos + size]
        pos = (pos + size + 3) // 4 * 4
        if name == 'TRAILER!!!':
            assert size == 0 and not any(raw[pos:])
            return files
        assert name.startswith('./') and name[2:] not in files
        assert (uid, gid, mtime, major, minor, rmajor, rminor, check) == (0, 0, builder.EPOCH, 0, 0, 0, 0, 0)
        assert mode in (0o40755, 0o100644)
        files[name[2:]] = (mode, content, inode)


class RPMTests(unittest.TestCase):
    def test_format_metadata_payload_and_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.rpm'
            rpm = builder.build_rpm(path).read_bytes()
            self.assertEqual(builder.build_rpm(path).read_bytes(), rpm)
            deb = builder.build(Path(tmp) / 'test.deb').read_bytes()
        self.assertEqual(rpm[:6], bytes.fromhex('edabeedb0300'))
        self.assertEqual(len(rpm[:96]), 96)
        sig, end, _ = read_header(rpm, 96, 62)
        self.assertEqual(rpm[end:(end + 7) // 8 * 8], b'\0' * (-end % 8))
        tags, end, header = read_header(rpm, (end + 7) // 8 * 8, 63)
        payload = rpm[end:]
        raw = gzip.decompress(payload)
        self.assertEqual(sig[273], hashlib.sha256(header).hexdigest())
        self.assertEqual(sig[269], hashlib.sha1(header).hexdigest())
        self.assertEqual(sig[1004], hashlib.md5(header + payload).digest())
        self.assertEqual(sig[1000], [len(header) + len(payload)])
        self.assertEqual(sig[1007], [len(raw)])
        self.assertEqual(tags[5092], [hashlib.sha256(payload).hexdigest()])
        self.assertEqual(tags[5097], [hashlib.sha256(raw).hexdigest()])
        self.assertEqual(tags[5093], [8])
        self.assertEqual(int.from_bytes(payload[4:8], 'little'), builder.EPOCH)
        self.assertEqual(payload[8], 2)  # gzip level 9
        cpio = read_cpio(raw)
        cursor = 8
        while cursor < len(deb):
            h = deb[cursor:cursor + 60]
            size = int(h[48:58])
            if h[:16].decode().strip().rstrip('/') == 'data.tar.gz':
                with tarfile.open(fileobj=io.BytesIO(deb[cursor + 60:cursor + 60 + size])) as tar:
                    data = {m.name: tar.extractfile(m).read() for m in tar if m.isfile()}
            cursor += 60 + size + size % 2
        self.assertEqual({k: v[1] for k, v in cpio.items() if stat.S_ISREG(v[0])}, data)
        self.assertEqual({k for k, v in cpio.items() if stat.S_ISDIR(v[0])},
                         {'usr/lib/linuxvm', 'usr/share/doc/linuxvm-guest',
                          'usr/share/gnome-shell', 'usr/share/gnome-shell/extensions',
                          'usr/share/gnome-shell/extensions/clipboard@linuxvm.dev'})
        names = [(tags[1118][i] + b).lstrip('/') for i, b in zip(tags[1116], tags[1117], strict=True)]
        self.assertEqual(names, sorted(cpio))
        self.assertEqual(tags[5011], [8])
        for i, name in enumerate(names):
            mode, content, inode = cpio[name]
            self.assertEqual(tags[1030][i], mode)
            self.assertEqual(tags[1028][i], len(content))
            self.assertEqual(tags[1034][i], builder.EPOCH)
            self.assertEqual((tags[1039][i], tags[1040][i]), ('root', 'root'))
            self.assertEqual(tags[1096][i], inode)
            self.assertEqual(tags[1035][i], hashlib.sha256(content).hexdigest() if stat.S_ISREG(mode) else '')
            self.assertEqual(tags[1037][i], 2 if name.endswith('/copyright') else 0)
        for tag, value in {1000: 'linuxvm-guest', 1001: builder.VERSION, 1002: '1',
                           1014: 'MIT', 1020: 'https://github.com/adrianorocha-dev/linux-vm',
                           1021: 'linux', 1022: 'noarch', 1132: 'noarch',
                           1124: 'cpio', 1125: 'gzip', 1126: '9'}.items():
            self.assertEqual(tags[tag], value)
        self.assertEqual(tags[1006], [builder.EPOCH])
        self.assertEqual(tags[1007], 'linuxvm-builder')
        self.assertNotIn('GNOME', tags[1004][0])
        self.assertEqual(tags[1047], ['linuxvm-guest'])
        self.assertEqual(tags[1112], [8])
        self.assertEqual(tags[1113], [builder.VERSION + '-1'])
        deps = list(zip(tags[1049], tags[1050], tags[1048], strict=True))
        self.assertEqual({n for n, v, f in deps if f == 0},
                         {'python3', 'python3-gobject-base', 'pulseaudio-utils', 'systemd'})
        for bit in (9, 10, 11, 12):
            self.assertIn(('/bin/sh', '', 256 | (1 << bit)), deps)
        for feature, version in [('CompressedFileNames', '3.0.4-1'), ('PayloadFilesHavePrefix', '4.0-1'),
                                 ('FileDigests', '4.6.0-1')]:
            self.assertIn(('rpmlib(' + feature + ')', version, (1 << 24) | 10), deps)
        self.assertTrue(all(tag not in tags for tag in (5046, 5047, 5048)))
        for tag, name in enumerate(('pre', 'post', 'preun', 'postun'), 1023):
            self.assertEqual(tags[tag], (ROOT / 'rpm' / name).read_text())
            self.assertEqual(tags[tag + 62], ['/bin/sh'])

    def test_scriptlet_mapping_syntax_and_upgrade_noops(self):
        for name, deb, arg in [('pre', 'prerm', 'upgrade'), ('post', 'postinst', 'configure'),
                               ('preun', 'prerm', 'remove'), ('postun', 'postrm', 'purge')]:
            script = ROOT / 'rpm' / name
            subprocess.run(['/bin/sh', '-n', script], check=True)
            self.assertEqual(script.read_text().split('set -- ' + arg + '\n', 1)[1],
                             (ROOT / 'debian' / deb).read_text().split('set -eu\n', 1)[1])
            if name != 'post':
                guard = '[ "$1" -ge 2 ] || exit 0' if name == 'pre' else '[ "$1" -eq 0 ] || exit 0'
                self.assertIn(guard, script.read_text())
                # Empty PATH makes any accidentally executed cleanup command fail.
                for count in ([0, 1] if name == 'pre' else [1, 2]):
                    subprocess.run(['/bin/sh', script, str(count)], env={'PATH': ''}, check=True)


class InstallerTests(unittest.TestCase):
    def test_package_manager_selection_and_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            # stage actual packages into a temporary disc, then isolate command discovery.
            builder.build(base / 'dist' / builder.DEB)
            builder.build_rpm(base / 'dist' / builder.RPM)
            oldroot = builder.ROOT
            try:
                builder.ROOT = base
                (base / 'iso').mkdir()
                for n in ('install.sh', 'README.txt'):
                    shutil.copyfile(ROOT / 'iso' / n, base / 'iso' / n)
                disc = base / 'disc'
                builder.stage_iso(disc)
            finally:
                builder.ROOT = oldroot
            binpath = base / 'bin'
            binpath.mkdir()
            (binpath / 'dirname').symlink_to('/usr/bin/dirname')
            log = base / 'commands'
            for name in ('sudo', 'apt-get', 'dnf'):
                p = binpath / name
                p.write_text('#!/bin/sh\nprintf "%s\\n" "' + name + ' $*" >> "$LOG"\n')
                if name == 'sudo':
                    p.write_text(p.read_text() + 'exec "$@"\n')
                p.chmod(0o755)
            env = {'PATH': str(binpath), 'LOG': str(log)}
            def run():
                return subprocess.run(['/bin/sh', disc / 'install.sh'], env=env, capture_output=True, text=True)
            for manager, package in [('apt-get', builder.DEB), ('dnf', builder.RPM)]:
                result = run()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Log out', result.stdout)
                self.assertEqual(log.read_text(), f'sudo {manager} install -y ./{package}\n{manager} install -y ./{package}\n')
                log.unlink()
                (binpath / manager).unlink()
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('support Ubuntu and Fedora', result.stderr)
            for filename in (builder.DEB, builder.RPM):
                original = disc / filename
                content = original.read_bytes()
                original.unlink()
                self.assertIn('Expected exactly one', run().stderr)
                original.write_bytes(content)
                duplicate = disc / filename.replace(builder.VERSION, '9.9.9')
                duplicate.write_bytes(content)
                self.assertIn('Expected exactly one', run().stderr)
                duplicate.unlink()


if __name__ == '__main__':
    unittest.main()
