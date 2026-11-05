"""Fedora configuration and lifecycle checks; never contact a VM."""
import base64
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fedora

KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest'
HASH = '$6$random$hash'


class FedoraConfigurationTests(unittest.TestCase):
    def test_kickstart(self):
        text = fedora.kickstart(KEY + ' unwanted-comment\n', HASH)
        required = [
            'cmdline', 'liveimg --url=file:///run/initramfs/live/LiveOS/squashfs.img',
            'lang en_US.UTF-8', 'keyboard us', 'timezone UTC --utc', 'rootpw --lock',
            f'user --name=tester --gecos="Tester" --groups=wheel --iscrypted --password={HASH}',
            f'sshkey --username=tester "{KEY}"', 'ignoredisk --only-use=vda', 'zerombr',
            'clearpart --all --initlabel --drives=vda --disklabel=gpt',
            'autopart --type=btrfs --noswap', 'bootloader', 'firstboot --disable',
            'services --enabled=sshd', 'poweroff', '%post --erroronfail', '%end',
            "echo 'tester ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-tester",
            'chmod 440 /etc/sudoers.d/90-tester', 'mkdir -p /etc/gdm',
            "printf '[daemon]\\nAutomaticLoginEnable=True\\nAutomaticLogin=tester\\n' > /etc/gdm/custom.conf",
            'mkdir -p /etc/plasmalogin.conf.d',
            "printf '[Autologin]\\nUser=tester\\nSession=plasma.desktop\\n' > /etc/plasmalogin.conf.d/90-harness-autologin.conf",
            'mkdir -p /home/tester/.config', 'touch /home/tester/.config/gnome-initial-setup-done',
            'chown -R tester:tester /home/tester/.config', 'restorecon -R /home/tester/.config || true',
            'systemctl set-default graphical.target', 'touch /etc/plasma-setup-done',
            'touch /var/lib/linuxvm-harness-installed',
        ]
        for line in required:
            self.assertIn(line, text.splitlines())
        self.assertNotIn('unwanted-comment', text)
        self.assertNotIn('/Users/', text)
        self.assertNotIn('@', text)

    def test_grub_arguments(self):
        text = fedora.grub_arguments(KEY + ' unwanted-comment\n')
        prefix = ' console=ttyAMA0 systemd.wants=sshd.service systemd.set_credential_binary=ssh.authorized_keys.root:'
        self.assertTrue(text.startswith(prefix))
        self.assertEqual(base64.b64decode(text[len(prefix):]).decode(), KEY + '\n')
        self.assertNotIn('autoinstall', text)

    def test_profile_selection(self):
        for name in ('Fedora-Workstation-Live-44-1.7.aarch64.iso', 'Fedora-KDE-Desktop-Live-45-1.4.aarch64.iso'):
            self.assertEqual(fedora.detect_profile(Path('test-media') / name), 'fedora')
        self.assertEqual(fedora.detect_profile('ubuntu-26.04.1-desktop-arm64.iso'), 'ubuntu')
        self.assertEqual(fedora.detect_profile('renamed.iso', 'fedora'), 'fedora')
        with self.assertRaises(ValueError):
            fedora.detect_profile('unknown.iso')

    def test_log_failure_detection(self):
        for marker in ('CmdlineError', 'Traceback (most recent call last):', ' ERR storage failed'):
            self.assertEqual(fedora.anaconda_failure('INFO starting\n' + marker + '\n'), marker)
        self.assertIsNone(fedora.anaconda_failure('INFO no errors\nDEBUG error handling enabled'))

    def test_start_script(self):
        self.assertIn('export LANG=C.UTF-8 LC_ALL=C.UTF-8', fedora.START_SCRIPT)
        self.assertIn('exec anaconda --cmdline --kickstart /root/ks.cfg', fedora.START_SCRIPT)
        self.assertNotIn('--liveinst', fedora.START_SCRIPT)
        self.assertNotIn('pkill', fedora.START_SCRIPT)


