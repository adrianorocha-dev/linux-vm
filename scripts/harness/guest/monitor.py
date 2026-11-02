import glob
import json
import subprocess
from gi.repository import Gio, GLib


def unpack(value):
    if isinstance(value, GLib.Variant):
        return unpack(value.unpack())
    if isinstance(value, dict):
        return {k: unpack(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [unpack(v) for v in value]
    return value


bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
state = unpack(bus.call_sync('org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig',
                            'org.gnome.Mutter.DisplayConfig', 'GetCurrentState', None, None,
                            Gio.DBusCallFlags.NONE, 15000, None))
serial, monitors, logical, properties = state
result = {'serial': serial, 'monitors': [], 'logical_monitors': [], 'properties': properties, 'edid': []}
for spec, modes, props in monitors:
    def mode(m):
        ident, width, height, hz, preferred_scale, scales, flags = m
        return {'id': ident, 'width': width, 'height': height, 'refresh_hz': hz,
                'preferred_scale': preferred_scale, 'supported_scales': scales, 'properties': flags}
    result['monitors'].append({'connector': spec[0], 'vendor': spec[1], 'product': spec[2], 'serial': spec[3],
                               'current_mode': next((mode(m) for m in modes if m[-1].get('is-current')), None),
                               'preferred_mode': next((mode(m) for m in modes if m[-1].get('is-preferred')), None),
                               'modes': [mode(m) for m in modes], 'properties': props})
for x, y, scale, transform, primary, specs, props in logical:
    result['logical_monitors'].append({'x': x, 'y': y, 'scale': scale, 'transform': transform,
                                       'primary': primary, 'connectors': [s[0] for s in specs], 'properties': props})
for path in glob.glob('/sys/class/drm/card*-*/edid'):
    with open(path, 'rb') as source:
        if not source.read():
            continue
    decoded = subprocess.run(['edid-decode', path], capture_output=True, text=True)
    lines = decoded.stdout.splitlines()
    result['edid'].append({'path': path, 'decode_exit_code': decoded.returncode,
                           'facts': [s.strip() for s in lines if any(t in s for t in ('image size', 'DTD', 'Hz', 'mm x', 'cm x', 'preferred'))],
                           'decoded': decoded.stdout, 'stderr': decoded.stderr})
print(json.dumps(result, indent=2))
