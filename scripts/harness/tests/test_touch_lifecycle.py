"""Event construction and verdicts of the touchpad lifecycle checks, without a VM."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import touch_lifecycle


class ContactEventTests(unittest.TestCase):
    def test_down_frame_places_both_slots(self):
        events = touch_lifecycle.contact_events(radius=100, y=20000)
        updates = [e['data'] for e in events if e['data']['type'] == 'update']
        self.assertEqual([(u['slot'], u['tracking-id']) for u in updates], [(0, 0), (1, 1)])
        positions = {(e['data']['slot'], e['data']['axis']): e['data']['value'] for e in events if e['data']['type'] == 'data'}
        self.assertEqual(positions, {(0, 'x'): 16284, (0, 'y'): 20000, (1, 'x'): 16484, (1, 'y'): 20000})

    def test_release_frame_ends_both_slots(self):
        events = touch_lifecycle.contact_events(down=False)
        self.assertEqual([(e['data']['type'], e['data']['slot'], e['data']['tracking-id']) for e in events],
                         [('end', 0, -1), ('end', 1, -1)])


class VerdictTests(unittest.TestCase):
    clean = {'contacts_down_at_end': [], 'anomalies': [], 'pinch_balanced': True, 'contact_state_observed': True,
             'scroll_sequences': [{'start_time': 1.0, 'ends_with_scroll_stop': True}],
             'pinch_sequences': [{'ended': True}]}

    def test_clean_recording_passes(self):
        self.assertEqual(touch_lifecycle.evaluate(self.clean, {'scroll': True, 'pinch': True}), [])

    def test_each_failure_is_reported(self):
        analysis = dict(self.clean, contacts_down_at_end=[{'slot': 0}], anomalies=[{'type': 'button_during_gesture'}],
                        pinch_balanced=False, pinch_sequences=[],
                        scroll_sequences=[{'start_time': 2.0, 'ends_with_scroll_stop': False}])
        problems = touch_lifecycle.evaluate(analysis, {'scroll': True, 'pinch': True})
        self.assertEqual(len(problems), 5)
        self.assertTrue(any('contacts still down' in p for p in problems))
        self.assertTrue(any('button_during_gesture' in p for p in problems))

    def test_missing_expected_gestures(self):
        problems = touch_lifecycle.evaluate(dict(self.clean, scroll_sequences=[], pinch_sequences=[]), {'scroll': True, 'pinch': True})
        self.assertEqual(problems, ['no scroll recognised', 'no pinch recognised'])


if __name__ == '__main__':
    unittest.main()
