"""GTK4 moving rectangle workload; collect completed presentation feedback."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
import json
import subprocess
import signal
import sys
import time

seconds, cpu_load = float(sys.argv[1]), int(sys.argv[2])
workers = []
rows = []
pending = set()
started = None
frames_requested = 0
x = 0
app = Gtk.Application(application_id='dev.linuxvm.HarnessTiming')


def collect(clock):
    for counter in list(pending):
        timings = clock.get_timings(counter)
        if timings is None:
            pending.remove(counter)
            continue
        if timings.get_complete():
            rows.append({'counter': counter, 'frame_time_us': timings.get_frame_time(),
                         'presentation_time_us': timings.get_presentation_time(),
                         'refresh_interval_us': timings.get_refresh_interval()})
            pending.remove(counter)


def tick(widget, clock):
    global started, x, frames_requested
    if started is None:
        started = time.monotonic()
    counter = clock.get_frame_counter()
    collect(clock)
    if time.monotonic() - started >= seconds:
        GLib.timeout_add(500, finish, clock)
        return False
    pending.add(counter)
    frames_requested += 1
    x = (clock.get_frame_time() / 5000) % 700
    widget.queue_draw()
    return True


def finish(clock):
    collect(clock)
    print(json.dumps({'workload': 'GTK4 800x600 moving rectangle', 'duration_seconds': seconds,
                       'cpu_load_processes': cpu_load, 'frames_requested': frames_requested,
                       'pending_feedback': len(pending), 'frames': sorted(rows, key=lambda f: f['counter'])}))
    app.quit()
    return False


def draw(area, cr, width, height):
    cr.set_source_rgb(.08, .10, .15)
    cr.paint()
    cr.set_source_rgb(.95, .35, .15)
    cr.rectangle(x, height / 2 - 40, 80, 80)
    cr.fill()


def activate(app):
    window = Gtk.ApplicationWindow(application=app, title='Linux VM presentation timing')
    window.set_default_size(800, 600)
    area = Gtk.DrawingArea()
    area.set_draw_func(draw)
    area.add_tick_callback(tick)
    window.set_child(area)
    window.present()


app.connect('activate', activate)
# Bound the run even if the window is hidden and GTK stops requesting ticks.
def watchdog():
    print('Presentation workload watchdog expired (window hidden or no ticks)', file=sys.stderr)
    app.quit()
    return False
GLib.timeout_add(int((seconds + 15) * 1000), watchdog)
signal.signal(signal.SIGTERM, lambda *_: app.quit())
try:
    for _ in range(cpu_load):
        workers.append(subprocess.Popen(['python3', '-c', 'while True: pass']))
    app.run([sys.argv[0]])
finally:
    for worker in workers:
        worker.terminate()
    for worker in workers:
        worker.wait()
