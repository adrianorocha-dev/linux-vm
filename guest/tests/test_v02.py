import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'files/usr/lib/linuxvm'))
from clock import choose_rtc, step_target
import clock
from timezone import WakeRecovery
from status import extension_state, encode_status, is_query, QueryLines, os_pretty_name


class RecoveryTests(unittest.TestCase):
    def test_decisions_precision_and_slow_samples(self):
        self.assertEqual(step_target(110, 100.5, .2), 110.2)
        for rtc, wall in [(100, 110), (105, 100), (105, 100.9)]:
            self.assertIsNone(step_target(rtc, wall, .1))
        self.assertEqual(step_target(106, 100.9, 2), 108)
        for elapsed in [-1, 2.001]:
            with self.assertRaises(ValueError):
                step_target(110, 100, elapsed)
        with self.assertRaises(ValueError):
            step_target(0, 100, .1)

    def test_choose_rtc(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, driver in [('rtc0', 'other'), ('rtc1', 'rtc-efi rtc-efi')]:
                (root / name).mkdir()
                (root / name / 'name').write_text(driver)
                (root / name / 'since_epoch').write_text('100')
            self.assertEqual(choose_rtc(root), root / 'rtc1')
            (root / 'rtc1/name').write_text('rtc-pl031 9010000.pl031')
            self.assertEqual(choose_rtc(root), root / 'rtc1')
            (root / 'rtc1/name').write_text('rtc-efi-untrusted')
            self.assertIsNone(choose_rtc(root))

    def test_credential_gate(self):
        with patch.dict(clock.os.environ, {}, clear=True), patch.object(clock, 'choose_rtc') as choose:
            self.assertFalse(clock.recover())
            choose.assert_not_called()

    def test_recover_steps_and_restarts_running_time_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'linuxvm.host').write_text('')
            (root / 'since_epoch').write_text('110')
            with (patch.dict(clock.os.environ, {'CREDENTIALS_DIRECTORY': temp}),
                  patch.object(clock, 'choose_rtc', return_value=root),
                  patch.object(clock.time, 'monotonic', side_effect=[1, 1.5]),
                  patch.object(clock.time, 'time', return_value=100),
                  patch.object(clock.time, 'clock_settime') as step,
                  patch.object(clock.subprocess, 'run') as run):
                self.assertTrue(clock.recover())
                step.assert_called_once_with(clock.time.CLOCK_REALTIME, 110.5)
                self.assertEqual([call.args[0][-1] for call in run.call_args_list],
                                 ['chrony.service', 'systemd-timesyncd.service'])
                for call in run.call_args_list:
                    self.assertEqual(call.args[0][:3], ['/usr/bin/systemctl', '--no-block', 'try-restart'])
                    self.assertFalse(call.kwargs['check'])

    def test_wake_coalescing(self):
        now, run = Mock(side_effect=[0, 1, 4.99, 5]), Mock()
        recovery = WakeRecovery(now, run)
        self.assertEqual([recovery.wake() for _ in range(4)], [True, False, False, True])
        self.assertEqual(run.call_count, 2)
        self.assertIn('--no-block', run.call_args.args[0])


