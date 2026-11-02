"""Parse libinput debug-events text and evdev contact state without dependencies."""
import re
import statistics

EVENT = re.compile(r'(?P<device>event\d+)\s+(?P<kind>[A-Z][A-Z_]+)\s+(?:\d+\s+)?\+?(?P<time>\d+(?:\.\d+)?)s\s*(?P<data>.*)')
AXIS = re.compile(r'(vert|horiz)\s+([+-]?\d+(?:\.\d+)?)(?:/([+-]?\d+(?:\.\d+)?))?')


def parse_debug(text, offset=0):
    events = []
    for line in text.splitlines():
        match = EVENT.search(line)
        if match:
            event = match.groupdict()
            event['time'] = float(event['time']) + offset
            event['axes'] = {m[0]: float(m[1]) for m in AXIS.findall(event['data'])}
            events.append(event)
    return events


def analyze(recording, gap_seconds=.1, scroll_gap_seconds=.25):
    if isinstance(recording, str):
        recording = {'devices': [{'debug_events': recording}], 'evdev': []}
    # debug-events uses the first hardware event as its per-process time origin,
    # not process startup. Align independent device readers with raw evdev time.
    origins = {}
    for event in recording.get('evdev', []):
        if 'time' in event:
            origins[event['device']] = min(origins.get(event['device'], event['time']), event['time'])
    events = sorted([e for d in recording['devices'] for e in parse_debug(
        d['debug_events'], d.get('debug_time_origin_seconds', origins.get(d.get('path'), d.get('start_offset_seconds', 0))))],
        key=lambda e: e['time'])
    scrolls, pinches, swipes, anomalies, gaps = [], [], [], [], []
    active_scroll, active_pinch, active_swipe = {}, {}, {}
    previous = {}
    counts = {kind: 0 for kind in ('pinch_begin', 'pinch_update', 'pinch_end', 'swipe_begin', 'swipe_update', 'swipe_end')}
    def finish_scroll(device, stopped):
        seq = active_scroll.pop(device)
        seq['duration_seconds'] = seq['last_time'] - seq['start_time']
        seq['ends_with_scroll_stop'] = stopped
        seq['axis_mix'] = [k for k in ('vert', 'horiz') if seq['absolute_distance'][k] > 0]
        scrolls.append(seq)
    for event in events:
        device, kind, timestamp, data = event['device'], event['kind'], event['time'], event['data']
        if device in previous and timestamp - previous[device] > gap_seconds:
            gaps.append({'device': device, 'after_time': previous[device], 'gap_seconds': timestamp - previous[device]})
        previous[device] = timestamp
        if kind in ('POINTER_SCROLL_FINGER', 'POINTER_AXIS') and ('finger' in data.lower() or kind == 'POINTER_SCROLL_FINGER'):
            axes = event['axes']
            if not axes:
                anomalies.append({'type': 'unparsed_scroll', 'event': event})
                continue
            if device in active_scroll and timestamp - active_scroll[device]['last_time'] > scroll_gap_seconds:
                finish_scroll(device, False)
            seq = active_scroll.setdefault(device, {'device': device, 'start_time': timestamp, 'last_time': timestamp,
                                                     'event_count': 0, 'total_distance': {'vert': 0., 'horiz': 0.},
                                                     'absolute_distance': {'vert': 0., 'horiz': 0.}})
            seq['last_time'] = timestamp
            seq['event_count'] += 1
            for axis, value in axes.items():
                seq['total_distance'][axis] += value
                seq['absolute_distance'][axis] += abs(value)
            # libinput emits an all-zero finger-scroll event to end scrolling.
            if all(value == 0 for value in axes.values()):
                finish_scroll(device, True)
        if kind.startswith('GESTURE_'):
            for name, active, sequences in [('PINCH', active_pinch, pinches), ('SWIPE', active_swipe, swipes)]:
                prefix = 'GESTURE_' + name + '_'
                if not kind.startswith(prefix):
                    continue
                action = kind[len(prefix):].lower()
                if name.lower() + '_' + action not in counts:
                    continue
                counts[name.lower() + '_' + action] += 1
                if action == 'begin':
                    if device in active:
                        anomalies.append({'type': 'duplicate_' + name.lower() + '_begin', 'event': event})
                        sequences.append(active.pop(device))
                    active[device] = {'device': device, 'start_time': timestamp, 'updates': 0, 'ended': False}
                elif action == 'update' and device in active:
                    active[device]['updates'] += 1
                elif action == 'end' and device in active:
                    seq = active.pop(device)
                    seq.update(ended=True, duration_seconds=timestamp - seq['start_time'], cancelled='cancelled' in data.lower())
                    sequences.append(seq)
                else:
                    anomalies.append({'type': 'unbalanced_' + name.lower() + '_' + action, 'event': event})
        # A gesture on the touchpad can coincide with a tablet button/motion.
        scrolling = any(timestamp - s['last_time'] <= scroll_gap_seconds for s in active_scroll.values())
        pinching = bool(active_pinch)
        if kind == 'POINTER_BUTTON' and (scrolling or pinching or active_swipe):
            anomalies.append({'type': 'button_during_gesture', 'event': event})
        if kind in ('POINTER_MOTION', 'POINTER_MOTION_ABSOLUTE') and pinching:
            anomalies.append({'type': 'pointer_motion_during_pinch', 'event': event})
    for device in list(active_scroll):
        finish_scroll(device, False)
    pinches.extend(active_pinch.values())
    swipes.extend(active_swipe.values())
    slots, current_slot, buttons = {}, {}, {}
    for event in recording.get('evdev', []):
        device, typ, code, value = (event[k] for k in ('device', 'type', 'code', 'value'))
        if typ == 3 and code == 47:  # ABS_MT_SLOT
            current_slot[device] = value
        elif typ == 3 and code == 57:  # ABS_MT_TRACKING_ID
            slots[(device, current_slot.get(device, 0))] = value
        elif typ == 1 and code == 330:  # BTN_TOUCH (single-touch tablet)
            buttons[device] = value
    stuck = [{'device': dev, 'slot': slot, 'tracking_id': value} for (dev, slot), value in slots.items() if value >= 0]
    stuck.extend({'device': dev, 'button': 'BTN_TOUCH'} for dev, value in buttons.items() if value)
    return {'event_count': len(events), 'scroll_sequence_count': len(scrolls), 'scroll_sequences': scrolls,
            'gesture_counts': counts, 'pinch_sequences': pinches, 'swipe_sequences': swipes,
            'pinch_balanced': counts['pinch_begin'] == counts['pinch_end'] and all(s['ended'] for s in pinches) and not any(a['type'].startswith(('duplicate_pinch', 'unbalanced_pinch')) for a in anomalies),
            'swipe_balanced': counts['swipe_begin'] == counts['swipe_end'] and all(s['ended'] for s in swipes) and not any(a['type'].startswith(('duplicate_swipe', 'unbalanced_swipe')) for a in anomalies),
            'anomalies': anomalies, 'contacts_down_at_end': stuck,
            'contact_state_observed': bool(recording.get('evdev')), 'timing_gaps': gaps,
            'gap_threshold_seconds': gap_seconds, 'scroll_split_gap_seconds': scroll_gap_seconds,
            'limits': ['Gaps can be intentional pauses; they are not proof of dropped events.',
                       'Only contacts observed during capture are known; start with all fingers lifted.',
                       'A gesture interrupted by the capture boundary may appear unbalanced.',
                       'Scroll distance is libinput debug-events output units; not physical Mac travel.',
                       'Per-device debug clocks are approximately aligned to their first observed raw event.']}
