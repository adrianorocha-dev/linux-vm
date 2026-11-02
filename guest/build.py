#!/usr/bin/env python3
"""Deterministic Debian/ar builder and ISO staging, using only the stdlib."""
import argparse
import gzip
import hashlib
import io
import os
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parent
VERSION = '0.1.0'
DEB = f'linuxvm-guest_{VERSION}_all.deb'
EPOCH = 946684800  # 2000-01-01 UTC, also representable by ISO9660.


def tar_gz(entries: dict[str, tuple[bytes | None, int]]) -> bytes:
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, mode='wb', filename='', mtime=EPOCH, compresslevel=9) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name, (data, mode) in sorted(entries.items()):
                info = tarfile.TarInfo(name)
                info.uid = info.gid = 0
                info.uname = info.gname = 'root'
                info.mtime = EPOCH
                info.mode = mode
                if data is None:
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                else:
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def ar_member(name: str, data: bytes) -> bytes:
    header = (f'{name + "/":<16}{EPOCH:<12}{0:<6}{0:<6}{"100644":<8}{len(data):<10}`\n').encode('ascii')
    assert len(header) == 60
    return header + data + (b'\n' if len(data) % 2 else b'')


def build(destination: Path | None = None) -> Path:
    destination = destination or ROOT / 'dist' / DEB
    data_entries = {}
    md5 = []
    for path in sorted((ROOT / 'files').rglob('*')):
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        name = path.relative_to(ROOT / 'files').as_posix()
        if path.is_symlink():
            raise ValueError(f'unexpected source symlink: {name}')
        if path.is_dir():
            data_entries[name] = (None, 0o755)
        elif path.is_file():
            data = path.read_bytes()
            data_entries[name] = (data, 0o644)
            md5.append(f'{hashlib.md5(data, usedforsecurity=False).hexdigest()}  {name}\n')
    control_entries = {'md5sums': (''.join(md5).encode(), 0o644)}
    for path in sorted((ROOT / 'debian').iterdir()):
        control_entries[path.name] = (path.read_bytes(), 0o644 if path.name == 'control' else 0o755)
    payload = b'!<arch>\n'
    for name, data in [('debian-binary', b'2.0\n'), ('control.tar.gz', tar_gz(control_entries)),
                       ('data.tar.gz', tar_gz(data_entries))]:
        payload += ar_member(name, data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    destination.chmod(0o644)
    os.utime(destination, (EPOCH, EPOCH))
    return destination


def stage_iso(stage: Path) -> None:
    stage.mkdir(parents=True, exist_ok=True)
    for source in [ROOT / 'dist' / DEB, ROOT / 'iso/install.sh', ROOT / 'iso/README.txt']:
        target = stage / source.name
        shutil.copyfile(source, target)
        target.chmod(0o755 if source.name == 'install.sh' else 0o644)
        os.utime(target, (EPOCH, EPOCH))
    os.utime(stage, (EPOCH, EPOCH))


def normalize_iso(path: Path) -> None:
    # makehybrid embeds wall-clock/birth times even with fixed source mtimes.
    # Normalize dates and discard makehybrid POSIX metadata (host uid/gid and
    # creation times). With no partial Rock Ridge tree, Linux uses Joliet names.
    image = bytearray(path.read_bytes())
    short_date = bytes([100, 1, 1, 0, 0, 0, 0])
    long_date = b'2000010100000000\0'
    seen = set()

    def directory(offset, size):
        key = (offset, size)
        if key in seen:
            return
        seen.add(key)
        cursor = offset
        records = []
        while cursor < offset + size:
            length = image[cursor]
            if length == 0:
                cursor = (cursor // 2048 + 1) * 2048
                continue
            if length < 34 or cursor + length > offset + size:
                raise ValueError('malformed ISO directory')
            record = bytearray(image[cursor:cursor + length])
            record[18:25] = short_date
            if record[25] & 2 and record[33:33 + record[32]] not in (b'\0', b'\1'):
                directory(int.from_bytes(record[2:6], 'little') * 2048,
                          int.from_bytes(record[10:14], 'little'))
            base_length = 33 + record[32]
            base_length += base_length % 2
            record = record[:base_length]
            record[0] = base_length
            records.append(record)
            cursor += length
        packed = bytearray()
        for record in records:
            if len(packed) % 2048 + len(record) > 2048:
                packed.extend(b'\0' * (-len(packed) % 2048))
            packed.extend(record)
        if len(packed) > size:
            raise ValueError('normalized ISO directory exceeds its extent')
        image[offset:offset + size] = packed + b'\0' * (size - len(packed))

    for offset in range(16 * 2048, len(image), 2048):
        if image[offset + 1:offset + 6] != b'CD001':
            raise ValueError('invalid ISO descriptor')
        kind = image[offset]
        if kind == 255:
            break
        if kind not in (1, 2):
            continue
        # makehybrid replaces '-' with '_' in the primary identifier. Keep the
        # contract's exact disc label in both descriptors for Linux/blkid too.
        label = 'LINUXVM-TOOLS'.ljust(16 if kind == 2 else 32)
        image[offset + 40:offset + 72] = label.encode('utf-16-be' if kind == 2 else 'ascii')
        for position in (813, 830, 864):
            image[offset + position:offset + position + 17] = long_date
        image[offset + 847:offset + 864] = b'0' * 16 + b'\0'
        image[offset + 174:offset + 181] = short_date
        record = image[offset + 156:offset + 190]
        directory(int.from_bytes(record[2:6], 'little') * 2048,
                  int.from_bytes(record[10:14], 'little'))
    else:
        raise ValueError('missing ISO descriptor terminator')
    path.write_bytes(image)
    os.utime(path, (EPOCH, EPOCH))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--stage-iso', type=Path)
    group.add_argument('--normalize-iso', type=Path)
    args = parser.parse_args()
    if args.stage_iso:
        stage_iso(args.stage_iso)
    elif args.normalize_iso:
        normalize_iso(args.normalize_iso)
    else:
        print(build())
