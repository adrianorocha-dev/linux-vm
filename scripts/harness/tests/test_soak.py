"""Parsing and guards of the lifecycle soak, without a VM."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import soak


class SoakParsingTests(unittest.TestCase):
    def test_status_with_and_without_run(self):
        running = soak.parse_status('running\nsince 2026-11-02 18:38:30 +0000, supervisor 52566, QEMU 52570\nguest tools 0.2.0, extension active, received x\n')
        self.assertEqual(running, {'state': 'running', 'supervisor': 52566, 'qemu': 52570})
        self.assertEqual(soak.parse_status('stopped\n'), {'state': 'stopped'})
        self.assertEqual(soak.parse_status('starting\nsince x, supervisor 7, QEMU -\n')['qemu'], None)

    def test_health_flags_only_our_units_and_filesystem_recovery(self):
        health = soak.parse_health(
            'system-failed: snapd.service linuxvm-timezone.service \n'
            'user-failed: \n'
            'boot: 1234\n'
            'EXT4-fs (vda2): mounted filesystem with ordered data mode\n'
            'EXT4-fs (vda2): orphan cleanup on readonly fs\n')
        self.assertEqual(health['boot_id'], '1234')
        self.assertEqual(soak.health_problems(health), [
            'failed unit linuxvm-timezone.service',
            'filesystem: EXT4-fs (vda2): orphan cleanup on readonly fs'])

    def test_log_problems(self):
        clean = '[t] Signal 15: asking Linux to shut down\n[t] QEMU exited with status 0\n'
        self.assertEqual(soak.log_problems(clean), [])
        forced = '[t] Linux did not shut down within 90 seconds: stopping QEMU\n[t] The audio bridge exited (status 1); restarting (1/5)\n'
        self.assertEqual(len(soak.log_problems(forced)), 2)

    def test_report_must_be_newer_than_the_boot(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'guest.json').write_text(json.dumps({'package': '0.2.0', 'extension': 'active', 'receivedAt': '2026-11-02T17:02:01Z'}))
            self.assertIsNotNone(soak.report_received_since(folder, datetime(2026, 11, 2, 17, 2, 1, 500000, tzinfo=timezone.utc)))
            self.assertIsNone(soak.report_received_since(folder, datetime(2026, 11, 2, 17, 2, 2, tzinfo=timezone.utc)))
            self.assertIsNone(soak.report_received_since(folder / 'missing', datetime.now(timezone.utc)))


class SoakOwnershipTests(unittest.TestCase):
    def folders(self, base, vm_id, owned_name='harness-unit', actual_name=None):
        run_dir = base / 'run'
        run_dir.mkdir()
        (run_dir / 'owned-vm.json').write_text(json.dumps({'id': vm_id, 'name': owned_name}))
        vm = base / 'VMs' / vm_id
        vm.mkdir(parents=True)
        (vm / 'config.json').write_text(json.dumps({'id': vm_id, 'name': actual_name or owned_name}))
        return base / 'VMs', run_dir

    def test_protected_and_foreign_vms_are_refused(self):
        cases = [(soak.PROTECTED, 'harness-unit', None, 'protected'),
                 ('11111111-1111-4111-8111-111111111111', 'harness-unit', 'Ubuntu', 'ownership'),
                 ('22222222-2222-4222-8222-222222222222', 'my-vm', None, 'ownership')]
        for vm_id, owned, actual, message in cases:
            with tempfile.TemporaryDirectory() as temp:
                root, run_dir = self.folders(Path(temp), vm_id, owned, actual)
                with patch.object(soak, 'VM_ROOT', root):
                    with self.assertRaisesRegex(RuntimeError, message):
                        soak.owned_vm(run_dir)

    def test_owned_vm_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            vm_id = '33333333-3333-4333-8333-333333333333'
            root, run_dir = self.folders(Path(temp), vm_id)
            with patch.object(soak, 'VM_ROOT', root):
                self.assertEqual(soak.owned_vm(run_dir)[0], vm_id)


if __name__ == '__main__':
    unittest.main()