class StatusTests(unittest.TestCase):
    def test_states(self):
        self.assertEqual(extension_state({}), 'missing')
        for value, expected in [(1, 'active'), (2, 'inactive'), (3, 'error'), (4, 'outdated'),
                                (99, 'missing'), (5, 'unknown'), (6, 'unknown'), (True, 'unknown'), ([], 'unknown')]:
            self.assertEqual(extension_state({'state': value}), expected)

    def test_encoding(self):
        data = encode_status('0.2.0', 'é' * 200, '50.1' * 20, 'active')
        self.assertLessEqual(len(data), 4096)
        value = json.loads(data)
        self.assertEqual(len(value['os']), 128)
        self.assertEqual(len(value['shell']), 32)
        self.assertEqual(value['package'], '0.2.0')
        self.assertNotIn('shell', json.loads(encode_status('0.2.0', '', None, 'unknown')))
        for version, state in [('bad', 'active'), ('0.2.0', 'bad')]:
            with self.assertRaises(ValueError):
                encode_status(version, '', None, state)

    def test_queries_and_recovery_after_oversized_input(self):
        self.assertTrue(is_query(b'{"type":"query","future":true}'))
        for value in ['{"type":"query"}'.encode('utf-16'), b'[]', b'{', b'\xff', b'{"type":"future"}', b'x' * 4096]:
            self.assertFalse(is_query(value))
        lines = QueryLines()
        self.assertEqual(lines.feed(b'x' * 10000), 0)
        self.assertLess(len(lines.buffer), 4096)
        self.assertEqual(lines.feed(b'\n{bad}\n{"type":"qu'), 0)
        self.assertEqual(lines.feed(b'ery"}\n{"type":"query"}\n'), 2)

    def test_os_release(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'os-release'
            path.write_text('NAME=Ubuntu\nPRETTY_NAME="Ubuntu 26.04.1 LTS"\n')
            self.assertEqual(os_pretty_name(path), 'Ubuntu 26.04.1 LTS')


class IntegrationStaticTests(unittest.TestCase):
    def test_units_version_and_upgrade_removal(self):
        system = ROOT / 'files/usr/lib/systemd/system'
        service = (system / 'linuxvm-clock-recovery.service').read_text()
        for value in ['ConditionCredential=linuxvm.host', 'ConditionPathExistsGlob=',
                      'CapabilityBoundingSet=CAP_SYS_TIME', 'ProtectSystem=strict']:
            self.assertIn(value, service)
        self.assertIn('OnUnitInactiveSec=60s', (system / 'linuxvm-clock-recovery.timer').read_text())
        self.assertIn('dev.linuxvm.status', (ROOT / 'files/usr/lib/udev/rules.d/70-linuxvm-ports.rules').read_text())
        for name in ['postinst', 'prerm']:
            text = (ROOT / 'debian' / name).read_text()
            for unit in ['linuxvm-status.service', 'linuxvm-clock-recovery.service', 'linuxvm-clock-recovery.timer']:
                self.assertIn(unit, text)
        source = (ROOT / 'files/usr/lib/linuxvm/status.py').read_text()
        self.assertIn('from version import VERSION', source)
        self.assertNotIn('dpkg', source)

    @unittest.skipUnless(shutil.which('node'), 'node unavailable')
    def test_cgroup_authorization_predicate(self):
        source = (ROOT / 'files/usr/share/gnome-shell/extensions/clipboard@linuxvm.dev/extension.js').read_text()
        function = source[source.index('export function agentCgroup'):source.index('export default class')]
        program = function + '''
import assert from 'node:assert/strict';
const base = '/user.slice/user-1000.slice/user@1000.service/app.slice/';
assert(agentCgroup('0::' + base + 'linuxvm-clipboard.service\\n'));
for (const path of ['other.service', 'linuxvm-clipboard.service.evil', 'linuxvm-clipboard.service/evil.scope'])
    assert(!agentCgroup('0::' + base + path));
assert(!agentCgroup('0::/system.slice/linuxvm-clipboard.service'));
assert(!agentCgroup('0::/userXslice/user-1000Xslice/user@1000Xservice/linuxvm-clipboard.service'));
assert(!agentCgroup('1:name=systemd:' + base + 'linuxvm-clipboard.service'));
'''
        subprocess.run(['node', '--input-type=module'], input=program.encode(), check=True)
        for value in ['GetConnectionCredentials', 'UnixUserID', 'ProcessID', 'NameOwnerChanged',
                      'dev.linuxvm.Clipboard.Error.AccessDenied']:
            self.assertIn(value, source)
        self.assertEqual(source.count('if (!await this._authorize(invocation))'), 2)
