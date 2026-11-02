#!/usr/bin/python3
"""Follow the host until the guest zone differs from our last applied zone."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys

from common import Lines, read_credential, save_json, zone_path

PORT = Path('/dev/virtio-ports/dev.linuxvm.timezone')
STATE = Path('/var/lib/linuxvm/timezone.json')


class TimeZoneFollower:
    def __init__(self, state_path=STATE, zoneinfo=Path('/usr/share/zoneinfo')):
        self.path = state_path
        self.zoneinfo = zoneinfo
        try:
            self.state = json.loads(state_path.read_text())
        except FileNotFoundError:
            self.state = {'mode': 'auto', 'zone': None}
        if (not isinstance(self.state, dict) or set(self.state) != {'mode', 'zone'}
                or self.state['mode'] not in ('auto', 'manual')):
            raise ValueError('invalid timezone state; refusing to overwrite guest choice')
        if self.state['zone'] is not None:
            zone_path(self.state['zone'], zoneinfo)

    def observe(self, current: str) -> bool:
        if self.state['mode'] == 'manual':
            return False
        if self.state['zone'] is not None and current != self.state['zone']:
            self.state['mode'] = 'manual'
            save_json(self.path, self.state)
            print('Guest timezone changed; no longer following the host.', flush=True)
            return False
        return True

    def synchronize(self, zone: str, current: str, apply) -> bool:
        zone_path(zone, self.zoneinfo)
        if not self.observe(current):
            return False
        changed = current != zone
        if changed:
            apply(zone)
        updated = {'mode': 'auto', 'zone': zone}
        if self.state != updated or not self.path.exists():
            save_json(self.path, updated)
        self.state = updated
        return changed


def decode_zone(line: bytes) -> str | None:
    message = json.loads(line)
    if isinstance(message, dict) and message == {'type': 'wake'}:
        return None
    if not isinstance(message, dict) or set(message) != {'type', 'zone'} or message['type'] != 'timezone':
        raise ValueError('invalid timezone message')
    if not isinstance(message['zone'], str):
        raise ValueError('invalid timezone value')
    return message['zone']


def current_zone() -> str:
    result = subprocess.run(['/usr/bin/timedatectl', 'show', '--property=Timezone', '--value'],
                            capture_output=True, text=True, check=True, timeout=10)
    zone = result.stdout.strip()
    zone_path(zone)
    return zone


def apply_zone(zone: str) -> None:
    subprocess.run(['/usr/bin/timedatectl', 'set-timezone', zone], check=True, timeout=10)


def main() -> int:
    follower = TimeZoneFollower()
    try:
        initial = read_credential().get('timezone')
        if initial is not None:
            follower.synchronize(initial, current_zone(), apply_zone)
    except ValueError as error:
        print(f'Ignoring host credential: {error}', file=sys.stderr)
    with PORT.open('r+b', buffering=0) as port:
        lines = Lines(4096)
        while True:
            # Observe even when the host is silent, so a manual choice survives reconnects.
            follower.observe(current_zone())
            ready, _, _ = select.select([port], [], [], 1)
            if not ready:
                continue
            chunk = os.read(port.fileno(), 4096)
            if not chunk:
                raise RuntimeError('host timezone bridge disconnected')
            for line in lines.feed(chunk):
                zone = decode_zone(line)
                if zone is not None:
                    follower.synchronize(zone, current_zone(), apply_zone)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f'linuxvm-timezone: {error}', file=sys.stderr, flush=True)
        raise SystemExit(1)
