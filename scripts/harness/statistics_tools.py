"""Timing statistics, in milliseconds; timestamps originate in guest feedback."""
import math
import statistics


def percentile(values, percent):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * percent / 100
    low = math.floor(index)
    high = math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def timing_report(raw):
    frames = sorted(raw['frames'], key=lambda f: f['counter'])
    presented = [f for f in frames if f['presentation_time_us'] > 0]
    intervals = [(b['presentation_time_us'] - a['presentation_time_us']) / 1000
                 for a, b in zip(presented, presented[1:])]
    refresh = [f['refresh_interval_us'] / 1000 for f in presented if f['refresh_interval_us'] > 0]
    nominal = statistics.median(refresh) if refresh else None
    stalls = [{'after_counter': a['counter'], 'interval_ms': delta,
               'refresh_interval_ms': b['refresh_interval_us'] / 1000}
              for a, b, delta in zip(presented, presented[1:], intervals)
              if b['refresh_interval_us'] > 0 and delta > 1.5 * b['refresh_interval_us'] / 1000]
    return {**raw, 'observation': 'Guest compositor presentation feedback; not Mac display scanout',
            'presented_frame_count': len(presented), 'missing_presentation_time_count': len(frames) - len(presented),
            'interval_count': len(intervals), 'mean_interval_ms': statistics.mean(intervals) if intervals else None,
            'median_interval_ms': statistics.median(intervals) if intervals else None,
            'p95_interval_ms': percentile(intervals, 95), 'p99_interval_ms': percentile(intervals, 99),
            'longest_gap_ms': max(intervals, default=None), 'stall_count': len(stalls), 'stalls': stalls,
            'guest_refresh_hz': 1000 / nominal if nominal else None,
            'nonpositive_intervals': sum(v <= 0 for v in intervals)}
