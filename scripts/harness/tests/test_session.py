"""Desktop session parsing and shell checks, without a guest."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common
import fresh_install
from session import kde_clipboard_active, parse_session_environment


class SessionTests(unittest.TestCase):
    def test_environment_parser_and_shell(self):
        for desktop, display in [('ubuntu:GNOME', 'wayland-0'), ('GNOME', 'wayland-0'), ('KDE', 'wayland-1')]:
            environment = f'WAYLAND_DISPLAY={display}\nXDG_CURRENT_DESKTOP={desktop}\nIGNORED=secret\n'
            self.assertEqual(parse_session_environment(environment), {'WAYLAND_DISPLAY': display, 'XDG_CURRENT_DESKTOP': desktop})
            # Exercise the exact shell prefix, with a fake user manager.
            script = 'systemctl() { printf %s ' + shlex.quote(environment) + '; }; ' + common.SESSION
            result = subprocess.run(['/bin/sh', '-c', script + 'printf "%s %s" "$WAYLAND_DISPLAY" "$XDG_CURRENT_DESKTOP"'], text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout, display + ' ' + desktop)
        self.assertEqual(parse_session_environment('XDG_CURRENT_DESKTOP="a b"\n'), {'XDG_CURRENT_DESKTOP': 'a b'})

    def test_clipboard_check_runs_same_code_in_guest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'linuxvm').mkdir()
            for text, expected in [(' {"state": "active"}', True), ('{"state":"inactive"}', False), ('{}', False), ('[]', False), ('null', False), ('invalid', False)]:
                self.assertEqual(kde_clipboard_active(text), expected)
                (root / 'linuxvm/clipboard.json').write_text(text)
                result = subprocess.run([sys.executable, '-c', common._SESSION_SOURCE, 'clipboard'], env=dict(os.environ, XDG_RUNTIME_DIR=temp), capture_output=True)
                self.assertEqual(result.returncode == 0, expected)


    def test_desktop_checks_reject_each_missing_unit(self):
        # Run the actual check body against local shell fakes, including the
        # real JSON parser. No loginctl/systemctl invocation reaches the host.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'linuxvm').mkdir()
            (root / 'linuxvm/clipboard.json').write_text('{"state":"active"}')
            extension = root / 'gnome-extensions'
            extension.write_text("#!/bin/sh\necho 'State: ACTIVE'\n")
            extension.chmod(0o755)
            for desktop, requested in [('KDE', None), ('ubuntu:GNOME', None), ('KDE', 'plasma'), ('ubuntu:GNOME', 'plasma')]:
                command = fresh_install.session_check(requested)
                self.assertTrue(command.startswith(common.SESSION_CHECK))
                body = command[len(common.SESSION):]
                units = ['linuxvm-clipboard', 'linuxvm-audio'] + (['linuxvm-status'] if desktop == 'KDE' else [])
                for failed in ['', *units]:
                    preamble = r'''
loginctl() {
 if [ "$1" = list-sessions ]; then echo '1 tester'; return; fi
 case "$4" in Name) echo tester ;; Type) echo wayland ;; Seat) echo seat0 ;; Active) echo yes ;; esac
}
systemctl() { [ "$3" != "$FAILED_UNIT" ]; }
'''
                    result = subprocess.run(['/bin/sh', '-c', preamble + body], env=dict(
                        os.environ, XDG_RUNTIME_DIR=temp, XDG_CURRENT_DESKTOP=desktop,
                        WAYLAND_DISPLAY='wayland-1', FAILED_UNIT=failed, PATH=temp + os.pathsep + os.environ['PATH']), capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, failed == '' and (requested != 'plasma' or desktop == 'KDE'), (desktop, requested, failed, result.stderr))
                    if requested == 'plasma' and desktop != 'KDE' and not failed:
                        self.assertIn('Expected KDE Wayland session', result.stderr)
