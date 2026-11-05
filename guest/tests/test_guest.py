import base64
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
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'files/usr/lib/linuxvm'))
from common import Lines, folder_name, parse_credential, read_credential, zone_path
from clipboard import (ClipboardSync, MAX_LINE_BYTES, MAX_PAYLOAD_BYTES, PNG_FORMAT,
                       TEXT_FORMAT, decode_message, encode_message)
import share as guest_share
from share import ShareLink, find_share_device, share_is_mounted
from timezone import TimeZoneFollower, decode_zone
from audio import PipeWireMirror, endpoint_name, pulse_module_proplist, pulse_proplist
spec = importlib.util.spec_from_file_location('guest_build', ROOT / 'build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def encode_name(name):
    return base64.urlsafe_b64encode(name.encode()).decode().rstrip('=')


class ClipboardTests(unittest.TestCase):
    def test_roundtrip_and_wire_schema(self):
        for mime, data in [(TEXT_FORMAT, 'Olá\0\nWorld'.encode()), (PNG_FORMAT, b'\x89PNG\r\n\x1a\nbytes')]:
            line = encode_message(mime, data)
            self.assertTrue(line.endswith(b'\n'))
            self.assertEqual(json.loads(line), {'type': 'clipboard', 'format': mime,
                                               'data': base64.b64encode(data).decode()})
            self.assertEqual(decode_message(line), (mime, data))

    def test_schema_and_base64(self):
        for line in [b'[]', b'{}', b'{"type":"sync"}',
                     b'{"type":"clipboard","format":"image/png","data":"%%%"}',
                     b'{"type":"clipboard","format":"image/png","data":"eA==","extra":1}', b'{']:
            with self.subTest(line=line), self.assertRaises(ValueError):
                decode_message(line)

    def test_ignored_payloads(self):
        for mime, data in [('image/jpeg', b'jpeg'), (TEXT_FORMAT, b'\xff'), (PNG_FORMAT, b'')]:
            line = json.dumps({'type': 'clipboard', 'format': mime,
                               'data': base64.b64encode(data).decode()}).encode()
            self.assertIsNone(decode_message(line))
        line = json.dumps({'type': 'clipboard', 'format': PNG_FORMAT,
                           'data': base64.b64encode(b'x' * (MAX_PAYLOAD_BYTES + 1)).decode()}).encode()
        self.assertIsNone(decode_message(line))

    def make_sync(self):
        self.now = 10.0
        self.sent, self.copied = [], []
        return ClipboardSync(self.sent.append, lambda *v: self.copied.append(v), lambda: self.now)

    def test_echo_both_directions_and_expiry(self):
        sync = self.make_sync()
        self.assertTrue(sync.host_changed(TEXT_FORMAT, b'host'))
        self.assertFalse(sync.guest_changed(TEXT_FORMAT, b'host'))
        self.assertTrue(sync.guest_changed(PNG_FORMAT, b'png'))
        self.assertFalse(sync.host_changed(PNG_FORMAT, b'png'))
        self.now += 2.1
        self.assertTrue(sync.host_changed(PNG_FORMAT, b'png'))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(self.copied), 2)

    def test_opposite_change_clears_marker_and_repeat_is_real(self):
        sync = self.make_sync()
        self.assertTrue(sync.guest_changed(TEXT_FORMAT, b'B'))
        self.assertTrue(sync.host_changed(TEXT_FORMAT, b'A'))
        self.assertTrue(sync.host_changed(TEXT_FORMAT, b'B'))
        self.assertFalse(sync.guest_changed(TEXT_FORMAT, b'B'))
        self.assertTrue(sync.guest_changed(TEXT_FORMAT, b'C'))
        self.assertTrue(sync.guest_changed(TEXT_FORMAT, b'B'))
        self.assertFalse(sync.guest_changed('other', b'x'))
        self.assertFalse(sync.guest_changed(TEXT_FORMAT, b''))

    def test_bounded_partial_lines(self):
        lines = Lines(4)
        self.assertEqual(lines.feed(b'ab'), [])
        self.assertEqual(lines.feed(b'cd\nx\ny'), [b'abcd', b'x'])
        self.assertEqual(lines.feed(b'\n'), [b'y'])
        with self.assertRaises(ValueError):
            lines.feed(b'12345\n')
        with self.assertRaises(ValueError):
            Lines(4).feed(b'12345')


