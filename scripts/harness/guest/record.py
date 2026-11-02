"""Root-only collector: libinput debug events plus raw evdev contact state."""
import fcntl
import glob
import json
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import sys
import tempfile
import time

seconds = float(sys.argv[1])
devices = []
for path in glob.glob('/sys/class/input/event*/device/name'):
    name = Path(path).read_text().strip()
    if name == 'QEMU Virtio Pinch Touchpad' or 'Tablet' in name or 'tablet' in name:
        devices.append({'name': name, 'path': '/dev/input/' + Path(path).parents[1].name})
if not any(d['name'] == 'QEMU Virtio Pinch Touchpad' for d in devices):
    raise RuntimeError('QEMU Virtio Pinch Touchpad not found')
raw = []
opened = {}
processes = []
start = time.monotonic()
event_struct = struct.Struct('@llHHi')
try:
    for device in devices:
        fd = os.open(device['path'], os.O_RDONLY | os.O_NONBLOCK)
        opened[fd] = device
        fcntl.ioctl(fd, 0x400445a0, struct.pack('i', 1))  # EVIOCSCLOCKID(CLOCK_MONOTONIC)
        output = tempfile.TemporaryFile(mode='w+')
        process = subprocess.Popen(['stdbuf', '-oL', '-eL', 'libinput', 'debug-events', '--device', device['path']],
                                   stdout=output, stderr=subprocess.STDOUT, env={**os.environ, 'LC_ALL': 'C'})
        processes.append((device, process, output, time.monotonic() - start))
    while time.monotonic() - start < seconds:
        ready, _, _ = select.select(list(opened), [], [], min(.2, max(0, seconds - (time.monotonic() - start))))
        for fd in ready:
            data = os.read(fd, event_struct.size * 256)
            for offset in range(0, len(data), event_struct.size):
                sec, usec, typ, code, value = event_struct.unpack_from(data, offset)
                raw.append({'device': opened[fd]['path'], 'time': sec + usec / 1e6 - start,
                            'type': typ, 'code': code, 'value': value})
finally:
    for fd in opened:
        os.close(fd)
    for device, process, output, offset in processes:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        output.seek(0)
        device.update(debug_events=output.read(), start_offset_seconds=offset, exit_code=process.returncode)
        output.close()
print(json.dumps({'format': 'linuxvm-input-v1', 'duration_seconds': seconds, 'devices': devices, 'evdev': raw}))
