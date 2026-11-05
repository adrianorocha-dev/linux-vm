"""Create, install, verify and (by default) remove an isolated harness VM."""
import argparse
import fedora
import contextlib
import functools
import fcntl
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
import subprocess
import threading
import tempfile
import time
import uuid

from terminal import screen, editor_linux_line
from common import CTL, ROOT, VM_ROOT, PROTECTED, Guest, SESSION_CHECK, ENVIRONMENT_REPORT, free_port, run, wait_for, write_json


PLASMA_INSTALL = r'''set -eu
sudo apt-get update -q
echo "debconf shared/default-x-display-manager select gdm3" | sudo debconf-set-selections
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q kubuntu-desktop
sudo mkdir -p /var/lib/AccountsService/users
printf "[User]\nSession=plasma\nSessionType=wayland\nSystemAccount=false\n" | sudo tee /var/lib/AccountsService/users/tester
'''

PLASMA_ENVIRONMENT_REPORT = '''cat /etc/X11/default-display-manager
dpkg-query -W kubuntu-desktop plasma-workspace kwin-wayland
'''


def install_plasma(guest, directory, timeout):
    """Preserve apt output even on failure or timeout, before propagating it."""
    log = directory / 'plasma-install.log'
    try:
        result = guest.ssh(PLASMA_INSTALL, timeout=timeout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        parts = (error.stdout, error.stderr)
        log.write_text(''.join(p.decode(errors='replace') if isinstance(p, bytes) else p or '' for p in parts))
        raise
    log.write_text(result.stdout + result.stderr)


def session_check(desktop):
    if desktop != 'plasma':
        return SESSION_CHECK
    # SESSION_CHECK imports the running user manager's environment. Installing
    # Plasma beside GNOME alone must not make a Plasma run pass.
    return SESSION_CHECK + r'''case ":${XDG_CURRENT_DESKTOP:-}:" in
 *:KDE:*) ;;
 *) echo "Expected KDE Wayland session for --desktop plasma; got ${XDG_CURRENT_DESKTOP:-unset}" >&2; exit 1 ;;
esac
'''


def seed(public_key, password_hash, port):
    # JSON scalars are valid YAML, including the single-quoted shell commands.
    late = [
        "curtin in-target -- sh -c 'echo \"tester ALL=(ALL) NOPASSWD:ALL\" > /etc/sudoers.d/90-tester && chmod 440 /etc/sudoers.d/90-tester'",
        "curtin in-target -- sh -c 'printf \"[daemon]\\nAutomaticLoginEnable=true\\nAutomaticLogin=tester\\n\" > /etc/gdm3/custom.conf'",
        "curtin in-target -- touch /var/lib/linuxvm-harness-installed",
        "sync",
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
        '  error-commands:',
        '    - ' + json.dumps("sh -c 'echo HARNESS_INSTALLER_FAILED > /dev/ttyAMA0; tail -n 100 /var/log/installer/subiquity-server-debug.log > /dev/ttyAMA0'"),
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
            progress = json.loads((directory / 'summary.json').read_text()).get('phases', {}) if (directory / 'summary.json').exists() else {}
            booted = 'install' in progress or (serial.exists() and 'Linux version' in serial.read_text(errors='replace'))
            wait_for('graceful shutdown', stopped, 90 if booted else 10, folder / 'logs')
        except TimeoutError:
            run([CTL, 'stop', vm_id, '--force'])
            wait_for('forced shutdown', stopped, 30, folder / 'logs')
    if (folder / 'logs').exists():
        destination = directory / ('vm-logs-final' if (directory / 'vm-logs').exists() else 'vm-logs')
        shutil.copytree(folder / 'logs', destination, dirs_exist_ok=True)
    shutil.rmtree(folder)  # Deliberately bypass Trash, but only after stop + ownership checks.
    summary_path = directory / 'summary.json'
    if summary_path.exists():
        saved = json.loads(summary_path.read_text())
        saved.update(cleaned_up=True, kept=False)
        write_json(summary_path, saved)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    relative = ROOT / 'test-media/ubuntu-26.04.1-desktop-arm64.iso'
    parser.add_argument('--iso', type=Path)
    parser.add_argument('--profile', choices=('ubuntu', 'fedora'))
    parser.add_argument('--desktop', choices=('gnome', 'plasma'),
                        help='Ubuntu desktop (default: gnome); Fedora uses its image desktop')
    parser.add_argument('--rpm', type=Path)
    parser.add_argument('--deb', type=Path)
    parser.add_argument('--keep', action='store_true')
    parser.add_argument('--install-timeout', type=int, default=3600)
    parser.add_argument('--boot-timeout', type=int, default=600)
    parser.add_argument('--plasma-timeout', type=int, default=3600)
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args(argv)
    if args.install_timeout <= 0 or args.boot_timeout <= 0 or args.plasma_timeout <= 0:
        parser.error('phase timeouts must be positive')
    if args.profile == 'fedora' and args.iso is None:
        parser.error('--iso is required for Fedora')
    args.iso = args.iso or relative
    try:
        profile = fedora.detect_profile(args.iso, args.profile)
    except ValueError as error:
        parser.error(str(error))
    if profile == 'fedora' and args.desktop is not None:
        parser.error('--desktop applies only to Ubuntu; Fedora uses the desktop from its image')
    if profile == 'ubuntu' and args.desktop is None:
        args.desktop = 'gnome'
    args.profile = profile
    if (args.deb and profile != 'ubuntu') or (args.rpm and profile != 'fedora'):
        parser.error('--deb requires Ubuntu; --rpm requires Fedora')
    if any(path and not path.is_file() for path in (args.iso, args.deb, args.rpm)):
        parser.error('ISO/package does not exist')
    return args


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    args = parse_args()
    profile = args.profile
    # Serialize harness launches across worktrees on this Mac. Keep the lock
    # file descriptor alive until main returns; do not unlink a locked inode.
    host_lock = open(Path(tempfile.gettempdir()) / f'linuxvm-harness-{os.getuid()}.lock', 'a')
    try:
        fcntl.flock(host_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('Another fresh-install harness is already running')
    # Fail closed rather than starting alongside a user VM, including a UTM QEMU.
    processes = run(['ps', '-axo', 'comm=']).stdout
    if any('qemu-system-' in line for line in processes.splitlines()):
        parser.error('A QEMU VM is already running; stop it yourself before using this harness')
    directory = (args.run_dir or ROOT / 'harness-runs' / time.strftime('%Y%m%d-%H%M%S')).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    directory.chmod(0o700)
    summary = {'profile': profile, 'run_dir': str(directory), 'phases': {}, 'success': False}
    if profile == 'ubuntu':
        summary['desktop'] = args.desktop
    started = time.monotonic()
    server = thread = execute = http_log = None
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
                output = [(part.decode(errors='replace') if isinstance(part, bytes) else part or '')
                          for part in (error.stdout, error.stderr)]
                (directory / (name + '-error.log')).write_text(''.join(output))
            raise
        finally:
            summary['phases'][name] = round(time.monotonic() - before, 3)
            write_json(directory / 'summary.json', summary)
    try:
        with phase('seed'):
            run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', '', '-f', directory / 'id_ed25519'])
            password_hash = run(['/opt/homebrew/bin/openssl', 'passwd', '-6', '-stdin'], input=secrets.token_urlsafe(32) + '\n').stdout.strip()
            if profile == 'fedora':
                (directory / 'ks.cfg').write_text(fedora.kickstart((directory / 'id_ed25519.pub').read_text(), password_hash))
            else:
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
            write_json(directory / 'connection.json', {'port': ssh_port, 'key': 'id_ed25519', 'user': 'root' if profile == 'fedora' else 'tester', 'vm_id': vm_id})
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
            menu_text = 'Start Fedora-' if profile == 'fedora' else 'Try or Install Ubuntu'
            wait_for('GRUB menu', lambda: menu_text in serial_text(), 180, serial)
            spec = importlib.util.spec_from_file_location('qmp_type', ROOT / 'scripts/qmp-type.py')
            qmp_type = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(qmp_type)
            execute = qmp_type.qmp(qmp_type.control_socket(vm_id))
            if profile == 'fedora':
                execute('send-key', keys=qmp_type.chord('up'), **{'hold-time': 80})
                time.sleep(1)
            execute('send-key', keys=qmp_type.chord('e'), **{'hold-time': 80})
            time.sleep(1.5)
            lines, cursor_row, _ = screen(serial_text())
            linux_row = next((i for i, line in enumerate(lines) if re.match(r'\s*linux\s', line[2:])), None)
            if linux_row is None:
                raise RuntimeError(f'GRUB linux line not found; inspect {serial}')
            for key in [*(['down'] * (linux_row - cursor_row) if linux_row >= cursor_row else ['up'] * (cursor_row - linux_row)), 'end']:
                execute('send-key', keys=qmp_type.chord(key), **{'hold-time': 80})
                time.sleep(1)
            if profile == 'fedora':
                kernel_args = fedora.grub_arguments((directory / 'id_ed25519.pub').read_text())
            else:
                kernel_args = f' autoinstall ds=nocloud-net\\;s=http://10.0.2.2:{port}/ console=ttyAMA0'
            for char in kernel_args:
                execute('send-key', keys=qmp_type.character(char), **{'hold-time': 40})
                time.sleep(.08)
            if profile == 'fedora':
                def echoed():
                    try:
                        return kernel_args.strip() in editor_linux_line(serial_text())
                    except ValueError:
                        return False
                try:
                    wait_for('GRUB argument echo', echoed, 60, directory / 'grub-edit.log')
                finally:
                    (directory / 'grub-edit.log').write_text(serial_text())
            else:
                time.sleep(2)
            # Reconstruct the editor's cursor-addressed screen and wrapped line.
            edited = serial_text()
            (directory / 'grub-edit.log').write_text(edited)
            edited_line = editor_linux_line(edited)
            (directory / 'grub-linux-line.txt').write_text(edited_line + '\n')
            if kernel_args.strip() not in edited_line:
                raise RuntimeError(f'Could not verify GRUB linux arguments; inspect {directory / "grub-edit.log"}')
            execute('send-key', keys=qmp_type.chord('ctrl-x'), **{'hold-time': 80})
            # Keep this connection to observe the real reset event. Close it
            # before linuxvmctl needs the same single-client control socket.
        if profile == 'fedora':
            execute.close()
            execute = None
            with phase('live_ssh'):
                wait_for('Fedora live root SSH', lambda: guest.ssh('true', check=False, timeout=15).returncode == 0,
                         args.boot_timeout, serial)
            with phase('install'):
                fedora.install(guest, vm_id, directory, args.install_timeout)
            with phase('installer_reboot'):
                run([CTL, 'set', vm_id, '--iso', 'none'])
                connection_path = directory / 'connection.json'
                connection = json.loads(connection_path.read_text())
                connection['user'] = 'tester'
                write_json(connection_path, connection)
                guest = Guest.from_run(directory)
                run([CTL, 'start', vm_id])
        else:
            with phase('install'):
                def target_installed():
                    text = serial_text()
                    if 'Kernel panic - not syncing' in text or re.search(r'(?m)^HARNESS_INSTALLER_FAILED\r?$', text):
                        raise RuntimeError(f'Installer failed; inspect {serial}')
                    if 'GET /installation-complete ' in (directory / 'http.log').read_text():
                        return True
                    try:
                        event = execute.next_event(.01)
                        with (directory / 'qmp-events.jsonl').open('a') as out:
                            out.write(json.dumps(event) + '\n')
                        if event.get('event') == 'RESET':
                            raise RuntimeError(f'Unexpected reset before installation completed; inspect {serial}')
                    except TimeoutError:
                        pass
                    return False
                wait_for('installer late commands', target_installed, args.install_timeout, serial)
            with phase('installer_reboot'):
                deadline = time.monotonic() + args.boot_timeout
                removal_prompt = False
                while True:
                    if 'Kernel panic - not syncing' in serial_text():
                        raise RuntimeError(f'Installer kernel panic; inspect {serial}')
                    if 'Please remove the installation medium' in serial_text():
                        removal_prompt = True
                        break
                    try:
                        event = execute.next_event(1)
                        with (directory / 'qmp-events.jsonl').open('a') as out:
                            out.write(json.dumps(event) + '\n')
                        if event.get('event') == 'RESET':
                            break
                    except TimeoutError:
                        pass
                    if time.monotonic() > deadline:
                        raise TimeoutError(f'Installer reboot timed out; inspect {serial}')
                execute.close()
                execute = None
                run([CTL, 'eject', vm_id])
                if removal_prompt:
                    execute = qmp_type.qmp(qmp_type.control_socket(vm_id))
                    execute('send-key', keys=qmp_type.chord('ret'), **{'hold-time': 80})
                    execute.close()
                    execute = None
        with phase('first_boot'):
            def installed():
                result = guest.ssh('test -f /var/lib/linuxvm-harness-installed', check=False, timeout=15)
                with (directory / 'ssh-wait.log').open('a') as out:
                    out.write(result.stderr)
                return result.returncode == 0
            wait_for('installed system SSH', installed, args.boot_timeout, directory / 'ssh-wait.log')
        if profile == 'ubuntu' and args.desktop == 'plasma':
            with phase('plasma'):
                install_plasma(guest, directory, args.plasma_timeout)
        with phase('guest_tools'):
            if args.rpm:
                guest.put(args.rpm, '/tmp/linuxvm-harness.rpm')
                result = guest.ssh('sudo dnf install -y /tmp/linuxvm-harness.rpm', timeout=600)
            elif args.deb:
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
            command = session_check(args.desktop)
            def ready():
                result = guest.ssh(command, check=False, timeout=20)
                (directory / 'session.log').write_text(result.stdout + result.stderr)
                return result.returncode == 0
            wait_for('desktop Wayland and integration services', ready, 180, directory / 'session.log')
            report = ENVIRONMENT_REPORT
            if profile == 'ubuntu' and args.desktop == 'plasma':
                report += PLASMA_ENVIRONMENT_REPORT
            environment = guest.ssh(report)
            (directory / 'guest-environment.txt').write_text(environment.stdout + environment.stderr)
            summary['success'] = True
            say('Fresh install passed; desktop Wayland and guest integration are active.')
    except BaseException as error:
        summary['error'] = f'{type(error).__name__}: {error}'
        say(summary['error'])
        raise
    finally:
        if execute:
            execute.close()
        if server:
            if thread and thread.is_alive():
                server.shutdown()
                thread.join(timeout=5)
            server.server_close()
        if http_log:
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
