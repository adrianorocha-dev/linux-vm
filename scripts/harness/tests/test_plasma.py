"""Ubuntu desktop selection and Plasma installation, without contacting a VM."""
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fresh_install


class DesktopArgumentsTests(unittest.TestCase):
    def test_defaults_and_explicit_desktops(self):
        with patch.object(Path, 'is_file', return_value=True):
            args = fresh_install.parse_args([])
            self.assertEqual((args.profile, args.desktop, args.plasma_timeout), ('ubuntu', 'gnome', 3600))
            for desktop in ('gnome', 'plasma'):
                args = fresh_install.parse_args(['--desktop', desktop, '--plasma-timeout', '4200'])
                self.assertEqual(args.desktop, desktop)
                self.assertEqual(args.plasma_timeout, 4200)
            args = fresh_install.parse_args(['--iso', 'Fedora-KDE.iso'])
            self.assertEqual((args.profile, args.desktop), ('fedora', None))

    def test_fedora_rejects_desktop_with_auto_or_explicit_profile(self):
        for profile in ([], ['--profile', 'fedora']):
            for desktop in ('gnome', 'plasma'):
                with self.subTest(profile=profile, desktop=desktop), contextlib.redirect_stderr(io.StringIO()) as err:
                    with self.assertRaises(SystemExit) as exit:
                        fresh_install.parse_args(['--iso', 'Fedora-KDE.iso', *profile, '--desktop', desktop])
                    self.assertEqual(exit.exception.code, 2)
                    self.assertIn('--desktop applies only to Ubuntu', err.getvalue())

    def test_plasma_timeout_must_be_positive(self):
        for timeout in ('0', '-1'):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit):
                    fresh_install.parse_args(['--plasma-timeout', timeout])
                self.assertIn('phase timeouts must be positive', err.getvalue())


class PlasmaInstallTests(unittest.TestCase):
    def test_default_session_check_is_unchanged(self):
        self.assertEqual(fresh_install.session_check('gnome'), fresh_install.SESSION_CHECK)
        self.assertEqual(fresh_install.session_check(None), fresh_install.SESSION_CHECK)

    def test_command_preserves_gdm_and_selects_plasma_wayland(self):
        command = fresh_install.PLASMA_INSTALL
        self.assertTrue(command.startswith('set -eu\n'))
        expected = [
            'sudo apt-get update -q',
            'echo "debconf shared/default-x-display-manager select gdm3" | sudo debconf-set-selections',
            'sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q kubuntu-desktop',
            'sudo mkdir -p /var/lib/AccountsService/users',
            r'printf "[User]\nSession=plasma\nSessionType=wayland\nSystemAccount=false\n" | sudo tee /var/lib/AccountsService/users/tester',
        ]
        for line in expected:
            self.assertIn(line, command.splitlines())
        self.assertEqual([command.index(line) for line in expected], sorted(command.index(line) for line in expected))

    def test_logs_and_timeout_on_success_failure_and_timeout(self):
        cases = [
            (None, 'apt outputwarning'),
            (subprocess.CalledProcessError(100, 'ssh', output='apt failed', stderr='error'), 'apt failederror'),
            (subprocess.TimeoutExpired('ssh', 42, output=b'partial apt output', stderr=b'timeout'), 'partial apt outputtimeout'),
        ]
        for error, expected in cases:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as temp:
                guest = Mock()
                guest.ssh.return_value = SimpleNamespace(stdout='apt output', stderr='warning')
                guest.ssh.side_effect = error
                if error:
                    with self.assertRaises(type(error)):
                        fresh_install.install_plasma(guest, Path(temp), 42)
                else:
                    fresh_install.install_plasma(guest, Path(temp), 42)
                guest.ssh.assert_called_once_with(fresh_install.PLASMA_INSTALL, timeout=42)
                self.assertEqual((Path(temp) / 'plasma-install.log').read_text(), expected)

    def test_environment_records_display_manager_and_package_versions(self):
        report = fresh_install.PLASMA_ENVIRONMENT_REPORT
        self.assertIn('cat /etc/X11/default-display-manager', report)
        self.assertIn('dpkg-query -W kubuntu-desktop plasma-workspace kwin-wayland', report)
