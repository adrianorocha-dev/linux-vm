"""Bounded host settings and wire input shared by the guest agents."""
import base64
import json
import os
from pathlib import Path
import re
import tempfile

CREDENTIAL_LIMIT = 65536


def parse_credential(data: bytes) -> dict[str, str]:
    if len(data) > CREDENTIAL_LIMIT or b'\0' in data:
        raise ValueError('invalid credential size or NUL')
    result = {}
    for line in data.decode('utf-8').splitlines():
        if not line:
            continue
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[a-z_]+', key) or key in result:
            raise ValueError('malformed or duplicate credential key')
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('control character in credential')
        result[key] = value
    return result


def read_credential() -> dict[str, str]:
    directory = os.environ.get('CREDENTIALS_DIRECTORY')
    if not directory:
        return {}
    try:
        with (Path(directory) / 'linuxvm.host').open('rb') as stream:
            return parse_credential(stream.read(CREDENTIAL_LIMIT + 1))
    except FileNotFoundError:
        return {}


def folder_name(encoded: str) -> str:
    if not isinstance(encoded, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,340}', encoded):
        raise ValueError('invalid shared folder encoding')
    raw = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
    if base64.urlsafe_b64encode(raw).decode().rstrip('=') != encoded:
        raise ValueError('noncanonical shared folder encoding')
    name = raw.decode('utf-8')
    if (not name or len(raw) > 255 or name in ('.', '..') or '/' in name
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise ValueError('invalid shared folder name')
    return name


def zone_path(zone: str, zoneinfo: Path = Path('/usr/share/zoneinfo')) -> Path:
    # Same grammar and containment check as Try Omarchy's timezone agent.
    if (not isinstance(zone, str) or not 0 < len(zone) <= 128
            or not re.fullmatch(r'[A-Za-z0-9_+/-]+', zone)
            or any(part in ('', '.', '..') for part in zone.split('/'))):
        raise ValueError('invalid host time zone')
    path = zoneinfo / zone
    if not path.is_file() or not path.resolve().is_relative_to(zoneinfo.resolve()):
        raise ValueError('host time zone is unavailable in the guest')
    return path


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), mode)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_json(path: Path, data: dict, mode: int = 0o600) -> None:
    atomic_write(path, (json.dumps(data, sort_keys=True) + '\n').encode(), mode)


def write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        count = os.write(fd, data[offset:])
        if count <= 0:
            raise RuntimeError('host port disconnected during write')
        offset += count


class Lines:
    def __init__(self, limit: int):
        self.limit = limit
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        self.buffer.extend(chunk)
        result = []
        while b'\n' in self.buffer:
            line, _, rest = self.buffer.partition(b'\n')
            if len(line) > self.limit:
                raise ValueError('host line exceeds size limit')
            result.append(bytes(line))
            self.buffer = bytearray(rest)
        if len(self.buffer) > self.limit:
            raise ValueError('host line exceeds size limit')
        return result
