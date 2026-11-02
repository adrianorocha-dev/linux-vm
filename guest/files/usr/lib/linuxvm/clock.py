#!/usr/bin/python3
"""Forward-only RTC recovery, adapted from Try Omarchy (MIT)."""
import os
from pathlib import Path
import subprocess
import sys
import time


def choose_rtc(root=Path('/sys/class/rtc')):
    for rtc in sorted(root.glob('rtc*')):
        name = (rtc / 'name').read_text().strip().split()[0]
        if name in ('rtc-efi', 'rtc-pl031', 'pl031') and (rtc / 'since_epoch').is_file():
            return rtc
    return None


def step_target(rtc, wall, elapsed):
    if rtc <= 0 or not 0 <= elapsed <= 2:
        raise ValueError('unusable virtual RTC sample')
    # Whole-second RTC value is a lower bound; do not round up a small gap.
    return rtc + elapsed if rtc - wall > 5 else None


def recover():
    directory = os.environ.get('CREDENTIALS_DIRECTORY')
    if not directory or not (Path(directory) / 'linuxvm.host').is_file():
        return False
    rtc = choose_rtc()
    if rtc is None:
        return False
    start = time.monotonic()
    seconds = int((rtc / 'since_epoch').read_text().strip())
    wall = time.time()
    target = step_target(seconds, wall, time.monotonic() - start)
    if target is None:
        return False
    time.clock_settime(time.CLOCK_REALTIME, target)
    print(f'Recovered guest clock forward to {target}', flush=True)
    subprocess.run(['/usr/bin/systemctl', '--no-block', 'try-restart',
                    'systemd-timesyncd.service'], check=True, timeout=5)
    return True


if __name__ == '__main__':
    try:
        recover()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'linuxvm-clock-recovery: {error}', file=sys.stderr)
        raise SystemExit(1)
