"""A real wire/SCM_RIGHTS peer; runs without a Wayland installation."""
import array
import json
import os
from pathlib import Path
import select
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'files/usr/lib/linuxvm'))
import clipboard as agent
import status
from wayland_clipboard import Clipboard, Unsupported, MANAGERS, TEXT, PNG, uint, string, get_string


class Compositor:
    def __init__(self, managers=MANAGERS):
        self.client, self.sock = socket.socketpair()
        self.managers = managers
        self.buffer = bytearray()
        self.fds = []
        self.binds, self.sources, self.offers = [], {}, {}
        self.lock = threading.Lock()
        self.device = self.source = None
        self.offer_id = 0xff000000
        self.errors = []
        self.stop = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def event(self, obj, opcode, body=b'', fd=None):
        with self.lock:
            self.sock.sendmsg([uint(obj, (len(body) + 8) << 16 | opcode) + body],
                              [] if fd is None else [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd]))])

    def selection(self, types, source=None):
        self.offer_id += 1
        offer = self.offer_id
        self.offers[offer] = (types, source)
        self.event(self.device, 0, uint(offer))
        for mime in types:
            self.event(offer, 0, string(mime))
        self.event(self.device, 1, uint(offer))
        return offer

    def request(self, obj, op, body):
        if obj == 1:
            ident, = struct.unpack('=I', body)
            if op == 1:
                self.registry = ident
                self.event(ident, 0, uint(10) + string('wl_seat') + uint(9))
                self.event(ident, 0, uint(11) + string('wl_seat') + uint(9))
                for i, name in enumerate(self.managers, 20):
                    self.event(ident, 0, uint(i) + string(name) + uint(2 if name.startswith('zwlr') else 1))
            else:
                self.event(ident, 0, uint(0))
                self.event(1, 1, uint(ident))
        elif obj == self.registry:
            name, = struct.unpack_from('=I', body)
            iface, offset = get_string(body, 4)
            ver, ident = struct.unpack_from('=II', body, offset)
            self.binds.append((name, iface, ver))
            if iface in MANAGERS:
                self.manager = ident
        elif obj == getattr(self, 'manager', None):
            if op == 1:
                self.device, self.seat = struct.unpack('=II', body)
            elif op == 0:
                ident, = struct.unpack('=I', body)
                self.sources[ident] = []
        elif obj in self.sources:
            if op == 0:
                mime, _ = get_string(body)
                self.sources[obj].append(mime)
            else:
                del self.sources[obj]
                self.event(1, 1, uint(obj))
        elif obj == self.device and op == 0:
            self.source, = struct.unpack('=I', body)
            self.selection(dict.fromkeys(self.sources[self.source]), self.source)
        elif obj in self.offers:
            if op == 1:
                del self.offers[obj]
            else:
                mime, _ = get_string(body)
                fd = self.fds.pop(0)
                types, source = self.offers[obj]
                if source:
                    self.event(source, 0, string(mime), fd)
                    os.close(fd)
                else:
                    payload = types[mime]
                    def write():
                        try:
                            if payload is None:
                                time.sleep(.15)
                            else:
                                offset = 0
                                while offset < len(payload):
                                    offset += os.write(fd, payload[offset:offset + 65536])
                        except BrokenPipeError:
                            pass
                        finally:
                            os.close(fd)
                    threading.Thread(target=write, daemon=True).start()

    def run(self):
        try:
            while not self.stop:
                raw, ancillary, _, _ = self.sock.recvmsg(65536, socket.CMSG_SPACE(1024))
                if not raw:
                    break
                for _, _, data in ancillary:
                    values = array.array('i')
                    values.frombytes(data)
                    self.fds.extend(values)
                self.buffer.extend(raw)
                while len(self.buffer) >= 8:
                    obj, word = struct.unpack_from('=II', self.buffer)
                    size = word >> 16
                    if len(self.buffer) < size:
                        break
                    body = bytes(self.buffer[8:size])
                    del self.buffer[:size]
                    self.request(obj, word & 65535, body)
        except Exception as error:
            if not self.stop:
                self.errors.append(error)

    def close(self):
        self.stop = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.thread.join(2)
        self.sock.close()
        for fd in self.fds:
            os.close(fd)