class AnacondaLifecycleTests(unittest.TestCase):
    def test_poweroff_is_success_and_exit_is_failure(self):
        for output in ('HARNESS_ANACONDA_EXITED\n1\n', 'Traceback error', None):
            with self.subTest(output=output), tempfile.TemporaryDirectory() as temp:
                guest = Mock()
                guest.ssh.return_value = SimpleNamespace(stdout=output or '', stderr='', returncode=0)
                with patch.object(fedora, 'run', return_value=SimpleNamespace(stdout='stopped\n' if output is None else 'running\n')):
                    if output is None:
                        fedora.install(guest, 'test-id', Path(temp), 1)
                        guest.get.assert_not_called()
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'Anaconda failed'):
                            fedora.install(guest, 'test-id', Path(temp), 1)
                        self.assertEqual(guest.get.call_count, 2)
                start = guest.ssh.call_args_list[0].args[0]
                self.assertIn('nohup', start)
                self.assertIn('< /dev/null &', start)

    def test_timeout_collects_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            guest = Mock()
            guest.ssh.return_value = SimpleNamespace(stdout='', stderr='', returncode=0)
            with patch.object(fedora, 'wait_for', side_effect=TimeoutError('timed out')):
                with self.assertRaises(TimeoutError):
                    fedora.install(guest, 'test-id', Path(temp), 1)
            self.assertEqual(guest.get.call_count, 2)


class FedoraMainTests(unittest.TestCase):
    def test_fedora_orchestration_without_devices(self):
        import contextlib
        import io
        import fresh_install
        vm_id = '11111111-1111-4111-8111-111111111111'
        with tempfile.TemporaryDirectory() as temp, contextlib.ExitStack() as stack:
            base = Path(temp).resolve()
            iso = base / 'Fedora-test.iso'
            iso.touch()
            directory = base / 'run'
            vm_root = base / 'VMs'
            (vm_root / vm_id / 'logs').mkdir(parents=True)
            (vm_root / vm_id / 'logs/serial.log').write_text('Start Fedora-')
            calls = []
            def command(argv, **kwargs):
                calls.append([str(x) for x in argv])
                if argv[0] == 'ssh-keygen':
                    (directory / 'id_ed25519.pub').write_text(KEY + '\n')
                stdout = vm_id if 'create' in argv else HASH if 'passwd' in argv else ''
                return SimpleNamespace(stdout=stdout, stderr='', returncode=0)
            guest = Mock()
            guest.argv.return_value = ['ssh', 'mock-guest']
            guest.ssh.side_effect = lambda cmd, **kw: SimpleNamespace(
                stdout=('new' if kw.get('check') is False else 'old') if 'boot_id' in cmd else '',
                stderr='', returncode=0)
            qmp = Mock()
            qmp_module = Mock()
            qmp_module.qmp.return_value = qmp
            qmp_module.character.side_effect = lambda c: c
            qmp_module.chord.side_effect = lambda c: c
            for name, value in [('VM_ROOT', vm_root), ('run', command), ('free_port', lambda: 12345),
                                ('screen', lambda text: (['  linux /boot/linux'], 0, 0)),
                                ('editor_linux_line', lambda text: fedora.grub_arguments(KEY)),
                                ('wait_for', lambda label, predicate, *a: self.assertTrue(predicate(), label))]:
                stack.enter_context(patch.object(fresh_install, name, value))
            stack.enter_context(patch.object(fresh_install, 'open', create=True))
            stack.enter_context(patch.object(fresh_install.fcntl, 'flock'))
            stack.enter_context(patch.object(fresh_install.signal, 'signal'))
            stack.enter_context(patch.object(fresh_install.time, 'sleep'))
            stack.enter_context(patch.object(fresh_install.Guest, 'from_run', return_value=guest))
            stack.enter_context(patch.object(fresh_install.importlib.util, 'module_from_spec', return_value=qmp_module))
            stack.enter_context(patch.object(fresh_install.importlib.util, 'spec_from_file_location', return_value=Mock()))
            installer = stack.enter_context(patch.object(fedora, 'install'))
            stack.enter_context(patch.object(sys, 'argv', ['fresh-install', '--iso', str(iso), '--run-dir', str(directory), '--keep']))
            with contextlib.redirect_stdout(io.StringIO()):
                fresh_install.main()
            installer.assert_called_once_with(guest, vm_id, directory, 3600)
            self.assertEqual(json.loads((directory / 'connection.json').read_text())['user'], 'tester')
            self.assertTrue(json.loads((directory / 'summary.json').read_text())['success'])
            self.assertFalse((directory / 'seed').exists())
            self.assertIn([fresh_install.CTL, 'set', vm_id, '--iso', 'none'], calls)
            keys = [call.kwargs.get('keys') for call in qmp.call_args_list]
            self.assertEqual(keys[:2], ['up', 'e'])
            self.assertEqual(keys[-1], 'ctrl-x')
            keygen = next(c for c in calls if c[0] == 'ssh-keygen')
            self.assertEqual(keygen[keygen.index('-C') + 1], '')
