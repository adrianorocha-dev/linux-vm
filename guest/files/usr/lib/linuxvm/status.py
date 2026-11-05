#!/usr/bin/python3
"""Bounded, session-scoped LinuxVM status transport."""
import json
import os
from pathlib import Path
import select
import sys
import subprocess
from functools import lru_cache
from clipboard import desktop_entries, state_path

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


def encode_status(version, os_name, shell, state, desktop="GNOME", desktop_version=None, clipboard=None):
    import re
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('invalid package version')
    if state not in ('active', 'inactive', 'outdated', 'error', 'missing', 'unknown'):
        raise ValueError('invalid extension state')
    message = {'type': 'status', 'package': version, 'os': str(os_name)[:128], 'extension': state}
    if desktop == 'GNOME':
        clipboard = {'missing': 'pending'}.get(state, state)
        desktop_version = shell
        if isinstance(shell, str) and shell:
            message['shell'] = shell[:32]
    else:
        message['extension'] = 'unknown'
    if desktop:
        message['desktop'] = clean_desktop(desktop)
    if isinstance(desktop_version, str) and desktop_version:
        message['desktopVersion'] = clean_desktop(desktop_version)
    allowed = ('active', 'inactive', 'outdated', 'pending', 'unsupported', 'error', 'unknown')
    message['clipboard'] = clipboard if clipboard in allowed else 'unknown'
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


def clean_desktop(value):
    return ''.join(c for c in value if c.isprintable())[:32]


def session_desktop():
    entries = desktop_entries()
    return next((name for name in ('GNOME', 'KDE') if name in entries),
                clean_desktop(entries[0]) if entries else '')


@lru_cache(maxsize=1)
def plasma_version():
    import re
    try:
        # KWin ships with each Plasma release. plasmashell --version is not safe to
        # run: on Plasma 6.6.6 it segfaults even offscreen, and KDE records a crash.
        result = subprocess.run(['kwin_wayland', '--version'], capture_output=True,
                                env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                                timeout=5, check=True, text=True)
        match = re.fullmatch(r'kwin\s+([0-9]+(?:\.[0-9]+)+)\s*', result.stdout)
        return match[1][:32] if match else None
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None


def clipboard_state():
    try:
        with state_path().open('rb') as stream:
            data = stream.read(LIMIT + 1)
        if len(data) > LIMIT:
            return 'unknown'
        value = json.loads(data)
        if (isinstance(value, dict) and value.get('backend') in ('data-control', 'gnome-extension')
                and value.get('state') in ('active', 'unsupported', 'error')
                and isinstance(value.get('protocol'), str)):
            return value['state']
    except (OSError, KeyError, ValueError, RecursionError):
        pass
    return 'unknown'


def clipboard_stamp():
    try:
        stat = state_path().stat()
        return stat.st_mtime_ns, stat.st_ino
    except (OSError, KeyError):
        return None


def other_main():
    from version import VERSION
    desktop = session_desktop()
    version = plasma_version() if desktop == 'KDE' else None
    os_name = os_pretty_name()
    with PORT.open('r+b', buffering=0) as port:
        fd, lines = port.fileno(), QueryLines()
        def report():
            write_all(fd, encode_status(VERSION, os_name, None, 'unknown', desktop,
                                        version, clipboard_state()))
        stamp = clipboard_stamp()
        report()
        while True:
            ready, _, _ = select.select([fd], [], [], 1)
            current = clipboard_stamp()
            if current != stamp:
                stamp = current
                report()
            if ready:
                chunk = os.read(fd, LIMIT)
                if not chunk:
                    raise RuntimeError('host status port disconnected')
                for _ in range(lines.feed(chunk)):
                    report()


def main():
    if session_desktop() != 'GNOME':
        return other_main()
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
                info = extensions.call_sync('GetExtensionInfo', GLib.Variant('(s)', (UUID,)),
                                            Gio.DBusCallFlags.NO_AUTO_START, 5000, None).unpack()[0]
                state = extension_state(info)
            except GLib.Error:
                pass
            # Ask each time: the proxy loads properties once, and at login
            # that can precede GNOME Shell exporting them.
            try:
                value = bus.call_sync('org.gnome.Shell', '/org/gnome/Shell', 'org.freedesktop.DBus.Properties',
                                      'Get', GLib.Variant('(ss)', ('org.gnome.Shell', 'ShellVersion')),
                                      GLib.VariantType('(v)'), Gio.DBusCallFlags.NO_AUTO_START, 5000, None)
                shell_version = value.unpack()[0]
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