class WaylandTests(unittest.TestCase):
    def setup_peer(self, managers=MANAGERS, **kwargs):
        self.peer = Compositor(managers)
        self.addCleanup(self.peer.close)
        self.changes = []
        self.client = Clipboard(lambda *args: self.changes.append(args), self.peer.client, **kwargs)
        self.addCleanup(self.client.close)
        return self.client

    def pump(self, condition, timeout=3):
        end = time.monotonic() + timeout
        while not condition() and time.monotonic() < end:
            self.client.dispatch(.005)
        self.assertFalse(self.peer.errors, self.peer.errors)
        self.assertTrue(condition(), 'timed out')

    def test_registry_both_fallback_and_unsupported(self):
        for managers, expected in [(MANAGERS, MANAGERS[0]), ((MANAGERS[1],), MANAGERS[1]), ((), None)]:
            with self.subTest(managers=managers):
                c = self.setup_peer(managers)
                if expected is None:
                    with self.assertRaises(Unsupported):
                        c.initialize()
                else:
                    c.initialize()
                    self.assertEqual(c.protocol, expected)
                    self.assertEqual(self.peer.binds, [(10, 'wl_seat', 1), (20, expected, 1)])
                    self.assertEqual(self.peer.seat, c.seat)

    def test_selection_text_png_invalid_utf8_and_clear(self):
        c = self.setup_peer(); c.initialize()
        for types, expected in [({PNG: b'png', TEXT[1]: b'hello'}, (TEXT[0], b'hello')),
                                ({TEXT[0]: b'\xff', PNG: b'png'}, (PNG, b'png')),
                                ({PNG: b'png'}, (PNG, b'png'))]:
            self.changes.clear()
            self.peer.selection(types)
            self.pump(lambda: bool(self.changes))
            self.assertEqual(self.changes, [expected])
        self.peer.event(c.device, 1, uint(0))
        self.pump(lambda: c.selection is None)
        self.assertIsNone(c.reading)

    def test_own_selection_large_transfer_no_deadlock_cancelled(self):
        c = self.setup_peer(); c.initialize()
        payload = b'x' * (1024 * 1024)
        c.set_selection(TEXT[0], payload)
        self.pump(lambda: bool(self.changes))
        self.assertEqual(self.changes, [(TEXT[0], payload)])
        source = self.peer.source
        self.assertEqual(self.peer.sources[source], list(TEXT))
        self.peer.event(source, 1)
        self.pump(lambda: source not in c.sources)
        self.pump(lambda: source not in c.objects)

    def test_timeout_cap_invalid_text_drop(self):
        c = self.setup_peer(timeout=.05, limit=1024); c.initialize()
        for data in [None, b'x' * 1025, b'\xff']:
            offer = self.peer.selection({TEXT[0]: data})
            self.pump(lambda: c.selection == offer and c.reading is None)
            self.assertEqual(self.changes, [])
        self.peer.selection({TEXT[0]: b'x' * 1024})
        self.pump(lambda: bool(self.changes))
        self.assertEqual(len(self.changes[0][1]), 1024)

    def test_fragmented_send_fd_and_unknown_mime(self):
        c = self.setup_peer(); c.initialize()
        c.set_selection(TEXT[0], b'payload')
        self.pump(lambda: bool(self.changes))
        source = self.peer.source
        for mime, expected in [('UTF8_STRING', b'payload'), ('application/unknown', b'')]:
            read, write = os.pipe()
            try:
                body = string(mime)
                raw = uint(source, (len(body) + 8) << 16) + body
                with self.peer.lock:
                    self.peer.sock.sendmsg([raw[:5]], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [write]))])
                os.close(write)
                write = None
                c.dispatch(.01)
                with self.peer.lock:
                    self.peer.sock.sendall(raw[5:])
                self.pump(lambda: bool(select.select([read], [], [], 0)[0]))
                self.assertEqual(os.read(read, 1024), expected)
            finally:
                os.close(read)
                if write is not None:
                    os.close(write)

    def test_default_cap_and_png_source(self):
        c = self.setup_peer(); c.initialize()
        offer = self.peer.selection({PNG: b'x' * (16 * 1024 * 1024 + 1)})
        self.pump(lambda: c.selection == offer and c.reading is None)
        self.assertEqual(self.changes, [])
        c.set_selection(PNG, b'png payload')
        self.pump(lambda: bool(self.changes))
        self.assertEqual(self.changes, [(PNG, b'png payload')])
        self.assertEqual(self.peer.sources[self.peer.source], [PNG])

    def test_display_socket_environment(self):
        for display, expected in [('wayland-1', '/run/user/test/wayland-1'),
                                  ('/absolute/wayland-2', '/absolute/wayland-2')]:
            with patch.dict(os.environ, {'WAYLAND_DISPLAY': display, 'XDG_RUNTIME_DIR': '/run/user/test'}):
                with patch('wayland_clipboard.socket.socket') as factory:
                    c = Clipboard(lambda *_: None)
                    factory.return_value.connect.assert_called_once_with(expected)
                    c.close()

    def test_finished_and_display_error(self):
        c = self.setup_peer(); c.initialize()
        self.peer.event(c.device, 2)
        with self.assertRaisesRegex(RuntimeError, 'finished'):
            for _ in range(20):
                c.dispatch(.01)
        self.peer.event(1, 0, uint(c.device, 1) + string('bad source'))
        with self.assertRaisesRegex(RuntimeError, 'bad source'):
            for _ in range(20):
                c.dispatch(.01)

    def test_agent_host_guest_sync_and_echoes(self):
        c = self.setup_peer()
        host, guest = socket.socketpair()
        self.addCleanup(host.close); self.addCleanup(guest.close)
        errors = []
        def run():
            try:
                agent.run_data_control(guest.fileno(), c)
            except Exception as error:
                errors.append(error)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_RUNTIME_DIR': temp}):
            thread = threading.Thread(target=run, daemon=True); thread.start()
            host.settimeout(3)
            stream = host.makefile('rb'); self.addCleanup(stream.close)
            self.assertEqual(json.loads(stream.readline()), {'type': 'sync'})
            host.sendall(agent.encode_message(TEXT[0], b'host'))
            end = time.monotonic() + 2
            while not c.sources and time.monotonic() < end:
                time.sleep(.01)
            # A barrier waits until the own selection read/echo has completed.
            end = time.monotonic() + 2
            while (not c.selection or c.reading) and time.monotonic() < end:
                time.sleep(.01)
            self.assertFalse(select.select([host], [], [], .15)[0])
            self.peer.selection({TEXT[1]: b'guest'})
            self.assertEqual(agent.decode_message(stream.readline()), (TEXT[0], b'guest'))
            source_count = c.next_id
            host.sendall(agent.encode_message(TEXT[0], b'guest'))
            time.sleep(.15)
            self.assertEqual(c.next_id, source_count)
            host.shutdown(socket.SHUT_WR)
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertRegex(str(errors[0]), 'disconnected')


