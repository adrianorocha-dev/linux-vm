"""Repeated lifecycle checks on a harness-owned VM: start, guest reboot, simulated
Mac sleep and shutdown, round after round. Python 3.14 standard library only."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
import uuid

from common import CTL, PROTECTED, SESSION, VM_ROOT, Guest, run, wait_for, write_json

FORCED_STOP = re.compile(r'did not shut down within|Second signal: stopping QEMU|: stopping QEMU$', re.M)
BRIDGE_TROUBLE = re.compile(r'bridge exited|bridge is unavailable|Cannot start the .* bridge', re.M)
FS_RECOVERY = re.compile(r'EXT4-fs .*(recover|orphan|error)', re.I)

READY = SESSION + r'''set -eu
found=0
for s in $(loginctl list-sessions --no-legend | awk '{print $1}'); do
 [ "$(loginctl show-session "$s" -p Name --value)" = tester ] || continue
 [ "$(loginctl show-session "$s" -p Type --value)" = wayland ] || continue
 [ "$(loginctl show-session "$s" -p Active --value)" = yes ] || continue
 found=1
done
[ "$found" = 1 ]
gnome-extensions info clipboard@linuxvm.dev | grep -q 'State: ACTIVE'
systemctl --user is-active linuxvm-clipboard linuxvm-audio linuxvm-status >/dev/null
systemctl is-active linuxvm-timezone.service linuxvm-clock-recovery.timer >/dev/null
'''

HEALTH = SESSION + r'''echo "system-failed: $(systemctl --failed --no-legend --plain | awk '{print $1}' | tr '\n' ' ')"
echo "user-failed: $(systemctl --user --failed --no-legend --plain | awk '{print $1}' | tr '\n' ' ')"
echo "boot: $(cat /proc/sys/kernel/random/boot_id)"
journalctl -b -k --no-pager -o cat 2>/dev/null | grep -E 'EXT4-fs' || true
'''


def owned_vm(directory):
    """The run's VM, only if it is the exact harness VM this run created."""
    owned = json.loads((Path(directory) / 'owned-vm.json').read_text())
    vm_id = owned['id']
    if str(uuid.UUID(vm_id)).upper() != vm_id or vm_id == PROTECTED:
        raise RuntimeError('Refusing: invalid or protected VM id')
    folder = VM_ROOT / vm_id
    config = json.loads((folder / 'config.json').read_text())
    if config.get('id') != vm_id or config.get('name') != owned['name'] or not owned['name'].startswith('harness-'):
        raise RuntimeError('Refusing: ownership/name mismatch')
    return vm_id, folder


def parse_status(text):
    lines = text.splitlines()
    status = {'state': lines[0].strip() if lines else 'unknown'}
    for line in lines[1:]:
        if match := re.search(r'supervisor (\d+), QEMU (\d+|-)', line):
            status['supervisor'] = int(match.group(1))
            status['qemu'] = int(match.group(2)) if match.group(2) != '-' else None
    return status


def parse_health(text):
    health = {'system_failed': [], 'user_failed': [], 'boot_id': None, 'fs_recovery': []}
    for line in text.splitlines():
        if line.startswith('system-failed:'):
            health['system_failed'] = line.split(':', 1)[1].split()
        elif line.startswith('user-failed:'):
            health['user_failed'] = line.split(':', 1)[1].split()
        elif line.startswith('boot:'):
            health['boot_id'] = line.split(':', 1)[1].strip()
        elif FS_RECOVERY.search(line):
            health['fs_recovery'].append(line.strip())
    return health


def health_problems(health):
    problems = [f'failed unit {unit}' for unit in health['system_failed'] + health['user_failed'] if 'linuxvm' in unit]
    problems += [f'filesystem: {line}' for line in health['fs_recovery']]
    return problems


def log_problems(text):
    problems = [f'forced stop: {line}' for line in text.splitlines() if FORCED_STOP.search(line)]
    problems += [f'bridge: {line}' for line in text.splitlines() if BRIDGE_TROUBLE.search(line)]
    return problems


