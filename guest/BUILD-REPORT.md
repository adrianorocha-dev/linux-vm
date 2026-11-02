# Implementation report

All implementation files and generated artifacts are inside `linux-vm/guest/`.
No VM was started, stopped, contacted or accessed over SSH. No UI was built.
The contract and upstream sources were read without modification.

## Validation commands and results

Run from `linux-vm/`; each command below exited 0 on macOS:

```sh
/opt/homebrew/bin/python3.14 guest/build.py
PYTHON=/opt/homebrew/bin/python3.14 guest/build-tools-iso.sh
/opt/homebrew/bin/python3.14 -m unittest discover guest/tests -v
node --check guest/files/usr/share/gnome-shell/extensions/clipboard@linuxvm.dev/extension.js
```

- Debian package build: successful, stdlib only; no dpkg used.
- ISO build: successful with `hdiutil makehybrid -iso -joliet -default-volume-name LINUXVM-TOOLS`, followed by deterministic normalization. Both volume descriptors retain the exact label, including the hyphen.
- unittest: **23 tests passed**. This includes package/ar/tar metadata, paths, permissions, ownership, md5sums, the ISO payload and label, clipboard wire/echo handling, host setting validation, timezone persistence, link ownership and mount identity.
- Node syntax check: passed. The test suite also invokes `node --input-type=module --check` on extension source through stdin.
- Shell scripts were syntax-checked with `sh -n` by the test suite.
- All eight Python source/test/build files passed `ast.parse`.

The exact repeat-build comparison also exited 0:

```sh
/opt/homebrew/bin/python3.14 - <<'PY'
from pathlib import Path
import hashlib
import os
import subprocess
root = Path('guest')
paths = [root / 'dist/linuxvm-guest_0.1.0_all.deb', root / 'dist/guest-tools.iso']
before = [path.read_bytes() for path in paths]
subprocess.run([str(root / 'build-tools-iso.sh')], env={**os.environ, 'PYTHON': '/opt/homebrew/bin/python3.14'}, check=True)
for path, previous in zip(paths, before):
    data = path.read_bytes()
    assert data == previous, f'{path}: nondeterministic build'
    print(f'{path}: identical, {len(data)} bytes, SHA256 {hashlib.sha256(data).hexdigest()}')
PY
```

Both artifacts were byte-identical on consecutive builds:

- `guest-tools.iso`: 921600 bytes; SHA256 `39f9cdf4d7027039b8c8e71e091bd0abb08b7405aebe41770cffd64e114efe6d`.
- `linuxvm-guest_0.1.0_all.deb`: 15074 bytes; SHA256 `a7084511428b3fd27c233ad02ee9d349a61079f8e0801cbc77411cfb7c99b783`.

## Implemented D-Bus interface

Session bus: `dev.linuxvm.Clipboard`  
Object: `/dev/linuxvm/Clipboard`  
Interface: `dev.linuxvm.Clipboard1`

```text
GetSelection() -> (s mime, ay data)
SetSelection(s mime, ay data) -> ()
Changed()
```

Text wins over PNG. Text aliases are canonicalized to
`text/plain;charset=utf-8`, and invalid UTF-8 is ignored. Empty/unusable,
stale, oversized or timed-out selections return empty mime/data. Writes accept
only canonical UTF-8 text or `image/png`, 1 through 16777216 bytes.
Invalid writes return `dev.linuxvm.Clipboard.Error.InvalidData`.
Disable disconnects the selection signal, fails outstanding calls with
`dev.linuxvm.Clipboard.Error.Disabled`, unexports the object and releases the name.

Wire schemas were checked against `NativeClipboardBridge.swift`,
`NativeAudioBridge.swift`, `NativeTimeZoneBridge.swift` and
`NativeBridgeSocket.swift`. The agents use the contract's three `dev.linuxvm.*`
port names, the `mac` 9p tag and `linuxvm.host` systemd credential.

## Guest verification still required

GNOME Shell/GJS runtime behavior, Gio D-Bus integration, extension activation
after logout/login, systemd lifecycle/credential import, udev access controls,
actual virtio disconnect/reconnect, PipeWire routing, timedatectl and 9p mounting
could not be exercised on macOS. Maintainer scripts were syntax-checked and
inspected; no package was installed on the Mac. The ISO was inspected directly
as bytes and was not mounted. PNG payload handling follows upstream opaque-byte
validation; it does not decode image pixels. St.Clipboard returns a full GBytes
before the extension can check the selection size; the 16 MiB limit applies to
accepted D-Bus and transport payloads, not St's internal transfer allocation.

## Files created

- `BUILD-REPORT.md`
- `README.md`
- `build-tools-iso.sh`
- `build.py`
- `debian/control`
- `debian/postinst`
- `debian/postrm`
- `debian/prerm`
- `dist/guest-tools.iso`
- `dist/linuxvm-guest_0.1.0_all.deb`
- `files/usr/lib/linuxvm/audio.py`
- `files/usr/lib/linuxvm/clipboard.py`
- `files/usr/lib/linuxvm/common.py`
- `files/usr/lib/linuxvm/share.py`
- `files/usr/lib/linuxvm/timezone.py`
- `files/usr/lib/systemd/system/linuxvm-share-mount.service`
- `files/usr/lib/systemd/system/linuxvm-timezone.service`
- `files/usr/lib/systemd/user/linuxvm-audio.service`
- `files/usr/lib/systemd/user/linuxvm-clipboard.service`
- `files/usr/lib/systemd/user/linuxvm-share-link.service`
- `files/usr/lib/udev/rules.d/70-linuxvm-ports.rules`
- `files/usr/share/doc/linuxvm-guest/copyright`
- `files/usr/share/glib-2.0/schemas/90_linuxvm.gschema.override`
- `files/usr/share/gnome-shell/extensions/clipboard@linuxvm.dev/extension.js`
- `files/usr/share/gnome-shell/extensions/clipboard@linuxvm.dev/metadata.json`
- `files/usr/share/libinput/90-linuxvm.quirks`
- `iso/README.txt`
- `iso/install.sh`
- `tests/test_guest.py`
- `tests/test_iso.py`
