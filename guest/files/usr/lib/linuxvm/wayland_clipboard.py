"""Minimal, asynchronous ext/wlr data-control client (no Wayland bindings).

Wire layouts: wayland/protocol/wayland.xml at
https://gitlab.freedesktop.org/wayland/wayland ; wayland-protocols/staging/
ext-data-control/ext-data-control-v1.xml at
https://gitlab.freedesktop.org/wayland/wayland-protocols ; and
https://gitlab.freedesktop.org/wlroots/wlr-protocols/-/blob/master/unstable/wlr-data-control-unstable-v1.xml.
Only interface names differ for the requests/events used here; bind version 1.
"""
import array
from collections import deque
import os
from pathlib import Path
import select
import socket
import struct
import time

TEXT = ('text/plain;charset=utf-8', 'text/plain', 'UTF8_STRING', 'TEXT', 'STRING')
PNG = 'image/png'
LIMIT = 16 * 1024 * 1024
MANAGERS = ('ext_data_control_manager_v1', 'zwlr_data_control_manager_v1')


def uint(*values):
    return struct.pack('=' + 'I' * len(values), *values)


def string(value):
    raw = value.encode() + b'\0'
    return uint(len(raw)) + raw + b'\0' * (-len(raw) % 4)


def get_string(raw, offset=0):
    size, = struct.unpack_from('=I', raw, offset)
    end = offset + 4 + size
    if not size or end > len(raw) or raw[end - 1] != 0:
        raise RuntimeError('invalid Wayland string')
    return raw[offset + 4:end - 1].decode(), end + (-size % 4)


class Unsupported(RuntimeError):
    pass


