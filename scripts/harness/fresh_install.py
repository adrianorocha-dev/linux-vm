"""Create, install, verify and (by default) remove an isolated harness VM."""
import argparse
import contextlib
import functools
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import shlex
import shutil
import threading
import time
import uuid

from terminal import screen, editor_linux_line
from common import CTL, ROOT, VM_ROOT, PROTECTED, Guest, SESSION, free_port, run, wait_for, write_json


def seed(public_key, password_hash, port):
    # JSON scalars are valid YAML, including the single-quoted shell commands.
    late = [
        "curtin in-target -- sh -c 'echo \"tester ALL=(ALL) NOPASSWD:ALL\" > /etc/sudoers.d/90-tester && chmod 440 /etc/sudoers.d/90-tester'",
        "curtin in-target -- sh -c 'printf \"[daemon]\\nAutomaticLoginEnable=true\\nAutomaticLogin=tester\\n\" > /etc/gdm3/custom.conf'",
        "curtin in-target -- touch /var/lib/linuxvm-harness-installed",
        f"wget -q -O /dev/null http://10.0.2.2:{port}/installation-complete",
    ]
    return '\n'.join([
        '#cloud-config', 'autoinstall:', '  version: 1', '  identity:',
        '    hostname: harness-ubuntu', '    realname: Tester', '    username: tester',
        '    password: ' + json.dumps(password_hash),
        '  ssh:', '    install-server: true', '    allow-pw: false', '    authorized-keys:',
        '      - ' + json.dumps(public_key.strip()),
        '  early-commands:',
        '    - ' + json.dumps("sh -c 'setsid tail -F /var/log/installer/subiquity-server-debug.log > /dev/ttyAMA0 2>&1 < /dev/null &'"),
        '  storage:', '    layout:', '      name: direct',
        '  late-commands:', *['    - ' + json.dumps(command) for command in late],
        '  shutdown: reboot', '',
    ])