def report_received_since(folder, since):
    """The guest.json report, if one arrived at or after `since` (aware datetime)."""
    try:
        report = json.loads((folder / 'guest.json').read_text())
        received = datetime.fromisoformat(report['receivedAt'].replace('Z', '+00:00'))
    except (OSError, ValueError, KeyError):
        return None
    return report if received >= since.replace(microsecond=0) else None


def clock_offset(guest):
    """Guest minus Mac wall clock, using the midpoint of the SSH round trip."""
    before = time.time()
    result = guest.ssh('date +%s.%N', check=False, timeout=15)
    after = time.time()
    if result.returncode != 0:
        return None
    return round(float(result.stdout.strip()) - (before + after) / 2, 3)


class Soak:
    def __init__(self, args):
        self.args = args
        self.run_dir = Path(args.run).resolve()
        self.vm_id, self.folder = owned_vm(self.run_dir)
        self.guest = Guest.from_run(self.run_dir)
        self.log = self.run_dir / 'soak.log'
        self.supervisor_log = self.folder / 'logs/supervisor.log'

    def say(self, message):
        line = f'[{datetime.now().strftime("%H:%M:%S")}] {message}'
        print(line, flush=True)
        with self.log.open('a') as out:
            out.write(line + '\n')

    def status(self):
        return parse_status(run([CTL, 'status', self.vm_id], check=False).stdout)

    def wait_state(self, state, timeout):
        wait_for(f'VM {state}', lambda: self.status()['state'] == state, timeout, self.supervisor_log)

    def log_offset(self):
        return self.supervisor_log.stat().st_size if self.supervisor_log.exists() else 0

    def log_since(self, offset):
        with self.supervisor_log.open('rb') as handle:
            handle.seek(offset)
            return handle.read().decode(errors='replace')

    def wait_ready(self, since):
        ready = lambda: self.guest.ssh(READY, check=False, timeout=20).returncode == 0
        wait_for('desktop session and guest tools', ready, self.args.boot_timeout, self.log)
        wait_for('guest status report', lambda: report_received_since(self.folder, since), 60, self.folder / 'guest.json')

    def check_boot(self, label, since, expect_boot=None):
        problems = []
        health = parse_health(self.guest.ssh(HEALTH, check=False, timeout=30).stdout)
        problems += health_problems(health)
        if expect_boot is not None and health['boot_id'] == expect_boot:
            problems.append('guest did not reboot')
        report = report_received_since(self.folder, since)
        if not report:
            problems.append('no guest status report since this boot')
        elif report.get('extension') != 'active':
            problems.append(f"extension {report.get('extension')}")
        offset = clock_offset(self.guest)
        if offset is None or abs(offset) > self.args.clock_tolerance:
            problems.append(f'guest clock offset {offset} s')
        return {'label': label, 'boot_id': health['boot_id'], 'clock_offset': offset,
                'report': report and {k: report.get(k) for k in ('package', 'shell', 'extension')},
                'failed_units': health['system_failed'] + health['user_failed'], 'problems': problems}

    def round(self, number):
        result = {'round': number, 'steps': [], 'problems': []}
        def step(entry):
            result['steps'].append(entry)
            result['problems'] += [f"{entry['label']}: {problem}" for problem in entry.get('problems', [])]
            self.say(f"round {number} {entry['label']}: " + ('ok' if not entry.get('problems') else '; '.join(entry['problems'])))

        offset = self.log_offset()
        started = time.monotonic()
        since = datetime.now(timezone.utc)
        environment = dict(os.environ, LINUXVM_DEBUG_SLEEP_SIGNALS='1')
        run([CTL, 'start', self.vm_id], env=environment, timeout=90)
        self.wait_ready(since)
        entry = self.check_boot('start', since)
        entry['seconds'] = round(time.monotonic() - started, 1)
        step(entry)
        pids = self.status()

        boot_id = entry['boot_id']
        since = datetime.now(timezone.utc)
        started = time.monotonic()
        self.guest.ssh('sudo systemctl reboot', check=False, timeout=20)
        wait_for('guest reboot', lambda: (r := self.guest.ssh('cat /proc/sys/kernel/random/boot_id', check=False, timeout=15)).returncode == 0
                 and r.stdout.strip() not in ('', boot_id), self.args.boot_timeout, self.log)
        self.wait_ready(since)
        entry = self.check_boot('reboot', since, expect_boot=boot_id)
        entry['seconds'] = round(time.monotonic() - started, 1)
        after = self.status()
        if (after.get('supervisor'), after.get('qemu')) != (pids.get('supervisor'), pids.get('qemu')):
            entry['problems'].append(f'supervisor or QEMU changed across the guest reboot: {pids} -> {after}')
        step(entry)

        supervisor = after['supervisor']
        os.kill(supervisor, signal.SIGUSR1)
        problems = []
        try:
            self.wait_state('paused', 15)
        except TimeoutError:
            problems.append('VM did not pause')
        time.sleep(self.args.sleep_seconds)
        os.kill(supervisor, signal.SIGUSR2)
        try:
            self.wait_state('running', 15)
        except TimeoutError:
            problems.append('VM did not resume')
        behind = clock_offset(self.guest)
        recovered_after = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = clock_offset(self.guest)
            if current is not None and abs(current) <= self.args.clock_tolerance:
                recovered_after = round(30 - (deadline - time.monotonic()), 1)
                break
            time.sleep(1)
        if recovered_after is None:
            problems.append(f'guest clock did not recover within 30 s (offset {behind} s just after wake)')
        health = parse_health(self.guest.ssh(HEALTH, check=False, timeout=30).stdout)
        problems += health_problems(health)
        step({'label': 'sleep', 'paused_seconds': self.args.sleep_seconds, 'offset_after_wake': behind,
              'clock_recovered_after': recovered_after, 'problems': problems})

        started = time.monotonic()
        run([CTL, 'stop', self.vm_id], check=False, timeout=30)
        problems = []
        try:
            self.wait_state('stopped', 150)
        except TimeoutError:
            problems.append('VM did not stop within 150 s')
        text = self.log_since(offset)
        problems += log_problems(text)
        if not re.search(r'QEMU exited with status 0\b', text):
            problems.append('QEMU did not exit with status 0')
        step({'label': 'shutdown', 'seconds': round(time.monotonic() - started, 1), 'problems': problems})
        return result

    def main(self):
        if self.status()['state'] != 'stopped':
            self.say('stopping the VM before the first round')
            run([CTL, 'stop', self.vm_id], check=False, timeout=30)
            self.wait_state('stopped', 150)
        summary = {'vm': self.vm_id, 'linuxvmctl': CTL, 'rounds': [], 'started': datetime.now(timezone.utc).isoformat()}
        output = Path(self.args.output) if self.args.output else self.run_dir / 'soak.json'
        for number in range(1, self.args.rounds + 1):
            try:
                summary['rounds'].append(self.round(number))
            except Exception as error:
                self.say(f'round {number} aborted: {error}')
                summary['rounds'].append({'round': number, 'problems': [f'aborted: {error}']})
                run([CTL, 'stop', self.vm_id], check=False, timeout=30)
                try:
                    self.wait_state('stopped', 150)
                except TimeoutError:
                    run([CTL, 'stop', self.vm_id, '--force'], check=False, timeout=30)
                    self.wait_state('stopped', 30)
            write_json(output, summary)
        failures = sum(1 for entry in summary['rounds'] if entry['problems'])
        summary['failed_rounds'] = failures
        write_json(output, summary)
        self.say(f'{self.args.rounds - failures}/{self.args.rounds} rounds passed; details in {output}')
        return 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Repeated start, reboot, simulated sleep and shutdown of a harness VM')
    parser.add_argument('--run', required=True, help='Harness run directory of a kept VM')
    parser.add_argument('--rounds', type=int, default=5)
    parser.add_argument('--sleep-seconds', type=int, default=30)
    parser.add_argument('--boot-timeout', type=int, default=300)
    parser.add_argument('--clock-tolerance', type=float, default=1.5)
    parser.add_argument('--output')
    args = parser.parse_args(argv)
    sys.exit(Soak(args).main())
