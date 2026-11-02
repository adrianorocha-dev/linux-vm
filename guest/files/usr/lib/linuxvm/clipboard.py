#!/usr/bin/python3
"""GNOME clipboard transport, adapted from Try Omarchy (MIT)."""
from __future__ import annotations
import base64
import hashlib
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PORT = Path('/dev/virtio-ports/dev.linuxvm.clipboard')
TEXT_FORMAT = 'text/plain;charset=utf-8'
PNG_FORMAT = 'image/png'
FORMATS = (TEXT_FORMAT, PNG_FORMAT)
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_LINE_BYTES = MAX_PAYLOAD_BYTES * 4 // 3 + 4096
ECHO_WINDOW_SECONDS = 2.0
NAME = 'dev.linuxvm.Clipboard'
OBJECT = '/dev/linuxvm/Clipboard'
INTERFACE = 'dev.linuxvm.Clipboard1'
UUID = 'clipboard@linuxvm.dev'

def fingerprint(mime: str, payload: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(mime.encode())
    digest.update(b"\0")
    digest.update(payload)
    return digest.hexdigest()


def encode_message(mime: str, payload: bytes) -> bytes:
    message = {
        "type": "clipboard",
        "format": mime,
        "data": base64.b64encode(payload).decode("ascii"),
    }
    return json.dumps(message, separators=(",", ":"), sort_keys=True).encode() + b"\n"


def decode_message(line: bytes) -> tuple[str, bytes] | None:
    """Return (mime, payload) for a host clipboard line, or None to ignore."""
    message = json.loads(line)
    if not isinstance(message, dict) or message.get("type") != "clipboard":
        raise ValueError("host sent an invalid clipboard message")
    if set(message) != {"type", "format", "data"}:
        raise ValueError("host clipboard message has an unexpected schema")
    mime = message["format"]
    data = message["data"]
    if mime not in FORMATS or not isinstance(data, str):
        return None
    try:
        payload = base64.b64decode(data, validate=True)
    except ValueError as error:
        raise ValueError("host clipboard payload is not base64") from error
    if not payload or len(payload) > MAX_PAYLOAD_BYTES:
        return None
    if mime == TEXT_FORMAT:
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return mime, payload


class ClipboardSync:
    """Echo-safe two-way state shared by the tests and the live agent.

    A marker only protects content that is still on the other side's
    clipboard. Accepting a new change in one direction therefore clears the
    other direction's marker: after guest copies B and Mac copies A, the Mac
    pasteboard no longer holds B, so a later Mac copy of B is new content and
    must not be mistaken for the original echo. Echoes are delivered in order
    before any later user copy, so clearing cannot let one through. A short
    expiry backs this up for markers that never see an opposite change.
    """

    def __init__(self, send: Any, copy: Any, clock: Any = time.monotonic) -> None:
        self.send = send
        self.copy = copy
        self.clock = clock
        self.last_from_host: tuple[str, float] | None = None
        self.last_from_guest: tuple[str, float] | None = None

    @staticmethod
    def _is_echo(marker: tuple[str, float] | None, key: str, now: float) -> bool:
        return marker is not None and marker[0] == key and now - marker[1] <= ECHO_WINDOW_SECONDS

    def guest_changed(self, mime: str, payload: bytes) -> bool:
        """Forward a new guest selection to the host. Returns True if sent."""
        if mime not in FORMATS or not payload or len(payload) > MAX_PAYLOAD_BYTES:
            return False
        key = fingerprint(mime, payload)
        now = self.clock()
        # The extension re-announces whatever the host just wrote; only that echo
        # is dropped. A repeat of earlier guest content is a real change.
        if self._is_echo(self.last_from_host, key, now):
            return False
        self.last_from_guest = (key, now)
        self.last_from_host = None
        self.send(encode_message(mime, payload))
        return True

    def host_changed(self, mime: str, payload: bytes) -> bool:
        """Apply a host pasteboard update to the guest. Returns True if applied."""
        key = fingerprint(mime, payload)
        now = self.clock()
        if self._is_echo(self.last_from_guest, key, now):
            return False
        self.last_from_host = (key, now)
        self.last_from_guest = None
        self.copy(mime, payload)
        return True


def main() -> int:
    from gi.repository import Gio, GLib
    from common import Lines, write_all

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    proxy = Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.DO_NOT_AUTO_START,
                                  None, NAME, OBJECT, INTERFACE, None)
    context = GLib.MainContext.default()
    pending = False
    last_owner = None
    last_enable = 0.0

    def copy(mime, payload):
        proxy.call_sync('SetSelection', GLib.Variant('(say)', (mime, payload)),
                        Gio.DBusCallFlags.NO_AUTO_START, 15000, None)

    with PORT.open('r+b', buffering=0) as port:
        fd = port.fileno()
        sync = ClipboardSync(lambda data: write_all(fd, data), copy)
        lines = Lines(MAX_LINE_BYTES)

        def changed(_proxy, _sender, signal, _parameters):
            nonlocal pending
            if signal == 'Changed':
                pending = True

        proxy.connect('g-signal', changed)
        while True:
            while context.pending():
                context.iteration(False)
            owner = proxy.get_name_owner()
            if owner != last_owner:
                last_owner = owner
                pending = False
                if owner:
                    sync = ClipboardSync(lambda data: write_all(fd, data), copy)
                    write_all(fd, b'{"type":"sync"}\n')
            if not owner and time.monotonic() - last_enable >= 15:
                last_enable = time.monotonic()
                # Installation requires a fresh Shell session before the UUID is known.
                settings = Gio.Settings.new('org.gnome.shell')
                if UUID not in settings.get_strv('enabled-extensions'):
                    subprocess.run(['gnome-extensions', 'enable', UUID],
                                   capture_output=True, timeout=10, check=False)
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    raise RuntimeError('host clipboard bridge disconnected')
                for line in lines.feed(chunk):
                    decoded = decode_message(line)
                    if decoded is not None and owner:
                        sync.host_changed(*decoded)
            if pending and owner:
                pending = False
                try:
                    result = proxy.call_sync('GetSelection', None,
                                             Gio.DBusCallFlags.NO_AUTO_START, 15000, None)
                    mime, data = result.unpack()
                    payload = bytes(data)
                    if mime == TEXT_FORMAT:
                        payload.decode('utf-8')
                    sync.guest_changed(mime, payload)
                except GLib.Error as error:
                    print(f'clipboard read: {error}', file=sys.stderr)
                except UnicodeDecodeError:
                    pass


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f'linuxvm-clipboard: {error}', file=sys.stderr, flush=True)
        raise SystemExit(1)
