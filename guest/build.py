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
VERSION = '0.2.2'
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
    version_data = f'VERSION = {VERSION!r}\n'.encode()
    data_entries['usr/lib/linuxvm/version.py'] = (version_data, 0o644)
    md5.append(f'{hashlib.md5(version_data, usedforsecurity=False).hexdigest()}  usr/lib/linuxvm/version.py\n')
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
    stage.chmod(0o755)
    for source in [ROOT / 'dist' / DEB, ROOT / 'iso/install.sh', ROOT / 'iso/README.txt']:
        target = stage / source.name
        shutil.copyfile(source, target)
        target.chmod(0o755 if source.name == 'install.sh' else 0o644)
        os.utime(target, (EPOCH, EPOCH))
    os.utime(stage, (EPOCH, EPOCH))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-iso', type=Path)
    args = parser.parse_args()
    if args.stage_iso:
        stage_iso(args.stage_iso)
    else:
        print(build())
