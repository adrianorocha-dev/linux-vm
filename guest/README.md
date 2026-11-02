# LinuxVM guest tools

Ubuntu 26.04 Desktop, GNOME Shell/Mutter 50 on Wayland. This builds
`linuxvm-guest` 0.1.0 (`Architecture: all`), using Python's standard library.
No VM access or Debian build tools are needed on the Mac.

- `files/usr/lib/linuxvm/clipboard.py` adapts Try Omarchy's text/PNG wire
  protocol and echo suppression to a GNOME Shell extension. It retries enabling
  the extension while waiting for its D-Bus name and resynchronizes with the Mac
  when the name appears. Clipboard data is limited to 16 MiB, with strict UTF-8
  text and base64 validation. Disconnects fail the service so systemd restarts it.
- `audio.py` adapts the upstream pactl remap modules and route selection to
  PipeWire/pipewire-pulse, with `linuxvm_host_` endpoint names.
- Root `timezone.py` accepts the launch credential and live host zones. It
  validates names against `/usr/share/zoneinfo` and calls `timedatectl`. A guest
  zone differing from its last applied zone permanently stops following,
  including across restarts. State is `/var/lib/linuxvm/timezone.json`.
  To resume following explicitly, stop `linuxvm-timezone.service`, delete that
  state file, then start the service. Host `wake` messages are accepted and ignored.
- Root `share.py mount` mounts only the `mac` 9p tag at `/mnt/mac`, using upstream
  `cache=readahead,msize=1048576` plus `nodev,nosuid`. It validates the URL-safe
  base64 folder name in `$CREDENTIALS_DIRECTORY/linuxvm.host` and publishes only
  that encoded name at `/run/linuxvm/shared-folder-name`. Invalid names suppress
  the home link while allowing the mount. A user agent watches the mounted share
  and links `~/<name>`; it never replaces an existing entry. It records each link's
  device, inode and change time under `${XDG_STATE_HOME:-~/.local/state}/linuxvm/`
  and removes only matching links, on rename, loss of sharing, logout or removal.
- udev grants the active desktop user access to clipboard/audio ports and keeps
  timezone root-only. The libinput quirk and gsettings override match the host's
  virtual touchpad scrolling and disable tap-to-click/disable-while-typing.

The three port names are `dev.linuxvm.clipboard`, `dev.linuxvm.audio` and
`dev.linuxvm.timezone`. Root services use `ImportCredential=linuxvm.host`.
User services are enabled globally for `graphical-session.target`; system
services start at `multi-user.target`. Installation needs a logout/login to
load the new Shell extension and start user services. Existing per-user
settings take precedence over the touchpad defaults.

## Clipboard D-Bus API

Session bus name `dev.linuxvm.Clipboard`, object `/dev/linuxvm/Clipboard`,
interface `dev.linuxvm.Clipboard1`:

- `GetSelection() → (s mime, ay data)`: UTF-8 text preferred over PNG; empty mime
  and data for unsupported, empty, stale, oversized or timed-out selections.
- `SetSelection(s mime, ay data) → ()`: accepts `text/plain;charset=utf-8` or
  `image/png`, with 1–16777216 bytes. Invalid input returns
  `dev.linuxvm.Clipboard.Error.InvalidData`.
- `Changed()`: emitted when the CLIPBOARD owner changes, including our own writes.

The ESM extension `clipboard@linuxvm.dev` uses `St.Clipboard` and
`global.display.get_selection()`; it disconnects signals, cancels pending
D-Bus calls and releases its bus name when disabled. Text reads also accept
`text/plain`, `UTF8_STRING`, `TEXT` and `STRING`, provided the bytes are UTF-8.
The St API delivers a complete `GBytes` before the extension can check its size.

## Build and test

From `linux-vm/`:

```sh
/opt/homebrew/bin/python3.14 -m unittest discover guest/tests -v
/opt/homebrew/bin/python3.14 guest/build.py
PYTHON=/opt/homebrew/bin/python3.14 guest/build-tools-iso.sh
```

Or use any Python 3 on PATH. The ISO step requires macOS `hdiutil`. Outputs:
`dist/linuxvm-guest_0.1.0_all.deb` and `dist/guest-tools.iso` (LINUXVM-TOOLS).
The disc contains the package, `install.sh` and `README.txt`. Run
`sh install.sh` from the mounted disc; it uses `sudo apt-get install -y`.

All archive mtimes use 2000-01-01 UTC. Debian ownership is root:root and modes
are assigned explicitly. The ISO normalizer removes makehybrid's host-specific
POSIX metadata and fixes descriptor/directory times; the disc uses Joliet names.
Tests check the wire/echo logic, untrusted settings, timezone opt-out, safe link
management, package contents/metadata, shell syntax and JavaScript syntax when
Node is available. Built ISO contents are checked when the ISO exists.

The macOS checks cannot exercise GNOME, D-Bus, virtio ports, udev, systemd,
PipeWire or 9p. Validate those in the guest after logout/login.

Parts are adapted from [Try Omarchy v1.3.0](https://github.com/omacom/try-omarchy)
(MIT). Its license notice is included at
`/usr/share/doc/linuxvm-guest/copyright`. Clipboard, audio and timezone wire
schemas were checked against the corresponding Swift helper bridges.