class StatusAndStateTests(unittest.TestCase):
    def test_state_permissions_and_status(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_RUNTIME_DIR': temp}):
            self.assertEqual(status.clipboard_state(), 'unknown')
            for state in ('active', 'unsupported', 'error'):
                before = status.clipboard_stamp()
                agent.write_state('data-control', state, MANAGERS[0])
                self.assertNotEqual(status.clipboard_stamp(), before)
                path = agent.state_path()
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual(json.loads(path.read_text()), dict(backend='data-control', state=state, protocol=MANAGERS[0]))
                self.assertEqual(status.clipboard_state(), state)
            path.write_text('{bad')
            self.assertEqual(status.clipboard_state(), 'unknown')

    def test_status_gnome_kde_and_desktop(self):
        for ext, expected in [('active', 'active'), ('missing', 'pending'), ('outdated', 'outdated'),
                              ('inactive', 'inactive'), ('error', 'error'), ('unknown', 'unknown')]:
            value = json.loads(status.encode_status('0.3.0', 'Ubuntu', '50', ext))
            self.assertEqual((value['desktop'], value['desktopVersion'], value['shell'], value['extension'], value['clipboard']),
                             ('GNOME', '50', '50', ext, expected))
        value = json.loads(status.encode_status('0.3.0', 'Fedora', None, 'unknown', 'KDE', '6.8.1', 'active'))
        self.assertEqual(value['extension'], 'unknown'); self.assertNotIn('shell', value)
        self.assertEqual(value['desktopVersion'], '6.8.1'); self.assertEqual(value['clipboard'], 'active')
        for desktop, expected in [('ubuntu:GNOME', 'GNOME'), ('KDE:Plasma', 'KDE'), ('X\n' * 40, 'X' * 32), ('', '')]:
            with patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': desktop}):
                self.assertEqual(status.session_desktop(), expected)
        status.plasma_version.cache_clear()
        with patch.object(status.subprocess, 'run', return_value=Mock(stdout='plasmashell 6.8.1\n')) as run:
            self.assertEqual(status.plasma_version(), '6.8.1')
            self.assertEqual(status.plasma_version(), '6.8.1')
            run.assert_called_once()
        status.plasma_version.cache_clear()

    def test_kde_status_rereports_file_changes_and_queries(self):
        import types
        host, guest = socket.socketpair()
        self.addCleanup(host.close)
        port = guest.makefile('rwb', buffering=0)
        self.addCleanup(guest.close)
        errors = []
        def run():
            try:
                status.main()
            except Exception as error:
                errors.append(error)
        with (tempfile.TemporaryDirectory() as temp,
              patch.dict(os.environ, {'XDG_RUNTIME_DIR': temp, 'XDG_CURRENT_DESKTOP': 'KDE'}),
              patch.dict(sys.modules, {'version': types.SimpleNamespace(VERSION='0.3.0')}),
              patch.object(status, 'PORT') as path,
              patch.object(status, 'plasma_version', return_value='6.8.1')):
            path.open.return_value = port
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            host.settimeout(3)
            stream = host.makefile('rb')
            self.addCleanup(stream.close)
            self.assertEqual(json.loads(stream.readline())['clipboard'], 'unknown')
            agent.write_state('data-control', 'active', MANAGERS[0])
            value = json.loads(stream.readline())
            self.assertEqual(value['clipboard'], 'active')
            self.assertEqual(value['extension'], 'unknown')
            host.sendall(b'{"type":"query"}\n')
            self.assertEqual(json.loads(stream.readline()), value)
            host.shutdown(socket.SHUT_WR)
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertRegex(str(errors[0]), 'disconnected')

    def test_agent_backend_selection_and_error_state(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_RUNTIME_DIR': temp, 'XDG_CURRENT_DESKTOP': 'ubuntu:GNOME'}):
            with patch.object(agent, 'gnome_main', return_value=0) as gnome:
                self.assertEqual(agent.main(), 0)
                gnome.assert_called_once()
            with patch.object(agent, 'gnome_main', side_effect=RuntimeError('failed')):
                with self.assertRaises(RuntimeError):
                    agent.main()
                self.assertEqual(status.clipboard_state(), 'error')
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_RUNTIME_DIR': temp, 'XDG_CURRENT_DESKTOP': 'KDE'}):
            with patch('wayland_clipboard.Clipboard') as backend, patch.object(agent, 'PORT'):
                backend.return_value.initialize.side_effect = Unsupported('none')
                self.assertEqual(agent.main(), 0)
                self.assertEqual(status.clipboard_state(), 'unsupported')
