#!/usr/bin/python3
"""Bounded, session-scoped LinuxVM status transport."""
import json
import os
from pathlib import Path
import select
import sys

from common import write_all

PORT = Path('/dev/virtio-ports/dev.linuxvm.status')
UUID = 'clipboard@linuxvm.dev'
LIMIT = 4096


def extension_state(info):
    if not info:
        return 'missing'
    value = info.get('state')
    if hasattr(value, 'unpack'):
        value = value.unpack()
    # GNOME Shell ExtensionState: ENABLED, DISABLED, ERROR, OUT_OF_DATE,
    # DOWNLOADING, INITIALIZED, DEACTIVATING, ACTIVATING, UNINSTALLED.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 'unknown'
    return {1: 'active', 2: 'inactive', 3: 'error', 4: 'outdated',
            99: 'missing'}.get(value, 'unknown')


def encode_status(version, os_name, shell, state):
    import re
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('invalid package version')
    if state not in ('active', 'inactive', 'outdated', 'error', 'missing', 'unknown'):
        raise ValueError('invalid extension state')
    message = {'type': 'status', 'package': version, 'os': str(os_name)[:128], 'extension': state}
    if isinstance(shell, str) and shell:
        message['shell'] = shell[:32]
    data = json.dumps(message, ensure_ascii=False, separators=(',', ':')).encode() + b'\n'
    if len(data) > LIMIT:
        raise ValueError('oversized status')
    return data


def is_query(line):
    if len(line) + 1 > LIMIT:
        return False
    try:
        value = json.loads(line.decode('utf-8'))
        return isinstance(value, dict) and value.get('type') == 'query'
    except (ValueError, UnicodeDecodeError, RecursionError):
        return False


class QueryLines:
    """Discard an entire oversized line, then resume at its newline."""
    def __init__(self):
        self.buffer = bytearray()
        self.dropping = False

    def feed(self, chunk):
        queries = 0
        for byte in chunk:
            if byte == 10:
                if not self.dropping and is_query(bytes(self.buffer)):
                    queries += 1
                self.buffer.clear()
                self.dropping = False
            elif not self.dropping:
                self.buffer.append(byte)
                if len(self.buffer) >= LIMIT:
                    self.buffer.clear()
                    self.dropping = True
        return queries


def os_pretty_name(path=Path('/etc/os-release')):
    # os-release uses shell quoting, but never execute its contents.
    import shlex
    try:
        for line in path.read_text().splitlines():
            if line.startswith('PRETTY_NAME='):
                words = shlex.split(line.partition('=')[2], comments=False)
                return ' '.join(words)[:128]
    except (OSError, ValueError):
        pass
    return ''


def main():
    from gi.repository import Gio, GLib
    from version import VERSION
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    shell = Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.DO_NOT_AUTO_START,
                                  None, 'org.gnome.Shell', '/org/gnome/Shell', 'org.gnome.Shell', None)
    extensions = Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.DO_NOT_AUTO_START,
                                       None, 'org.gnome.Shell', '/org/gnome/Shell',
                                       'org.gnome.Shell.Extensions', None)
    pending = True

    def changed(_proxy, _sender, signal, parameters):
        nonlocal pending
        if signal == 'ExtensionStateChanged' and parameters.unpack()[0] == UUID:
            pending = True

    def owner_changed(*_args):
        nonlocal pending
        pending = True

    extensions.connect('g-signal', changed)
    shell.connect('notify::g-name-owner', owner_changed)
    context = GLib.MainContext.default()
    os_name = os_pretty_name()

    def report(fd):
        state, shell_version = 'unknown', None
        if shell.get_name_owner():
            try:
                value = shell.get_cached_property('ShellVersion')
                shell_version = value.unpack() if value else None
                info = extensions.call_sync('GetExtensionInfo', GLib.Variant('(s)', (UUID,)),
                                            Gio.DBusCallFlags.NO_AUTO_START, 5000, None).unpack()[0]
                state = extension_state(info)
            except GLib.Error:
                pass
        write_all(fd, encode_status(VERSION, os_name, shell_version, state))

    with PORT.open('r+b', buffering=0) as port:
        fd = port.fileno()
        lines = QueryLines()
        while True:
            while context.pending():
                context.iteration(False)
            if pending:
                pending = False
                report(fd)
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                chunk = os.read(fd, LIMIT)
                if not chunk:
                    raise RuntimeError('host status port disconnected')
                for _ in range(lines.feed(chunk)):
                    report(fd)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'linuxvm-status: {error}', file=sys.stderr, flush=True)
        raise SystemExit(1)