class CredentialTests(unittest.TestCase):
    def test_parse_and_read(self):
        data = b'timezone=Asia/Tokyo\nshared_folder_name=V29yaw\n'
        expected = {'timezone': 'Asia/Tokyo', 'shared_folder_name': 'V29yaw'}
        self.assertEqual(parse_credential(data), expected)
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            directory = Path(temp)
            (directory / 'linuxvm.host').write_bytes(data)
            with patch.dict(os.environ, {'CREDENTIALS_DIRECTORY': temp}):
                self.assertEqual(read_credential(), expected)
                (directory / 'linuxvm.host').unlink()
                self.assertEqual(read_credential(), {})

    def test_invalid_credentials(self):
        for data in [b'no-equals', b'timezone=A\ntimezone=B', b'TIMEZONE=A',
                     b'timezone=A\0', b'timezone=\xff', b'timezone=A\tB', b'x' * 65537]:
            with self.subTest(data=data[:40]), self.assertRaises(ValueError):
                parse_credential(data)

    def test_folder_names(self):
        for name in ['Work', 'My Documents', 'A=B', 'Trabalho 🐈', '.hidden', 'x' * 255]:
            self.assertEqual(folder_name(encode_name(name)), name)
        for name in ['', '.', '..', '/tmp', 'a/b', 'a\0b', 'a\nb', 'x' * 256]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                folder_name(encode_name(name))
        for encoded in ['V29yaw==', 'V29yaw+', 'Zh', '_w', 'A', '!', 'V29y aw']:
            with self.subTest(encoded=encoded), self.assertRaises(ValueError):
                folder_name(encoded)


class ZoneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.zones = self.root / 'zoneinfo'
        for name in ['UTC', 'Asia/Tokyo', 'Europe/London', 'Etc/GMT+3']:
            path = self.zones / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'TZif')
        self.state = self.root / 'state/timezone.json'

    def test_validation(self):
        for name in ['UTC', 'Asia/Tokyo', 'Etc/GMT+3']:
            self.assertTrue(zone_path(name, self.zones).is_file())
        for name in ['', '../UTC', '/UTC', 'Etc//GMT+3', 'Etc/./GMT+3', 'UTC\n',
                     'A' * 129, 'UTC;id', 'Missing', None, [], 'America']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                zone_path(name, self.zones)
        (self.root / 'outside').write_bytes(b'TZif')
        (self.zones / 'Escape').symlink_to(self.root / 'outside')
        with self.assertRaises(ValueError):
            zone_path('Escape', self.zones)

    def test_timezone_wire(self):
        self.assertEqual(decode_zone(b'{"type":"timezone","zone":"UTC"}'), 'UTC')
        self.assertIsNone(decode_zone(b'{"type":"wake"}'))
        for value in [b'[]', b'{"type":"wake","zone":"UTC"}', b'{"type":"timezone"}',
                      b'{"type":"timezone","zone":null}']:
            with self.assertRaises(ValueError):
                decode_zone(value)

    def test_follows_and_stops_persistently(self):
        applied = []
        follower = TimeZoneFollower(self.state, self.zones)
        self.assertTrue(follower.synchronize('Asia/Tokyo', 'UTC', applied.append))
        follower = TimeZoneFollower(self.state, self.zones)
        self.assertTrue(follower.synchronize('Europe/London', 'Asia/Tokyo', applied.append))
        self.assertFalse(follower.synchronize('UTC', 'Asia/Tokyo', applied.append))
        self.assertEqual(follower.state['mode'], 'manual')
        restarted = TimeZoneFollower(self.state, self.zones)
        self.assertFalse(restarted.synchronize('UTC', 'Europe/London', applied.append))
        self.assertEqual(applied, ['Asia/Tokyo', 'Europe/London'])

    def test_initial_same_zone_records_and_idle_manual_change(self):
        follower = TimeZoneFollower(self.state, self.zones)
        self.assertFalse(follower.synchronize('UTC', 'UTC', lambda _: self.fail()))
        self.assertTrue(self.state.exists())
        self.assertFalse(follower.observe('Europe/London'))
        self.assertEqual(json.loads(self.state.read_text())['mode'], 'manual')

    def test_failed_apply_does_not_commit(self):
        follower = TimeZoneFollower(self.state, self.zones)
        with self.assertRaises(RuntimeError):
            follower.synchronize('Europe/London', 'UTC', lambda _: (_ for _ in ()).throw(RuntimeError()))
        self.assertFalse(self.state.exists())
        self.state.parent.mkdir(exist_ok=True)
        self.state.write_text('{"mode":"bad"}')
        with self.assertRaises(ValueError):
            TimeZoneFollower(self.state, self.zones)


