"""Screenshot portal; host explicitly grants permission on this test VM."""
import json
from pathlib import Path
import shutil
import sys
from urllib.parse import unquote, urlparse
from gi.repository import Gio, GLib

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
loop = GLib.MainLoop()
result = {}


def response(connection, sender, path, interface, signal, parameters):
    code, values = parameters.unpack()
    result.update(code=code, values=values)
    loop.quit()


def timeout():
    result['error'] = 'Screenshot portal response timeout'
    loop.quit()
    return False


token = 'linuxvm_harness_' + str(__import__('os').getpid())
handle = '/org/freedesktop/portal/desktop/request/' + bus.get_unique_name()[1:].replace('.', '_') + '/' + token
subscription = bus.signal_subscribe('org.freedesktop.portal.Desktop', 'org.freedesktop.portal.Request',
                                    'Response', handle, None, Gio.DBusSignalFlags.NONE, response)
bus.call_sync('org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop',
              'org.freedesktop.portal.Screenshot', 'Screenshot',
              GLib.Variant('(sa{sv})', ('', {'interactive': GLib.Variant('b', False),
                                            'handle_token': GLib.Variant('s', token)})),
              None, Gio.DBusCallFlags.NONE, 15000, None)
GLib.timeout_add_seconds(40, timeout)
loop.run()
bus.signal_unsubscribe(subscription)
if result.get('code') != 0:
    raise RuntimeError(str(result))
uri = result['values']['uri']
parsed = urlparse(uri)
if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost'):
    raise RuntimeError('Unexpected screenshot URI: ' + uri)
source = Path(unquote(parsed.path))
shutil.copyfile(source, sys.argv[1])
source.unlink()
print(json.dumps({'path': sys.argv[1], 'portal_response': result['code']}))
