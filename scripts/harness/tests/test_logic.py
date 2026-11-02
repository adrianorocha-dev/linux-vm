from pathlib import Path
import json
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from analyzer import analyze, parse_debug
from fresh_install import seed
from statistics_tools import percentile, timing_report
from terminal import screen, editor_linux_line


class SeedTests(unittest.TestCase):
    def test_identity_key_and_no_interactive_login(self):
        text = seed('ssh-ed25519 AAAA tester\n', '$6$random$hash', 12345)
        self.assertIn('password: "$6$random$hash"', text)
        self.assertIn('"ssh-ed25519 AAAA tester"', text)
        self.assertIn('name: direct', text)
        self.assertIn('allow-pw: false', text)
        late = [json.loads(line[6:]) for line in text.splitlines() if line.startswith('    - ')]
        self.assertTrue(any('AutomaticLogin=tester' in c for c in late))
        self.assertTrue(any('NOPASSWD:ALL' in c for c in late))
        self.assertTrue(late[-1].endswith('http://10.0.2.2:12345/installation-complete'))


class TimingTests(unittest.TestCase):
    def test_feedback_statistics_and_stalls(self):
        raw = {'frames': [{'counter': i, 'presentation_time_us': t, 'refresh_interval_us': 10000}
                          for i, t in enumerate([100000, 110000, 120000, 150000, 0])]}
        result = timing_report(raw)
        self.assertEqual(result['presented_frame_count'], 4)
        self.assertEqual(result['missing_presentation_time_count'], 1)
        self.assertEqual(result['median_interval_ms'], 10)
        self.assertEqual(result['longest_gap_ms'], 30)
        self.assertEqual(result['stall_count'], 1)
        self.assertEqual(result['guest_refresh_hz'], 100)
        self.assertAlmostEqual(result['p95_interval_ms'], 28)

    def test_absent_feedback_is_not_fabricated(self):
        result = timing_report({'frames': []})
        self.assertIsNone(result['mean_interval_ms'])
        self.assertIsNone(result['guest_refresh_hz'])
        self.assertEqual(result['stall_count'], 0)
        self.assertIsNone(percentile([], 99))

    def test_stall_uses_per_frame_refresh(self):
        result = timing_report({'frames': [
            {'counter': 1, 'presentation_time_us': 10000, 'refresh_interval_us': 10000},
            {'counter': 2, 'presentation_time_us': 30000, 'refresh_interval_us': 20000}]})
        self.assertEqual(result['stall_count'], 0)


class AnalyzerTests(unittest.TestCase):
    def test_injected_bugs_and_stuck_contact(self):
        source = '''event5 GESTURE_PINCH_BEGIN +0.000s 2
 event5 GESTURE_PINCH_UPDATE +0.010s 2 0.00/0.00 1.20 @ 0.0
 event4 POINTER_BUTTON +0.020s BTN_LEFT (272) pressed, seat count: 1
 event4 POINTER_MOTION_ABSOLUTE +0.025s 20.0/30.0
 event5 GESTURE_PINCH_END +0.030s 2
 event5 POINTER_SCROLL_FINGER +0.100s vert 2.00/0.0 horiz -3.00/0.0 (finger)
 event5 POINTER_SCROLL_FINGER +0.110s vert 0.00/0.0 horiz 0.00/0.0 (finger)
 event5 POINTER_SCROLL_FINGER +0.500s vert 4.00/0.0 horiz 0.00/0.0 (finger)
'''
        result = analyze({'devices': [{'debug_events': source}], 'evdev': [
            {'device': 'event5', 'type': 3, 'code': 47, 'value': 1},
            {'device': 'event5', 'type': 3, 'code': 57, 'value': 99}]})
        self.assertEqual(result['scroll_sequence_count'], 2)
        self.assertTrue(result['scroll_sequences'][0]['ends_with_scroll_stop'])
        self.assertFalse(result['scroll_sequences'][1]['ends_with_scroll_stop'])
        self.assertEqual(result['scroll_sequences'][0]['axis_mix'], ['vert', 'horiz'])
        self.assertEqual(result['scroll_sequences'][0]['total_distance'], {'vert': 2., 'horiz': -3.})
        self.assertTrue(result['pinch_balanced'])
        self.assertEqual([a['type'] for a in result['anomalies']], ['button_during_gesture', 'pointer_motion_during_pinch'])
        self.assertEqual(result['contacts_down_at_end'][0]['tracking_id'], 99)
        self.assertTrue(result['timing_gaps'])

    def test_missing_begin_is_unbalanced(self):
        result = analyze('event5 GESTURE_PINCH_END +0.100s 2')
        self.assertFalse(result['pinch_balanced'])
        self.assertFalse(result['contact_state_observed'])

    def test_contact_release(self):
        result = analyze({'devices': [], 'evdev': [
            {'device': 'event5', 'type': 3, 'code': 57, 'value': 17},
            {'device': 'event5', 'type': 3, 'code': 57, 'value': -1}]})
        self.assertEqual(result['contacts_down_at_end'], [])


class TerminalTests(unittest.TestCase):
    def test_private_csi_and_editor_borders(self):
        text = '\x1b[=3h\x1b[2J\x1b[8;2H|\x1b[8;3H    linux /casper/vmlinuz\x1b[5;3H'
        lines, row, col = screen(text)
        self.assertEqual((row, col), (4, 2))
        self.assertEqual(editor_linux_line(text), '    linux /casper/vmlinuz')

    def test_real_serial_editor_and_wrapped_kernel_arguments(self):
        text = (HERE / 'fixtures/grub-editor.txt').read_text()
        command = editor_linux_line(text)
        self.assertTrue(command.lstrip().startswith('linux '))
        self.assertIn('autoinstall ds=nocloud-net\\;s=http://10.0.2.2:60917/ console=ttyAMA0', command)

    def test_arguments_on_other_line_are_not_linux_arguments(self):
        text = '\x1b[7;3H set gfxpayload=keep autoinstall\x1b[8;3H linux /casper/vmlinuz'
        self.assertNotIn('autoinstall', editor_linux_line(text))


if __name__ == '__main__':
    unittest.main()
