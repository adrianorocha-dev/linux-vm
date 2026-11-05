import importlib.util
from pathlib import Path
import stat
import unittest

ROOT = Path(__file__).resolve().parents[1]
ISO = ROOT / 'dist/guest-tools.iso'
spec = importlib.util.spec_from_file_location('iso_builder', ROOT / 'build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@unittest.skipUnless(ISO.exists(), 'build the ISO first to check its contents')
class ISOTests(unittest.TestCase):
    def test_rock_ridge_joliet_modes_names_and_contents(self):
        image = ISO.read_bytes()
        trees = 0
        for offset in range(16 * 2048, len(image), 2048):
            self.assertEqual(image[offset + 1:offset + 6], b'CD001')
            kind = image[offset]
            if kind == 255:
                break
            if kind not in (1, 2):
                continue
            trees += 1
            encoding = 'utf-16-be' if kind == 2 else 'ascii'
            self.assertEqual(image[offset + 40:offset + 72].decode(encoding).strip(), 'LINUXVM-TOOLS')
            self.assertEqual(image[offset + 813:offset + 830], b'2000010100000000\0')
            root = image[offset + 156:offset + 190]
            cursor = int.from_bytes(root[2:6], 'little') * 2048
            end = cursor + int.from_bytes(root[10:14], 'little')
            files = {}
            while cursor < end:
                length = image[cursor]
                if not length:
                    cursor = (cursor // 2048 + 1) * 2048
                    continue
                record = image[cursor:cursor + length]
                self.assertEqual(record[18:25], bytes([100, 1, 1, 0, 0, 0, 0]))
                raw_name = record[33:33 + record[32]]
                base = 33 + record[32]
                base += base % 2
                fields = {}
                while base + 4 <= length:
                    size = record[base + 2]
                    if size < 4:
                        break
                    fields[record[base:base + 2]] = record[base:base + size]
                    base += size
                if kind == 1:
                    px = fields[b'PX']
                    mode = int.from_bytes(px[4:8], 'little')
                    self.assertEqual(int.from_bytes(px[20:24], 'little'), 0)
                    self.assertEqual(int.from_bytes(px[28:32], 'little'), 0)
                    expected = 0o755 if record[25] & 2 or fields.get(b'NM', b'')[5:] == b'install.sh' else 0o644
                    self.assertEqual(stat.S_IMODE(mode), expected)
                if not record[25] & 2:
                    name = (fields[b'NM'][5:].decode() if kind == 1 else
                            raw_name.decode(encoding).removesuffix(';1'))
                    start = int.from_bytes(record[2:6], 'little') * 2048
                    size = int.from_bytes(record[10:14], 'little')
                    files[name] = image[start:start + size]
                cursor += length
            self.assertEqual(set(files), {builder.DEB, builder.RPM, 'install.sh', 'README.txt'})
            self.assertEqual(files[builder.DEB], (ROOT / 'dist' / builder.DEB).read_bytes())
            self.assertEqual(files[builder.RPM], (ROOT / 'dist' / builder.RPM).read_bytes())
            for name in ['install.sh', 'README.txt']:
                self.assertEqual(files[name], (ROOT / 'iso' / name).read_bytes())
        self.assertEqual(trees, 2)
