#!/usr/bin/env python3
"""Deterministic Debian/ar and RPM v4 builder and ISO staging, using only the stdlib."""
import argparse
import gzip
import hashlib
import io
import os
from pathlib import Path
import shutil
import stat
import struct
import tarfile

ROOT = Path(__file__).resolve().parent
VERSION = '0.3.0'
DEB = f'linuxvm-guest_{VERSION}_all.deb'
RPM = f'linuxvm-guest-{VERSION}-1.noarch.rpm'
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


def collect_entries() -> dict[str, tuple[bytes | None, int]]:
    data_entries = {}
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
    version_data = f'VERSION = {VERSION!r}\n'.encode()
    data_entries['usr/lib/linuxvm/version.py'] = (version_data, 0o644)
    return data_entries


def build(destination: Path | None = None, entries=None) -> Path:
    destination = destination or ROOT / "dist" / DEB
    data_entries = collect_entries() if entries is None else entries
    md5 = [f"{hashlib.md5(data, usedforsecurity=False).hexdigest()}  {name}\n"
           for name, (data, _) in sorted(data_entries.items()) if data is not None]
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


# RPM tag numbers/types follow rpm 4.20 include/rpm/rpmtag.h. The manual's
# signature table has a typo for SHA256: the source defines it as 273.
# https://rpm.org/docs/4.20.x/manual/format_v4.html
# https://rpm.org/docs/4.20.x/manual/format_header.html
# GNOME Shell's folders are shared: on a KDE system without gnome-shell, nothing
# else owns them, and RPM would leave them behind on removal.
RPM_DIRECTORIES = {'usr/lib/linuxvm',
                   'usr/share/gnome-shell', 'usr/share/gnome-shell/extensions',
                   'usr/share/gnome-shell/extensions/clipboard@linuxvm.dev',
                   'usr/share/doc/linuxvm-guest'}


def rpm_header(tags, region):
    """Serialize one immutable region, including its negative index-size trailer."""
    store = bytearray()
    indexes = []
    for tag, (kind, value) in sorted(tags.items()):
        if kind in (3, 4, 5):
            alignment, code = {3: (2, 'H'), 4: (4, 'I'), 5: (8, 'Q')}[kind]
            store.extend(b'\0' * (-len(store) % alignment))
            values = value if isinstance(value, list) else [value]
            encoded = struct.pack('>' + code * len(values), *values)
            count = len(values)
        elif kind == 7:
            encoded, count = value, len(value)
        else:
            values = [value] if kind == 6 else value
            encoded = b''.join(v.encode() + b'\0' for v in values)
            count = len(values)
        indexes.append(struct.pack('>IIII', tag, kind, len(store), count))
        store.extend(encoded)
    count = len(indexes) + 1
    region_index = struct.pack('>IIII', region, 7, len(store), 16)
    store.extend(struct.pack('>IIiI', region, 7, -16 * count, 16))
    return (b'\x8e\xad\xe8\x01\0\0\0\0' + struct.pack('>II', count, len(store))
            + region_index + b''.join(indexes) + store)


def cpio_newc(entries):
    archive = bytearray()
    for inode, (name, (data, mode)) in enumerate([*sorted(entries.items()),
                                               ('TRAILER!!!', (b'', 0))], 1):
        trailer = name == 'TRAILER!!!'
        filename = (name if trailer else './' + name).encode() + b'\0'
        content = data or b''
        filemode = 0 if trailer else mode | (stat.S_IFDIR if data is None else stat.S_IFREG)
        fields = [inode, filemode, 0, 0, 2 if data is None else 1, EPOCH,
                  len(content), 0, 0, 0, 0, len(filename), 0]
        archive.extend(b'070701' + ''.join(f'{v:08x}' for v in fields).encode() + filename)
        archive.extend(b'\0' * (-len(archive) % 4))
        archive.extend(content)
        archive.extend(b'\0' * (-len(archive) % 4))
    return bytes(archive)


