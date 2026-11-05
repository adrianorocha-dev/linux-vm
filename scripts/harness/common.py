"""Host helpers; Python 3.14 standard library only."""
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
VM_ROOT = Path.home() / 'Library/Application Support/Linux VM/VMs'
PROTECTED = '8F611ECF-72A8-4B1B-A54E-811509AC6902'
CTL = os.environ.get('LINUXVMCTL', '/Applications/Linux VM.app/Contents/Helpers/linuxvmctl')


# Run the same parsers on the host and guest, without installing a guest module.
_SESSION_SOURCE = Path(__file__).with_name('session.py').read_text()
SESSION = ('export LC_ALL=C; export XDG_RUNTIME_DIR=/run/user/$(id -u); '
           'export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus; '
           'unset WAYLAND_DISPLAY XDG_CURRENT_DESKTOP; '
           'eval "$(systemctl --user show-environment | python3 -c ' +
           shlex.quote(_SESSION_SOURCE) + ' environment' + ')"; ')


SESSION_CHECK = SESSION + r'''set -eu
found=0
for s in $(loginctl list-sessions --no-legend | awk '{print $1}'); do
 [ "$(loginctl show-session "$s" -p Name --value)" = tester ] || continue
 [ "$(loginctl show-session "$s" -p Type --value)" = wayland ] || continue
 [ "$(loginctl show-session "$s" -p Seat --value)" = seat0 ] || continue
 [ "$(loginctl show-session "$s" -p Active --value)" = yes ] || continue
 found=1
done
[ "$found" = 1 ]
[ -n "${WAYLAND_DISPLAY:-}" ]
case ":${XDG_CURRENT_DESKTOP:-}:" in
 *:KDE:*)
  for unit in linuxvm-clipboard linuxvm-audio linuxvm-status; do
   systemctl --user is-active "$unit" || exit 1
  done
  python3 -c ''' + shlex.quote(_SESSION_SOURCE) + ' clipboard' + r'''
  ;;
 *:GNOME:*|*:ubuntu:*)
  gnome-extensions info clipboard@linuxvm.dev | grep -q 'State: ACTIVE'
  for unit in linuxvm-clipboard linuxvm-audio; do
   systemctl --user is-active "$unit" || exit 1
  done
  ;;
 *) echo "Unsupported desktop: ${XDG_CURRENT_DESKTOP:-unset}" >&2; exit 1 ;;
esac
'''

ENVIRONMENT_REPORT = SESSION + r'''cat /etc/os-release
uname -a
case ":${XDG_CURRENT_DESKTOP:-}:" in
 *:KDE:*) QT_QPA_PLATFORM=offscreen kwin_wayland --version ;;
 *) gnome-shell --version ;;
esac
if command -v rpm >/dev/null; then
 rpm -q linuxvm-guest libinput gtk4
else
 dpkg-query -W linuxvm-guest libinput10 libgtk-4-1
fi
'''


def run(args, *, timeout=60, check=True, **kwargs):
    return subprocess.run([str(x) for x in args], timeout=timeout, check=check,
                          text=True, capture_output=True, **kwargs)


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_for(label, predicate, timeout, log):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(2)
    raise TimeoutError(f'{label} timed out after {timeout}s; inspect {log}')


class Guest:
    def __init__(self, port, key, user='tester'):
        self.port, self.key, self.user = int(port), Path(key).resolve(), user

    @classmethod
    def from_run(cls, directory):
        directory = Path(directory).resolve()
        data = json.loads((directory / 'connection.json').read_text())
        return cls(data['port'], directory / data['key'], data['user'])

    def argv(self):
        return ['ssh', '-i', str(self.key), '-p', str(self.port), '-o', 'BatchMode=yes',
                '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=5', '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=3',
                f'{self.user}@127.0.0.1']

    def ssh(self, command, **kwargs):
        return run(self.argv() + [command], **kwargs)

    def script(self, path, args=(), **kwargs):
        return self.ssh(SESSION + 'python3 - ' + shlex.join([str(x) for x in args]),
                        input=Path(path).read_text(), **kwargs)

    def get(self, remote, local):
        # Binary streaming avoids scp's remote-shell and SFTP differences.
        with open(local, 'wb') as out:
            subprocess.run(self.argv() + ['cat -- ' + shlex.quote(remote)],
                           stdout=out, check=True, timeout=120)

    def put(self, local, remote):
        with open(local, 'rb') as source:
            subprocess.run(self.argv() + ['cat > ' + shlex.quote(remote)],
                           stdin=source, check=True, timeout=120)