class Clipboard:
    """fileno() is the display; call dispatch() every <= .1 s for pipe progress.

    dispatch also selects transfer pipes and returns ready extra_read fds, for
    embedding in the host-port loop. changed(mime, bytes) runs after a complete
    bounded read. set_selection queues a source; initialize waits for readiness.
    """
    def __init__(self, changed, sock=None, timeout=5, limit=LIMIT):
        self.changed, self.timeout, self.limit = changed, timeout, limit
        self.sock = sock or socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if sock is None:
            display = os.environ.get('WAYLAND_DISPLAY')
            if not display:
                self.sock.close()
                raise RuntimeError('WAYLAND_DISPLAY is unset')
            path = Path(display)
            if not path.is_absolute():
                path = Path(os.environ['XDG_RUNTIME_DIR']) / path
            try:
                self.sock.connect(str(path))
            except Exception:
                self.sock.close()
                raise
        self.sock.setblocking(False)
        self.objects = {1: 'display'}
        self.next_id = 2
        self.incoming, self.fds, self.outgoing = bytearray(), deque(), deque()
        self.globals, self.offers, self.sources, self.writes = {}, {}, {}, {}
        self.selection, self.reading = None, None
        self.candidates = []
        self.protocol = ''
        self.done = set()
        self.registry = self.new('registry')
        self.request(1, 1, uint(self.registry))

    def fileno(self):
        return self.sock.fileno()

    def new(self, kind):
        value = self.next_id
        self.next_id += 1
        if value >= 0xff000000:
            raise RuntimeError('Wayland object ids exhausted')
        self.objects[value] = kind
        return value

    def request(self, obj, opcode, body=b'', fd=None):
        self.outgoing.append([uint(obj, ((len(body) + 8) << 16) | opcode) + body, fd])

    def barrier(self):
        callback = self.new('callback')
        self.request(1, 0, uint(callback))
        deadline = time.monotonic() + self.timeout
        while callback not in self.done:
            if time.monotonic() >= deadline:
                raise RuntimeError('Wayland roundtrip timed out')
            self.dispatch(.05)
        self.done.remove(callback)

    def initialize(self):
        self.barrier()
        seats = [(name, ver) for name, (iface, ver) in self.globals.items() if iface == 'wl_seat']
        manager = next(((name, iface) for iface in MANAGERS
                        for name, (kind, ver) in self.globals.items() if kind == iface), None)
        if manager is None:
            raise Unsupported('compositor has no data-control manager')
        if not seats:
            raise RuntimeError('compositor has no seat')
        def bind(name, iface, kind):
            obj = self.new(kind)
            self.request(self.registry, 0, uint(name) + string(iface) + uint(1, obj))
            return obj
        self.seat = bind(seats[0][0], 'wl_seat', 'seat')
        self.protocol = manager[1]
        self.manager = bind(manager[0], self.protocol, 'manager')
        self.device = self.new('device')
        self.request(self.manager, 1, uint(self.device, self.seat))
        self.barrier()

    def set_selection(self, mime, payload):
        if mime not in (TEXT[0], PNG) or not payload or len(payload) > self.limit:
            raise ValueError('invalid selection')
        if mime == TEXT[0]:
            payload.decode('utf-8')
        source = self.new('source')
        types = TEXT if mime == TEXT[0] else (PNG,)
        self.sources[source] = (types, payload)
        self.request(self.manager, 0, uint(source))
        for offered in types:
            self.request(source, 0, string(offered))
        self.request(self.device, 0, uint(source))

    def destroy_offer(self, offer):
        if offer in self.offers:
            self.request(offer, 1)
            del self.offers[offer]
            self.objects.pop(offer, None)

    def next_read(self):
        if not self.candidates:
            return
        mime = self.candidates.pop(0)
        read, write = os.pipe()
        os.set_blocking(read, False)
        self.request(self.selection, 0, string(mime), write)
        self.reading = (read, mime, bytearray(), time.monotonic() + self.timeout)

    def event(self, obj, opcode, body):
        kind = self.objects.get(obj)
        if kind == 'display':
            if opcode == 0:
                target, code = struct.unpack_from('=II', body)
                message, _ = get_string(body, 8)
                raise RuntimeError(f'Wayland error {target}/{code}: {message}')
            if opcode == 1:
                deleted, = struct.unpack('=I', body)
                self.objects.pop(deleted, None)
        elif kind == 'registry':
            name, = struct.unpack_from('=I', body)
            if opcode == 0:
                iface, offset = get_string(body, 4)
                version, = struct.unpack_from('=I', body, offset)
                self.globals[name] = (iface, version)
            else:
                self.globals.pop(name, None)
        elif kind == 'callback':
            self.done.add(obj)
        elif kind == 'device':
            if opcode == 2:
                raise RuntimeError('data-control device finished')
            offer, = struct.unpack('=I', body)
            if opcode == 0:
                # new_id in an EVENT belongs to the server, never allocate it.
                self.objects[offer] = 'offer'
                self.offers[offer] = []
            elif opcode == 1:
                if self.reading:
                    os.close(self.reading[0])
                    self.reading = None
                self.destroy_offer(self.selection)
                self.selection = offer or None
                types = self.offers.get(offer, [])
                self.candidates = [m for m in (*TEXT, PNG) if m in types]
                self.next_read()
            elif opcode == 3:  # primary selection is deliberately ignored
                self.destroy_offer(offer)
        elif kind == 'offer':
            mime, _ = get_string(body)
            self.offers[obj].append(mime)
        elif kind == 'source':
            if opcode == 1:
                self.request(obj, 1)
                self.sources.pop(obj, None)
            elif opcode == 0:
                mime, _ = get_string(body)
                fd = self.fds.popleft()
                types, data = self.sources.get(obj, ((), b''))
                if mime not in types:
                    os.close(fd)
                else:
                    os.set_blocking(fd, False)
                    self.writes[fd] = (memoryview(data), time.monotonic() + self.timeout)

    def dispatch(self, timeout=0, extra_read=()):
        reads = [self.sock, *extra_read]
        if self.reading:
            reads.append(self.reading[0])
        ready, writable, _ = select.select(reads, [*self.writes, *([self.sock] if self.outgoing else [])], [], timeout)
        if self.sock in writable:
            data, fd = self.outgoing[0]
            rights = [] if fd is None else [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd]))]
            try:
                sent = self.sock.sendmsg([data], rights)
            except BlockingIOError:
                sent = 0
            if sent:
                if fd is not None:
                    os.close(fd)
                    self.outgoing[0][1] = None
                self.outgoing[0][0] = data[sent:]
                if sent == len(data):
                    self.outgoing.popleft()
        if self.sock in ready:
            data, ancillary, flags, _ = self.sock.recvmsg(65536, socket.CMSG_SPACE(256 * array.array('i').itemsize))
            for level, kind, raw in ancillary:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    values = array.array('i')
                    values.frombytes(raw[:len(raw) // values.itemsize * values.itemsize])
                    self.fds.extend(values)
            if flags & socket.MSG_CTRUNC or not data:
                raise RuntimeError('Wayland disconnected or truncated ancillary data')
            self.incoming.extend(data)
            while len(self.incoming) >= 8:
                obj, word = struct.unpack_from('=II', self.incoming)
                size, opcode = word >> 16, word & 65535
                if size < 8 or size % 4:
                    raise RuntimeError('invalid Wayland message size')
                if len(self.incoming) < size:
                    break
                body = bytes(self.incoming[8:size])
                del self.incoming[:size]
                self.event(obj, opcode, body)
        now = time.monotonic()
        for fd, (data, deadline) in list(self.writes.items()):
            if fd in writable:
                try:
                    data = data[os.write(fd, data[:65536]):]
                except BlockingIOError:
                    pass
                except BrokenPipeError:
                    data = b''
                self.writes[fd] = (data, deadline)
            if not data or now >= deadline:
                os.close(fd)
                del self.writes[fd]
        if self.reading:
            fd, mime, data, deadline = self.reading
            eof = False
            if fd in ready:
                try:
                    chunk = os.read(fd, min(65536, self.limit + 1 - len(data)))
                except BlockingIOError:
                    # Selection events may replace the old pipe and reuse its
                    # fd after select returned readiness for the old pipe.
                    pass
                else:
                    data.extend(chunk)
                    eof = not chunk
            if eof or len(data) > self.limit or now >= deadline:
                os.close(fd)
                self.reading = None
                valid = eof and bool(data) and len(data) <= self.limit
                if valid and mime in TEXT:
                    try:
                        data.decode('utf-8')
                    except UnicodeDecodeError:
                        valid = False
                if valid:
                    self.candidates = []
                    self.changed(TEXT[0] if mime in TEXT else PNG, bytes(data))
                else:
                    self.next_read()
        return [fd for fd in extra_read if fd in ready]

    def close(self):
        for fd in [*self.fds, *self.writes, *([self.reading[0]] if self.reading else []),
                   *(fd for _, fd in self.outgoing if fd is not None)]:
            os.close(fd)
        self.sock.close()