def cleanup(directory):
    """Only remove the exact UUID and name registered by this run's create call."""
    directory = Path(directory).resolve()
    owned = json.loads((directory / 'owned-vm.json').read_text())
    vm_id = owned['id']
    if str(uuid.UUID(vm_id)).upper() != vm_id or vm_id == PROTECTED:
        raise RuntimeError('Refusing cleanup: invalid or protected VM id')
    folder = VM_ROOT / vm_id
    if not folder.exists():
        return
    config = json.loads((folder / 'config.json').read_text())
    if config.get('id') != vm_id or config['name'] != owned['name'] or not config['name'].startswith('harness-'):
        raise RuntimeError('Refusing cleanup: ownership/name mismatch')
    def stopped():
        return run([CTL, 'status', vm_id]).stdout.splitlines()[0] == 'stopped'
    if not stopped():
        run([CTL, 'stop', vm_id], check=False)
        try:
            serial = folder / 'logs/serial.log'
            booted = serial.exists() and 'Linux version' in serial.read_text(errors='replace')
            wait_for('graceful shutdown', stopped, 90 if booted else 10, folder / 'logs')
        except TimeoutError:
            run([CTL, 'stop', vm_id, '--force'])
            wait_for('forced shutdown', stopped, 30, folder / 'logs')
    if (folder / 'logs').exists():
        shutil.copytree(folder / 'logs', directory / 'vm-logs', dirs_exist_ok=True)
    shutil.rmtree(folder)  # Deliberately bypass Trash, but only after stop + ownership checks.
    summary_path = directory / 'summary.json'
    if summary_path.exists():
        saved = json.loads(summary_path.read_text())
        saved.update(cleaned_up=True, kept=False)
        write_json(summary_path, saved)


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    relative = ROOT / 'test-media/ubuntu-26.04.1-desktop-arm64.iso'
    parser.add_argument('--iso', type=Path, default=relative if relative.exists() else Path('~/ccsandbox/linux-vm/test-media/ubuntu-26.04.1-desktop-arm64.iso'))
    parser.add_argument('--deb', type=Path)
    parser.add_argument('--keep', action='store_true')
    parser.add_argument('--install-timeout', type=int, default=3600)
    parser.add_argument('--boot-timeout', type=int, default=600)
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args()
    if not args.iso.is_file() or (args.deb and not args.deb.is_file()):
        parser.error('ISO/deb does not exist')
    # Fail closed rather than starting alongside a user VM, including a UTM QEMU.
    processes = run(['ps', '-axo', 'comm=']).stdout
    if any('qemu-system-' in line for line in processes.splitlines()):
        parser.error('A QEMU VM is already running; stop it yourself before using this harness')
    directory = (args.run_dir or ROOT / 'harness-runs' / time.strftime('%Y%m%d-%H%M%S')).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    directory.chmod(0o700)
    summary = {'run_dir': str(directory), 'phases': {}, 'success': False}
    started = time.monotonic()
    server = thread = execute = None
    owned = False
    log = (directory / 'host.log').open('a', buffering=1)
    def say(message):
        print(message, flush=True)
        print(message, file=log)
    @contextlib.contextmanager
    def phase(name):
        say(f'[{name}] starting')
        before = time.monotonic()
        try:
            yield
        except Exception as error:
            if hasattr(error, 'stderr'):
                (directory / (name + '-error.log')).write_text((error.stdout or '') + (error.stderr or ''))
            raise
        finally:
            summary['phases'][name] = round(time.monotonic() - before, 3)
            write_json(directory / 'summary.json', summary)
    try:
        with phase('seed'):
            run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', directory / 'id_ed25519'])
            password_hash = run(['/opt/homebrew/bin/openssl', 'passwd', '-6', '-stdin'], input=secrets.token_urlsafe(32) + '\n').stdout.strip()
            seed_dir = directory / 'seed'
            seed_dir.mkdir()
            http_log = (directory / 'http.log').open('a', buffering=1)
            class Handler(http.server.SimpleHTTPRequestHandler):
                def log_message(self, fmt, *values):
                    print(time.strftime('%FT%T'), fmt % values, file=http_log)
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(seed_dir)))
            port = server.server_port
            (seed_dir / 'user-data').write_text(seed((directory / 'id_ed25519.pub').read_text(), password_hash, port))
            (seed_dir / 'meta-data').write_text('')
            (seed_dir / 'vendor-data').write_text('')
            (seed_dir / 'network-config').write_text('network: {version: 2, ethernets: {all: {match: {name: "en*"}, dhcp4: true}}}\n')
            (seed_dir / 'installation-complete').touch()
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
        with phase('create'):
            name = 'harness-' + directory.name + '-' + secrets.token_hex(3)
            # Defer interruption across create + ownership registration so Ctrl-C
            # cannot leave an untracked VM folder between the two operations.
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
            try:
                vm_id = run([CTL, 'create', '--name', name, '--iso', args.iso.resolve(), '--cpus', '4', '--memory', '4096', '--disk', '32']).stdout.strip()
                if vm_id == PROTECTED or str(uuid.UUID(vm_id)).upper() != vm_id:
                    raise RuntimeError('Unexpected VM id from create; refusing to act')
                write_json(directory / 'owned-vm.json', {'id': vm_id, 'name': name})
                owned = True
                summary['vm_id'] = vm_id
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            ssh_port = free_port()
            write_json(directory / 'connection.json', {'port': ssh_port, 'key': 'id_ed25519', 'user': 'tester', 'vm_id': vm_id})
            summary.update(vm_id=vm_id, port=ssh_port)
            guest = Guest.from_run(directory)
            say(f'VM {vm_id}; SSH port {ssh_port}\n{shlex.join(guest.argv())}\nRun: {directory}')
            run([CTL, 'set', vm_id, '--forward', f'{ssh_port}:22'])
            run([CTL, 'start', vm_id])
        folder = VM_ROOT / vm_id
        serial = folder / 'logs/serial.log'
        def serial_text():
            return serial.read_text(errors='replace') if serial.exists() else ''
        with phase('grub'):
            wait_for('GRUB menu', lambda: 'Try or Install Ubuntu' in serial_text(), 180, serial)
            spec = importlib.util.spec_from_file_location('qmp_type', ROOT / 'scripts/qmp-type.py')
            qmp_type = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(qmp_type)
            execute = qmp_type.qmp(qmp_type.control_socket(vm_id))
            execute('send-key', keys=qmp_type.chord('e'), **{'hold-time': 80})
            time.sleep(1.5)
            lines, cursor_row, _ = screen(serial_text())
            linux_row = next((i for i, line in enumerate(lines) if re.match(r'\s*linux\s', line[2:])), None)
            if linux_row is None:
                raise RuntimeError(f'GRUB linux line not found; inspect {serial}')
            for key in [*(['down'] * (linux_row - cursor_row) if linux_row >= cursor_row else ['up'] * (cursor_row - linux_row)), 'end']:
                execute('send-key', keys=qmp_type.chord(key), **{'hold-time': 80})
                time.sleep(1)
            kernel_args = f' autoinstall ds=nocloud-net\\;s=http://10.0.2.2:{port}/ console=ttyAMA0'
            for char in kernel_args:
                execute('send-key', keys=qmp_type.character(char), **{'hold-time': 40})
                time.sleep(.08)
            time.sleep(2)
            # Strip ANSI movement/formatting, preserve the raw evidence too.
            edited = serial_text()
            (directory / 'grub-edit.log').write_text(edited)
            edited_line = editor_linux_line(edited)
            (directory / 'grub-linux-line.txt').write_text(edited_line + '\n')
            if kernel_args.strip() not in edited_line:
                raise RuntimeError(f'Could not verify GRUB linux arguments; inspect {directory / "grub-edit.log"}')
            execute('send-key', keys=qmp_type.chord('ctrl-x'), **{'hold-time': 80})
            execute.close()
            execute = None
        with phase('install'):
            wait_for('installer late commands', lambda: 'GET /installation-complete ' in (directory / 'http.log').read_text(), args.install_timeout, serial)
            # The final late command is after target installation/configuration. Eject
            # now, before reboot; the running installer is already resident in RAM.
            run([CTL, 'eject', vm_id])
        with phase('first_boot'):
            def installed():
                result = guest.ssh('test -f /var/lib/linuxvm-harness-installed', check=False, timeout=15)
                with (directory / 'ssh-wait.log').open('a') as out:
                    out.write(result.stderr)
                return result.returncode == 0
            wait_for('installed system SSH', installed, args.boot_timeout, directory / 'ssh-wait.log')
        with phase('guest_tools'):
            if args.deb:
                guest.put(args.deb, '/tmp/linuxvm-harness.deb')
                result = guest.ssh('sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y /tmp/linuxvm-harness.deb', timeout=600)
            else:
                result = guest.ssh('set -eu; dev=$(sudo blkid -L LINUXVM-TOOLS); sudo mkdir -p /mnt/linuxvm-tools; sudo mount -o ro "$dev" /mnt/linuxvm-tools; cd /mnt/linuxvm-tools; sudo sh install.sh', timeout=600)
            (directory / 'guest-tools.log').write_text(result.stdout + result.stderr)
        with phase('tools_reboot'):
            boot_id = guest.ssh('cat /proc/sys/kernel/random/boot_id').stdout.strip()
            guest.ssh('sudo reboot', check=False)
            wait_for('guest tools reboot', lambda: (r := guest.ssh('cat /proc/sys/kernel/random/boot_id', check=False, timeout=15)).returncode == 0 and r.stdout.strip() != boot_id, args.boot_timeout, directory / 'ssh-wait.log')
        with phase('session'):
            command = SESSION + '''set -eu
found=0
for s in $(loginctl list-sessions --no-legend | awk '{print $1}'); do
 [ "$(loginctl show-session "$s" -p Name --value)" = tester ] || continue
 [ "$(loginctl show-session "$s" -p Type --value)" = wayland ] || continue
 [ "$(loginctl show-session "$s" -p Seat --value)" = seat0 ] || continue
 [ "$(loginctl show-session "$s" -p Active --value)" = yes ] || continue
 found=1
done
[ "$found" = 1 ]
gnome-extensions info clipboard@linuxvm.dev
for unit in linuxvm-clipboard linuxvm-audio; do
 systemctl --user is-active "$unit" || exit 1
done
'''
            def ready():
                result = guest.ssh(command, check=False, timeout=20)
                (directory / 'session.log').write_text(result.stdout + result.stderr)
                return result.returncode == 0 and bool(re.search(r'State: ACTIVE', result.stdout))
            wait_for('GNOME Wayland and integration services', ready, 180, directory / 'session.log')
            summary['success'] = True
            say('Fresh install passed; GNOME Wayland and guest integration are active.')
    except BaseException as error:
        summary['error'] = f'{type(error).__name__}: {error}'
        say(summary['error'])
        raise
    finally:
        if execute:
            execute.close()
        if server:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            http_log.close()
        if owned:
            try:
                if not args.keep:
                    with phase('cleanup'):
                        cleanup(directory)
                    summary['cleaned_up'] = True
                else:
                    summary['kept'] = True
                    if (VM_ROOT / summary['vm_id'] / 'logs').exists():
                        shutil.copytree(VM_ROOT / summary['vm_id'] / 'logs', directory / 'vm-logs', dirs_exist_ok=True)
            except BaseException as error:
                summary['cleanup_error'] = str(error)
                summary['success'] = False
                raise
            finally:
                summary['total_seconds'] = round(time.monotonic() - started, 3)
                write_json(directory / 'summary.json', summary)
        summary['total_seconds'] = round(time.monotonic() - started, 3)
        write_json(directory / 'summary.json', summary)
        log.close()


if __name__ == '__main__':
    main()
