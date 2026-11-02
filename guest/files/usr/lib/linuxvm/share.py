#!/usr/bin/python3
"""Mount the optional 9p export and manage only the links we create."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from common import atomic_write, folder_name, read_credential, save_json

MOUNT = Path('/mnt/mac')
RUNTIME = Path('/run/linuxvm/shared-folder-name')
DEVICES = Path('/sys/bus/virtio/drivers/9pnet_virtio')


def find_share_device(devices=DEVICES) -> bool:
    for path in devices.glob('virtio*/mount_tag'):
        if path.read_bytes().rstrip(b'\0\n') == b'mac':
            return True
    return False


def share_is_mounted(mount=MOUNT, mountinfo=Path('/proc/self/mountinfo')) -> bool:
    for line in mountinfo.read_text().splitlines():
        before, separator, after = line.partition(' - ')
        fields = before.split()
        if separator and len(fields) >= 5 and fields[4] == str(mount):
            return after.split()[:2] == ['9p', 'mac']
    return False


def mount_share() -> None:
    RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME.unlink(missing_ok=True)
    encoded = None
    try:
        encoded = read_credential().get('shared_folder_name')
        if encoded is not None:
            folder_name(encoded)
    except ValueError as error:
        print(f'Ignoring shared folder name: {error}', file=sys.stderr)
        encoded = None
    if not find_share_device():
        return
    MOUNT.mkdir(parents=True, exist_ok=True)
    if os.path.ismount(MOUNT) and not share_is_mounted():
        raise RuntimeError('/mnt/mac is already occupied by another filesystem')
    if not share_is_mounted():
        # Upstream uses readahead to avoid the 9p/netfs writeback corruption path.
        subprocess.run(['/usr/bin/mount', '-t', '9p', '-o',
                        'trans=virtio,version=9p2000.L,msize=1048576,cache=readahead,nodev,nosuid',
                        'mac', str(MOUNT)], check=True, timeout=30)
    if encoded is not None:
        atomic_write(RUNTIME, (encoded + '\n').encode('ascii'))


def unmount_share() -> None:
    RUNTIME.unlink(missing_ok=True)
    if share_is_mounted():
        subprocess.run(['/usr/bin/umount', str(MOUNT)], check=True, timeout=30)


class ShareLink:
    def __init__(self, home: Path, state: Path, mount=MOUNT):
        self.home = home
        self.state = state
        self.mount = mount

    def _record(self):
        try:
            record = json.loads(self.state.read_text())
            name = folder_name(record['encoded'])
            return record, self.home / name
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            return None, None

    def cleanup(self) -> None:
        record, link = self._record()
        if record is not None:
            try:
                info = link.lstat()
                if (link.is_symlink() and os.readlink(link) == str(self.mount)
                        and [info.st_dev, info.st_ino, info.st_ctime_ns] == record.get('identity')):
                    link.unlink()
            except FileNotFoundError:
                pass
        self.state.unlink(missing_ok=True)

    def update(self, encoded: str | None) -> None:
        name = folder_name(encoded) if encoded is not None else None
        record, link = self._record()
        if record is not None and record['encoded'] == encoded:
            try:
                info = link.lstat()
                if (link.is_symlink() and os.readlink(link) == str(self.mount)
                        and [info.st_dev, info.st_ino, info.st_ctime_ns] == record.get('identity')):
                    return
            except FileNotFoundError:
                pass
        self.cleanup()
        if name is None:
            return
        link = self.home / name
        try:
            link.symlink_to(self.mount)
        except FileExistsError:
            return
        info = link.lstat()
        save_json(self.state, {'encoded': encoded, 'identity': [info.st_dev, info.st_ino, info.st_ctime_ns]})


def user_link(cleanup=False) -> None:
    home = Path.home()
    state_home = Path(os.environ.get('XDG_STATE_HOME', home / '.local/state'))
    manager = ShareLink(home, state_home / 'linuxvm/share-link.json')
    if cleanup:
        manager.cleanup()
        return
    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while running:
            encoded = None
            if share_is_mounted():
                try:
                    with RUNTIME.open('rb') as stream:
                        data = stream.read(342)
                    encoded = data.decode('ascii').removesuffix('\n')
                    folder_name(encoded)
                except FileNotFoundError:
                    pass
            manager.update(encoded)
            time.sleep(1)
    finally:
        manager.cleanup()


if __name__ == '__main__':
    try:
        action = sys.argv[1]
        if action == 'mount':
            mount_share()
        elif action == 'unmount':
            unmount_share()
        elif action == 'link':
            user_link()
        elif action == 'unlink':
            user_link(cleanup=True)
        else:
            raise ValueError('unknown share action')
    except Exception as error:
        print(f'linuxvm-share: {error}', file=sys.stderr, flush=True)
        raise SystemExit(1)
