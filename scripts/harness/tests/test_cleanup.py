"""Exercise deletion guards against temporary folders, never real VMs."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fresh_install


class CleanupTests(unittest.TestCase):
    def setup_folders(self, base, vm_id, name='harness-unit-test', actual_name=None):
        run_dir = base / 'run'
        run_dir.mkdir()
        (run_dir / 'owned-vm.json').write_text(json.dumps({'id': vm_id, 'name': name}))
        (run_dir / 'summary.json').write_text(json.dumps({'kept': True}))
        root = base / 'VMs'
        vm = root / vm_id
        vm.mkdir(parents=True)
        (vm / 'config.json').write_text(json.dumps({'id': vm_id, 'name': actual_name or name}))
        (vm / 'logs').mkdir()
        (vm / 'logs/serial.log').write_text('unit test log')
        return root, run_dir, vm

    def test_protected_vm_rejected_before_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root, run_dir, vm = self.setup_folders(Path(temp), fresh_install.PROTECTED)
            with patch.object(fresh_install, 'VM_ROOT', root), patch.object(fresh_install, 'run') as command:
                with self.assertRaisesRegex(RuntimeError, 'protected'):
                    fresh_install.cleanup(run_dir)
                command.assert_not_called()
                self.assertTrue(vm.exists())

    def test_renamed_vm_rejected_before_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root, run_dir, vm = self.setup_folders(Path(temp), '11111111-1111-4111-8111-111111111111', actual_name='Ubuntu')
            with patch.object(fresh_install, 'VM_ROOT', root), patch.object(fresh_install, 'run') as command:
                with self.assertRaisesRegex(RuntimeError, 'ownership'):
                    fresh_install.cleanup(run_dir)
                command.assert_not_called()
                self.assertTrue(vm.exists())

    def test_owned_stopped_vm_removed_with_logs_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root, run_dir, vm = self.setup_folders(Path(temp), '11111111-1111-4111-8111-111111111111')
            with patch.object(fresh_install, 'VM_ROOT', root), patch.object(fresh_install, 'run') as command:
                command.return_value.stdout = 'stopped\n'
                fresh_install.cleanup(run_dir)
            self.assertFalse(vm.exists())
            self.assertEqual((run_dir / 'vm-logs/serial.log').read_text(), 'unit test log')
            summary = json.loads((run_dir / 'summary.json').read_text())
            self.assertTrue(summary['cleaned_up'])
            self.assertFalse(summary['kept'])


if __name__ == '__main__':
    unittest.main()
