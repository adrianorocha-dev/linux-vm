"""Touchpad contact lifecycle checks on a harness-owned VM, replayed through QMP
multi-touch events (see REPORT.md). They bypass the Mac trackpad, Cocoa's gesture
translation and focus handling; they test what the guest sees when the VM pauses,
resumes or reboots in the middle of a gesture."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from common import CTL, ROOT, Guest, run, wait_for, write_json
from soak import READY, owned_vm, parse_status

HERE = Path(__file__).resolve().parent
CENTER = 16384


def load_qmp():
    spec = importlib.util.spec_from_file_location('qmp_type', ROOT / 'scripts/qmp-type.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contact_events(radius=125, y=CENTER, down=True):
    """One sync frame for both slots: two contacts `radius` either side of the
    centre at height `y`, or the release of both."""
    events = []
    for slot in (0, 1):
        data = {'type': 'update' if down else 'end', 'slot': slot,
                'tracking-id': slot if down else -1, 'axis': 'x', 'value': 0}
        events.append({'type': 'mtt', 'data': data})
        if down:
            for axis, value in (('x', CENTER + (radius if slot else -radius)), ('y', y)):
                events.append({'type': 'mtt', 'data': {**data, 'type': 'data', 'axis': axis, 'value': value}})
    return events


def evaluate(analysis, expect):
    """Problems in an analyze-input result against the scenario's expectations."""
    problems = []
    if analysis.get('contacts_down_at_end'):
        problems.append(f"contacts still down at the end: {analysis['contacts_down_at_end']}")
    for anomaly in analysis.get('anomalies', []):
        problems.append(f"anomaly {anomaly['type']}")
    scrolls = analysis.get('scroll_sequences', [])
    if expect.get('scroll') and not scrolls:
        problems.append('no scroll recognised')
    problems += [f'scroll at {s["start_time"]:.2f}s did not end with a stop' for s in scrolls if not s['ends_with_scroll_stop']]
    if expect.get('pinch') and not analysis.get('pinch_sequences'):
        problems.append('no pinch recognised')
    if not analysis.get('pinch_balanced', True):
        problems.append('pinch begin/end unbalanced')
    if not analysis.get('contact_state_observed', True):
        problems.append('raw contact state not observed')
    return problems


