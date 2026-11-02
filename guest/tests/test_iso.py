import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ISO = ROOT / 'dist/guest-tools.iso'
spec = importlib.util.spec_from_file_location('iso_builder', ROOT / 'build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@unittest.skipUnless(ISO.exists(), 'build the ISO first to check its contents')
class ISOTests(unittest.TestCase):
    def test_label_contents_and_normalization(self):
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
            for position in (813, 830, 864):
                self.assertEqual(image[offset + position:offset + position + 17], b'2000010100000000\0')
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
                name = record[33:33 + record[32]]
                # No host uid/gid, birth times, or partial Rock Ridge metadata remains.
                base = 33 + record[32]
                self.assertEqual(length, base + base % 2)
                if not record[25] & 2:
                    name = name.decode(encoding).removesuffix(';1')
                    start = int.from_bytes(record[2:6], 'little') * 2048
                    size = int.from_bytes(record[10:14], 'little')
                    files[name] = image[start:start + size]
                cursor += length
            self.assertEqual(len(files), 3)
            if kind == 2:
                self.assertEqual(set(files), {builder.DEB, 'install.sh', 'README.txt'})
                self.assertEqual(files[builder.DEB], (ROOT / 'dist' / builder.DEB).read_bytes())
                self.assertEqual(files['install.sh'], (ROOT / 'iso/install.sh').read_bytes())
                self.assertEqual(files['README.txt'], (ROOT / 'iso/README.txt').read_bytes())
        self.assertEqual(trees, 2)
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            path = Path(temp) / 'copy.iso'
            path.write_bytes(image)
            builder.normalize_iso(path)
            self.assertEqual(path.read_bytes(), image)