class ShareTests(unittest.TestCase):
    def test_only_own_links_are_removed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            home = root / 'home'
            home.mkdir()
            mount = root / 'mac'
            mount.mkdir()
            manager = ShareLink(home, root / 'state/links.json', mount)
            manager.update(encode_name('Work'))
            self.assertEqual(os.readlink(home / 'Work'), str(mount))
            manager.update(encode_name('Other'))
            self.assertFalse((home / 'Work').is_symlink())
            self.assertTrue((home / 'Other').is_symlink())
            manager.cleanup()
            self.assertFalse((home / 'Other').is_symlink())
            (home / 'Work').mkdir()
            manager.update(encode_name('Work'))
            self.assertTrue((home / 'Work').is_dir())
            (home / 'File').write_text('keep')
            manager.update(encode_name('File'))
            self.assertEqual((home / 'File').read_text(), 'keep')
            (home / 'Existing').symlink_to(mount)
            manager.update(encode_name('Existing'))
            manager.cleanup()
            self.assertTrue((home / 'Existing').is_symlink())

    def test_replaced_link_and_tag_detection(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            manager = ShareLink(root, root / 'state/links.json', root / 'mac')
            manager.update(encode_name('Work'))
            (root / 'Work').unlink()
            (root / 'Work').write_text('user replacement')
            manager.cleanup()
            self.assertEqual((root / 'Work').read_text(), 'user replacement')
            self.assertFalse(find_share_device(root))
            (root / 'virtio1').mkdir()
            (root / 'virtio1/mount_tag').write_bytes(b'mac\0')
            self.assertTrue(find_share_device(root))

    def test_mount_identity_and_invalid_name_does_not_block_mount(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            mountinfo = root / 'mountinfo'
            mountinfo.write_text('42 1 0:23 / /mnt/mac rw - 9p mac rw\n')
            self.assertTrue(share_is_mounted(Path('/mnt/mac'), mountinfo))
            mountinfo.write_text('42 1 0:23 / /mnt/mac rw - ext4 /dev/vda1 rw\n')
            self.assertFalse(share_is_mounted(Path('/mnt/mac'), mountinfo))
            with (patch.object(guest_share, 'MOUNT', root / 'mac'),
                  patch.object(guest_share, 'RUNTIME', root / 'run/name'),
                  patch.object(guest_share, 'find_share_device', return_value=True),
                  patch.object(guest_share, 'read_credential', return_value={'shared_folder_name': '!!!'}),
                  patch.object(guest_share, 'share_is_mounted', return_value=False),
                  patch.object(guest_share.os.path, 'ismount', return_value=False),
                  patch.object(guest_share.subprocess, 'run') as run):
                guest_share.mount_share()
                command = run.call_args.args[0]
                self.assertEqual(command[:3], ['/usr/bin/mount', '-t', '9p'])
                self.assertIn('trans=virtio,version=9p2000.L,msize=1048576,cache=readahead,nodev,nosuid', command)
                self.assertFalse((root / 'run/name').exists())
            with (patch.object(guest_share, 'RUNTIME', root / 'run/name'),
                  patch.object(guest_share, 'share_is_mounted', return_value=False),
                  patch.object(guest_share.subprocess, 'run') as run):
                guest_share.unmount_share()
                run.assert_not_called()


class AudioTests(unittest.TestCase):
    def test_catalog_validation_and_escaping(self):
        valid = [{'deviceUID': 'a', 'name': 'Speakers "Mac"'}]
        self.assertEqual(PipeWireMirror._validated_devices(valid), valid)
        for records in [None, [{}], valid * 2, [{'deviceUID': 'a', 'name': 'x\nmodule-null-sink'}]]:
            with self.assertRaises(ValueError):
                PipeWireMirror._validated_devices(records)
        self.assertTrue(endpoint_name('output', 'a').startswith('linuxvm_host_output_'))
        self.assertIn('\\"', pulse_proplist(('node.description', 'a"b')))
        self.assertTrue(pulse_module_proplist('sink_properties', 'a="b"').startswith('sink_properties="'))


def parse_ar(data):
    if data[:8] != b'!<arch>\n':
        raise ValueError('invalid ar magic')
    entries = {}
    cursor = 8
    while cursor < len(data):
        header = data[cursor:cursor + 60]
        if len(header) != 60 or header[58:60] != b'`\n':
            raise ValueError('invalid ar header')
        name = header[:16].decode().strip().removesuffix('/')
        size = int(header[48:58])
        self_data = data[cursor + 60:cursor + 60 + size]
        if len(self_data) != size:
            raise ValueError('truncated ar member')
        entries[name] = (header, self_data)
        cursor += 60 + size + size % 2
    if cursor != len(data):
        raise ValueError('invalid ar padding')
    return entries


class PackageTests(unittest.TestCase):
    def test_deb_structure_modes_hashes_and_determinism(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            path = Path(temp) / 'guest.deb'
            first = builder.build(path).read_bytes()
            self.assertEqual(builder.build(path).read_bytes(), first)
        members = parse_ar(first)
        self.assertEqual(list(members), ['debian-binary', 'control.tar.gz', 'data.tar.gz'])
        self.assertEqual(members['debian-binary'][1], b'2.0\n')
        for header, _ in members.values():
            self.assertEqual(int(header[16:28]), builder.EPOCH)
            self.assertEqual(int(header[28:34]), 0)
            self.assertEqual(int(header[34:40]), 0)
            self.assertEqual(int(header[40:48], 8), 0o100644)
        archives = {}
        for name in ['control', 'data']:
            with tarfile.open(fileobj=io.BytesIO(members[f'{name}.tar.gz'][1]), mode='r:gz') as archive:
                records = {}
                for member in archive:
                    self.assertFalse(member.name.startswith('/') or '..' in Path(member.name).parts)
                    self.assertEqual((member.uid, member.gid, member.uname, member.gname), (0, 0, 'root', 'root'))
                    self.assertEqual(member.mtime, builder.EPOCH)
                    executable = name == 'control' and member.name in ('postinst', 'prerm', 'postrm')
                    self.assertEqual(member.mode, 0o755 if member.isdir() or executable else 0o644)
                    records[member.name] = archive.extractfile(member).read() if member.isfile() else None
                archives[name] = records
        fields = dict(line.split(': ', 1) for line in archives['control']['control'].decode().splitlines()
                      if line and not line.startswith(' '))
        self.assertEqual(fields['Package'], 'linuxvm-guest')
        self.assertEqual(fields['Version'], builder.VERSION)
        self.assertEqual(fields['Architecture'], 'all')
        self.assertEqual(fields['Depends'], 'python3, python3-gi, pulseaudio-utils, systemd')
        self.assertEqual(fields['Recommends'], 'wl-clipboard')
        expected = ['usr/lib/linuxvm/' + name + '.py' for name in ['clipboard', 'audio', 'timezone', 'share', 'common', 'clock', 'status', 'version']]
        expected += ['usr/lib/systemd/user/linuxvm-' + name + '.service' for name in ['clipboard', 'audio', 'share-link', 'status']]
        expected += ['usr/lib/systemd/system/linuxvm-' + name + '.service' for name in ['timezone', 'share-mount', 'clock-recovery']]
        expected += ['usr/lib/systemd/system/linuxvm-clock-recovery.timer']
        expected += ['usr/lib/udev/rules.d/70-linuxvm-ports.rules', 'usr/share/libinput/90-linuxvm.quirks',
                     'usr/share/glib-2.0/schemas/90_linuxvm.gschema.override',
                     'usr/share/doc/linuxvm-guest/copyright',
                     'usr/share/gnome-shell/extensions/clipboard@linuxvm.dev/extension.js',
                     'usr/share/gnome-shell/extensions/clipboard@linuxvm.dev/metadata.json']
        self.assertEqual({name for name, data in archives['data'].items() if data is not None}, set(expected))
        for line in archives['control']['md5sums'].decode().splitlines():
            digest, name = line.split('  ', 1)
            self.assertEqual(hashlib.md5(archives['data'][name], usedforsecurity=False).hexdigest(), digest)
        self.assertEqual(len(archives['control']['md5sums'].decode().splitlines()), len(expected))
        self.assertEqual(archives['data']['usr/lib/linuxvm/version.py'], f"VERSION = {builder.VERSION!r}\n".encode())
        # The Mac's touchpad contacts follow the fingers, so GNOME applies natural scrolling itself.
        self.assertIn(b'natural-scroll=true\n', archives['data']['usr/share/glib-2.0/schemas/90_linuxvm.gschema.override'])
        self.assertNotIn('conffiles', archives['control'])  # All configuration lives under /usr.
        self.assertIn(b'Copyright (c) 2026 Try Omarchy contributors', archives['data']['usr/share/doc/linuxvm-guest/copyright'])

    def test_units_and_extension_contract(self):
        for path in (ROOT / 'files/usr/lib/systemd/user').glob('*.service'):
            unit = path.read_text()
            for line in ['WantedBy=graphical-session.target', 'ConditionPathExists=',
                         'Restart=on-failure', 'StartLimitIntervalSec=0']:
                self.assertIn(line, unit)
        for path in (ROOT / 'files/usr/lib/systemd/system').glob('*.service'):
            self.assertIn('WantedBy=multi-user.target', path.read_text())
            self.assertIn('ImportCredential=linuxvm.host', path.read_text())
        extension = ROOT / 'files/usr/share/gnome-shell/extensions/clipboard@linuxvm.dev'
        self.assertEqual(json.loads((extension / 'metadata.json').read_text())['shell-version'], ['50'])
        script = (extension / 'extension.js').read_text()
        for text in ['dev.linuxvm.Clipboard1', '/dev/linuxvm/Clipboard', "'owner-changed'", 'bus_unown_name', '.disconnect(']:
            self.assertIn(text, script)

    @unittest.skipUnless(shutil.which('node'), 'node unavailable')
    def test_extension_javascript_syntax(self):
        for path in (ROOT / 'files/usr/share/gnome-shell/extensions').rglob('*.js'):
            result = subprocess.run(['node', '--input-type=module', '--check'], input=path.read_bytes(), capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_shell_syntax(self):
        for path in [ROOT / 'build-tools-iso.sh', ROOT / 'iso/install.sh',
                     *(ROOT / 'debian' / name for name in ['postinst', 'prerm', 'postrm'])]:
            result = subprocess.run(['sh', '-n', str(path)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == '__main__':
    unittest.main()