class Lifecycle:
    def __init__(self, args):
        self.args = args
        self.run_dir = Path(args.run).resolve()
        self.vm_id, self.folder = owned_vm(self.run_dir)
        self.guest = Guest.from_run(self.run_dir)
        self.out = Path(args.output_dir) if args.output_dir else self.run_dir / 'touch-lifecycle'
        self.out.mkdir(parents=True, exist_ok=True)
        self.qmp = load_qmp()
        self.execute = None
        self.paused_by = None

    def connect(self):
        self.execute = self.qmp.qmp(self.qmp.control_socket(self.vm_id))

    def close(self):
        if self.execute:
            self.execute.close()
            self.execute = None

    def send(self, **kwargs):
        self.execute('input-send-event', events=contact_events(**kwargs))

    def release(self):
        self.send(down=False)

    def scroll(self, steps, start=0, interval=.02):
        for i in range(start, start + steps):
            self.send(y=CENTER + i * 3)
            time.sleep(interval)

    def pinch(self, steps, interval=.02):
        for radius in range(125, 125 + steps * 5, 5):
            self.send(radius=radius)
            time.sleep(interval)

    def pause(self, how):
        self.paused_by = how
        if how == 'qmp':
            self.execute('stop')
        else:
            os.kill(parse_status(run([CTL, 'status', self.vm_id]).stdout)['supervisor'], signal.SIGUSR1)
            wait_for('VM paused', lambda: parse_status(run([CTL, 'status', self.vm_id]).stdout)['state'] == 'paused', 15, self.out)

    def resume(self, how):
        self.paused_by = None
        if how == 'qmp':
            self.execute('cont')
        else:
            os.kill(parse_status(run([CTL, 'status', self.vm_id]).stdout)['supervisor'], signal.SIGUSR2)
            wait_for('VM running', lambda: parse_status(run([CTL, 'status', self.vm_id]).stdout)['state'] == 'running', 15, self.out)

    def recorded(self, name, seconds, body):
        """Runs `body` while the guest records input; returns the analysis."""
        output = self.out / f'{name}.json'
        record = subprocess.Popen([str(HERE / 'record-input'), '--run', str(self.run_dir), '--seconds', str(seconds),
                                   '--output', str(output)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        time.sleep(2)
        self.connect()
        try:
            body()
        finally:
            if self.paused_by:
                self.resume(self.paused_by)
            try:
                self.release()
            except Exception:
                pass
            self.close()
        _, errors = record.communicate(timeout=seconds + 60)
        if record.returncode:
            raise RuntimeError(f'{name}: input recording failed: {errors.strip()[-400:]}')
        return json.loads(output.with_suffix('.analysis.json').read_text())

    def scenarios(self):
        sleep_path = 'signals' if self.args.sleep_signals else 'qmp'

        def baseline():
            self.scroll(40)
            self.release()
            time.sleep(.4)
            self.pinch(30)
            self.release()

        def pause_release_dropped(how):
            def body():
                self.scroll(20)
                self.pause(how)
                try:
                    self.release()
                except RuntimeError as error:
                    # QEMU refuses input while paused, as Cocoa's lifts are lost then.
                    if 'not running' not in str(error):
                        raise
                time.sleep(2)
                self.resume(how)
                time.sleep(1)
            return body

        def pause_continue():
            self.scroll(20)
            self.pause('qmp')
            time.sleep(2)
            self.resume('qmp')
            self.scroll(20, start=20)
            self.release()

        def repeat():
            for _ in range(15):
                self.scroll(8)
                self.release()
                time.sleep(.05)
                self.pinch(8)
                self.release()
                time.sleep(.05)

        def scroll_into_pinch():
            self.scroll(20)
            for radius in range(125, 300, 5):
                self.send(radius=radius, y=CENTER + 57)
                time.sleep(.02)
            self.release()

        items = [('baseline', 10, baseline, {'scroll': True, 'pinch': True}),
                 ('pause-release-dropped-qmp', 12, pause_release_dropped('qmp'), {'scroll': True}),
                 ('pause-continue', 12, pause_continue, {'scroll': True}),
                 ('repeat', 14, repeat, {'scroll': True, 'pinch': True}),
                 ('scroll-into-pinch', 10, scroll_into_pinch, {'scroll': True, 'informational': True})]
        if sleep_path == 'signals':
            items.insert(2, ('pause-release-dropped-sleep', 16, pause_release_dropped('signals'), {'scroll': True}))
        return items

    def reboot_with_contacts_down(self):
        boot_id = self.guest.ssh('cat /proc/sys/kernel/random/boot_id').stdout.strip()
        self.connect()
        try:
            self.scroll(10)
            self.guest.ssh('sudo systemctl reboot', check=False, timeout=20)
            time.sleep(3)
        finally:
            self.close()  # Contacts deliberately left down across the reboot.
        wait_for('guest reboot', lambda: (r := self.guest.ssh('cat /proc/sys/kernel/random/boot_id', check=False, timeout=15)).returncode == 0
                 and r.stdout.strip() not in ('', boot_id), 300, self.out)
        wait_for('desktop session', lambda: self.guest.ssh(READY, check=False, timeout=20).returncode == 0, 300, self.out)
        time.sleep(5)

    def main(self):
        results = []
        for name, seconds, body, expect in self.scenarios():
            analysis = self.recorded(name, seconds, body)
            problems = evaluate(analysis, expect)
            results.append({'scenario': name, 'informational': bool(expect.get('informational')), 'problems': problems,
                            'scrolls': len(analysis.get('scroll_sequences', [])), 'pinches': len(analysis.get('pinch_sequences', []))})
            print(f"{name}: {'ok' if not problems else '; '.join(problems)}", flush=True)
            time.sleep(1)
        if self.args.reboot:
            self.reboot_with_contacts_down()
            analysis = self.recorded('after-reboot-with-contacts-down', 10, lambda: (self.scroll(40), self.release()))
            problems = evaluate(analysis, {'scroll': True})
            results.append({'scenario': 'after-reboot-with-contacts-down', 'informational': False, 'problems': problems,
                            'scrolls': len(analysis.get('scroll_sequences', [])), 'pinches': 0})
            print(f"after-reboot-with-contacts-down: {'ok' if not problems else '; '.join(problems)}", flush=True)
        failed = [r for r in results if r['problems'] and not r['informational']]
        write_json(self.out / 'summary.json', {'vm': self.vm_id, 'results': results, 'failed': len(failed)})
        print(f'{len(results) - len(failed)}/{len(results)} scenarios passed; details in {self.out}', flush=True)
        return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Touchpad contact lifecycle checks through QMP replay')
    parser.add_argument('--run', required=True, help='Harness run directory of a running, kept VM')
    parser.add_argument('--output-dir')
    parser.add_argument('--sleep-signals', action='store_true',
                        help='Also pause through the supervisor (it must run with LINUXVM_DEBUG_SLEEP_SIGNALS=1)')
    parser.add_argument('--reboot', action='store_true', help='Also reboot the guest with contacts down, then check a fresh scroll')
    args = parser.parse_args(argv)
    sys.exit(Lifecycle(args).main())
