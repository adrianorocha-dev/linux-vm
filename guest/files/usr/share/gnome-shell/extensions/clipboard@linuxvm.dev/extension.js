import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const NAME = 'dev.linuxvm.Clipboard';
const PATH = '/dev/linuxvm/Clipboard';
const TEXT = 'text/plain;charset=utf-8';
const PNG = 'image/png';
const LIMIT = 16 * 1024 * 1024;
const TEXT_TYPES = [TEXT, 'text/plain', 'UTF8_STRING', 'TEXT', 'STRING'];
const XML = `<node>
  <interface name="dev.linuxvm.Clipboard1">
    <method name="GetSelection">
      <arg name="mime" type="s" direction="out"/>
      <arg name="data" type="ay" direction="out"/>
    </method>
    <method name="SetSelection">
      <arg name="mime" type="s" direction="in"/>
      <arg name="data" type="ay" direction="in"/>
    </method>
    <signal name="Changed"/>
  </interface>
</node>`;

export default class ClipboardExtension extends Extension {
    enable() {
        this._clipboard = St.Clipboard.get_default();
        this._selection = global.display.get_selection();
        this._generation = 0;
        this._pending = new Map();
        this._object = Gio.DBusExportedObject.wrapJSObject(XML, this);
        this._object.export(Gio.DBus.session, PATH);
        this._owner = Gio.bus_own_name_on_connection(
            Gio.DBus.session, NAME, Gio.BusNameOwnerFlags.NONE, null, null);
        this._changed = this._selection.connect('owner-changed', (_selection, type) => {
            if (type === Meta.SelectionType.SELECTION_CLIPBOARD) {
                this._generation++;
                this._object.emit_signal('Changed', null);
            }
        });
    }

    GetSelectionAsync(_parameters, invocation) {
        const generation = this._generation;
        const finish = (mime = '', data = new Uint8Array()) => {
            const timeout = this._pending?.get(invocation);
            if (timeout === undefined)
                return;
            GLib.source_remove(timeout);
            this._pending.delete(invocation);
            invocation.return_value(new GLib.Variant('(say)', [mime, data]));
        };
        const timeout = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 10000, () => {
            this._pending.delete(invocation);
            invocation.return_value(new GLib.Variant('(say)', ['', new Uint8Array()]));
            return GLib.SOURCE_REMOVE;
        });
        this._pending.set(invocation, timeout);
        try {
            const offered = this._clipboard.get_mimetypes(St.ClipboardType.CLIPBOARD) ?? [];
            const requested = TEXT_TYPES.find(type => offered.includes(type)) ??
                (offered.includes(PNG) ? PNG : null);
            if (!requested) {
                finish();
                return;
            }
            this._clipboard.get_content(St.ClipboardType.CLIPBOARD, requested, (_clipboard, bytes) => {
                try {
                    if (!this._clipboard || generation !== this._generation || !bytes ||
                        bytes.get_size() === 0 || bytes.get_size() > LIMIT) {
                        finish();
                        return;
                    }
                    const data = bytes.get_data();
                    if (requested !== PNG)
                        new TextDecoder('utf-8', {fatal: true}).decode(data);
                    finish(requested === PNG ? PNG : TEXT, data);
                } catch (_error) {
                    finish();
                }
            });
        } catch (_error) {
            finish();
        }
    }

    SetSelectionAsync([mime, data], invocation) {
        try {
            if ((mime !== TEXT && mime !== PNG) || data.length === 0 || data.length > LIMIT)
                throw new Error('Unsupported clipboard format or size');
            if (mime === TEXT)
                new TextDecoder('utf-8', {fatal: true}).decode(data);
            this._clipboard.set_content(St.ClipboardType.CLIPBOARD, mime, new GLib.Bytes(data));
            invocation.return_value(new GLib.Variant('()', []));
        } catch (_error) {
            invocation.return_dbus_error('dev.linuxvm.Clipboard.Error.InvalidData',
                'Unsupported clipboard format, invalid UTF-8, or payload outside 1..16777216 bytes');
        }
    }

    disable() {
        if (this._changed)
            this._selection.disconnect(this._changed);
        this._changed = 0;
        for (const [invocation, timeout] of this._pending ?? []) {
            GLib.source_remove(timeout);
            invocation.return_dbus_error('dev.linuxvm.Clipboard.Error.Disabled',
                'Clipboard extension disabled');
        }
        this._pending?.clear();
        if (this._owner)
            Gio.bus_unown_name(this._owner);
        this._owner = 0;
        this._object?.unexport();
        this._object = null;
        this._clipboard = null;
        this._selection = null;
    }
}