def build_rpm(destination: Path | None = None, entries=None) -> Path:
    entries = collect_entries() if entries is None else entries
    entries = {name: value for name, value in entries.items()
               if value[0] is not None or name in RPM_DIRECTORIES}
    names = sorted(entries)
    values = [entries[name][0] for name in names]
    modes = [entries[name][1] | (stat.S_IFDIR if entries[name][0] is None else stat.S_IFREG)
             for name in names]
    raw = cpio_newc(entries)
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, mode='wb', filename='', mtime=EPOCH, compresslevel=9) as f:
        f.write(raw)
    payload = stream.getvalue()
    dirs = sorted({'/' + name.rsplit('/', 1)[0] + '/' for name in names})
    n = len(names)
    requires = [(name, '', 0) for name in
                ['python3', 'python3-gobject-base', 'pulseaudio-utils', 'systemd']]
    requires += [('/bin/sh', '', (1 << 8) | (1 << flag)) for flag in (9, 10, 11, 12)]
    requires += [('rpmlib(' + name + ')', version, (1 << 24) | 2 | 8)
                 for name, version in [('CompressedFileNames', '3.0.4-1'),
                                       ('PayloadFilesHavePrefix', '4.0-1'),
                                       ('FileDigests', '4.6.0-1')]]
    tags = {
        100: (8, ['C']), 1000: (6, 'linuxvm-guest'), 1001: (6, VERSION), 1002: (6, '1'),
        1004: (9, ['Desktop integration for Linux VM on macOS']),
        1005: (9, ['Clipboard, audio endpoints, host time zone, shared folder and touchpad defaults.']),
        1006: (4, EPOCH), 1007: (6, 'linuxvm-builder'),
        1009: (4, sum(len(v) for v in values if v is not None)),
        1014: (6, 'MIT'), 1016: (9, ['System Environment/Daemons']),
        1020: (6, 'https://github.com/adrianorocha-dev/linux-vm'),
        1021: (6, 'linux'), 1022: (6, 'noarch'),
        1028: (4, [len(v) if v is not None else 0 for v in values]),
        1030: (3, modes), 1033: (3, [0] * n), 1034: (4, [EPOCH] * n),
        1035: (8, [hashlib.sha256(v).hexdigest() if v is not None else '' for v in values]),
        1036: (8, [''] * n),
        1037: (4, [2 if name.endswith('/copyright') else 0 for name in names]),  # RPMFILE_DOC
        1039: (8, ['root'] * n), 1040: (8, ['root'] * n),
        1045: (4, [0xff] * n),
        1047: (8, ['linuxvm-guest']), 1112: (4, [8]), 1113: (8, [VERSION + '-1']),
        1048: (4, [r[2] for r in requires]), 1049: (8, [r[0] for r in requires]),
        1050: (8, [r[1] for r in requires]),
        1095: (4, [0] * n), 1096: (4, list(range(1, n + 1))), 1097: (8, [''] * n),
        1116: (4, [dirs.index('/' + name.rsplit('/', 1)[0] + '/') for name in names]),
        1117: (8, [name.rsplit('/', 1)[1] for name in names]), 1118: (8, dirs),
        1124: (6, 'cpio'), 1125: (6, 'gzip'), 1126: (6, '9'), 1132: (6, 'noarch'),
        5011: (4, 8),
        5092: (8, [hashlib.sha256(payload).hexdigest()]), 5093: (4, 8),
        5097: (8, [hashlib.sha256(raw).hexdigest()]),
    }
    for tag, name in enumerate(('pre', 'post', 'preun', 'postun'), 1023):
        tags[tag] = (6, (ROOT / 'rpm' / name).read_text())
        tags[tag + 62] = (8, ['/bin/sh'])
    header = rpm_header(tags, 63)
    # Retain legacy MD5/SHA1 for v4 compatibility, in addition to modern SHA256.
    signature = rpm_header({269: (6, hashlib.sha1(header, usedforsecurity=False).hexdigest()),
                            273: (6, hashlib.sha256(header).hexdigest()),
                            1000: (4, len(header) + len(payload)),
                            1004: (7, hashlib.md5(header + payload, usedforsecurity=False).digest()),
                            1007: (4, len(raw))}, 62)
    lead = struct.pack('>4sBBHH66sHH16s', b'\xed\xab\xee\xdb', 3, 0, 0, 0,
                       f'linuxvm-guest-{VERSION}-1'.encode(), 1, 5, b'')
    destination = destination or ROOT / 'dist' / RPM
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(lead + signature + b'\0' * (-len(signature) % 8) + header + payload)
    destination.chmod(0o644)
    os.utime(destination, (EPOCH, EPOCH))
    return destination


def stage_iso(stage: Path) -> None:
    stage.mkdir(parents=True, exist_ok=True)
    stage.chmod(0o755)
    for source in [ROOT / 'dist' / DEB, ROOT / 'dist' / RPM, ROOT / 'iso/install.sh', ROOT / 'iso/README.txt']:
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
        entries = collect_entries()
        print(build(entries=entries))
        print(build_rpm(entries=entries))
