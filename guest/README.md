# LinuxVM guest tools

`linuxvm-guest` 0.3.0 supports GNOME Shell/Mutter 50 and KDE Plasma 6.6–6.8 on
Wayland, as a Debian package for Ubuntu 26.04 and an RPM for Fedora 44 and 45.
The builder for both packages uses Python's standard library; the tools disc
requires xorriso (PATH, then `/opt/homebrew/bin/xorriso`). No VM or packaging
tools are needed on the Mac.

What works in a VM without this package, and what needs it:
[docs/what-needs-guest-tools.md](../docs/what-needs-guest-tools.md).

## Integrations

- Clipboard text/PNG uses Try Omarchy's wire protocol and echo suppression via
  `clipboard@linuxvm.dev` on GNOME. On other desktops it uses the compositor
  data-control protocol directly, preferring `ext_data_control_manager_v1` over
  `zwlr_data_control_manager_v1`; no wl-clipboard executable is required. Payloads are limited to 16 MiB, with strict UTF-8 and
  base64 checks. Disconnects fail the agent so systemd restarts it.
- Audio mirrors Mac endpoints through PipeWire/pipewire-pulse using pactl.
- Root `timezone.py` validates host IANA zones against `/usr/share/zoneinfo`.
  A guest zone differing from its last applied zone permanently stops following,
  including across restarts. To resume: stop `linuxvm-timezone.service`, delete
  `/var/lib/linuxvm/timezone.json`, then start it again.
- Root `share.py mount` mounts only the `mac` 9p tag at `/mnt/mac`, with
  `cache=readahead,msize=1048576,nodev,nosuid`. It validates the credential's
  URL-safe base64 folder name and publishes it at `/run/linuxvm/shared-folder-name`.
  The user agent creates `~/<name>` without replacing existing entries. It records
  device, inode and change time under `${XDG_STATE_HOME:-~/.local/state}/linuxvm/`
  and removes only its own unchanged links on rename, disconnect, logout or removal.
- Touchpad defaults turn on natural scrolling, as on the Mac, and disable
  tap-to-click and disable-while-typing. The Mac's touchpad contacts follow
  the fingers, so GNOME's own setting picks the direction. Existing user
  settings take precedence.

Ports are `dev.linuxvm.clipboard`, `.audio`, `.timezone` and `.status` under
`/dev/virtio-ports/`. udev grants the active seat user access to clipboard,
audio and status; timezone remains root-only. User services are globally enabled
for `graphical-session.target`; installation and upgrades require logout/login
to load the extension and start the new user units. The extension declares only
Shell 50, the tested major version; its own version is now 2.

## Clock recovery after Mac sleep

`linuxvm-clock-recovery.service` runs `/usr/lib/linuxvm/clock.py` as a root
oneshot with only CAP_SYS_TIME retained, a read-only filesystem sandbox and
no home access. It requires the `linuxvm.host` credential and an RTC exposing
`since_epoch`. The helper independently checks its imported credential, then
selects an RTC whose driver name is `rtc-efi`, `rtc-pl031` or `pl031`, rather
than assuming rtc0 is the correct device.

The helper rejects samples taking over two seconds. The RTC's whole-second
value is a lower bound: only a measured gap strictly greater than five seconds
causes a step, to RTC seconds plus the sample duration. It never steps backward
or writes the RTC. After stepping, `systemctl --no-block try-restart` restarts
chrony (Ubuntu 26.04's time service) or systemd-timesyncd, whichever is running;
a missing one does not fail the recovery. Small and backward offsets remain
network time synchronization's responsibility; a wrong Mac clock remains a
wrong reference.

The timezone agent requests `systemctl start --no-block
linuxvm-clock-recovery.service` on wake, coalescing messages within five seconds
using monotonic time. The fallback timer runs five seconds after boot and every
60 seconds of guest runtime after the oneshot becomes inactive, with one-second
accuracy. GNOME's GnomeWallClock uses a cancel-on-set timerfd and follows clock
steps automatically; no refresh unit is required.

Clock recovery is adapted from Try Omarchy's MIT `guest-clock-recover`, its
recovery units and `docs/guest-clock-recovery.md`; its license is included at
`/usr/share/doc/linuxvm-guest/copyright`.

## Guest status

`linuxvm-status.service` runs in the graphical session only when the status port
exists. It sends bounded UTF-8 JSON lines at startup, on our extension's
`ExtensionStateChanged`, on Shell bus-owner changes and for every host `query`.
Unknown keys/types and malformed or oversized lines are dropped; input resumes
after the offending newline. Transport failure exits and systemd reconnects.

The package version comes from `version.py`, generated from build.py's VERSION
and included with package md5sums; there are no runtime dpkg calls. OS comes from
PRETTY_NAME (128 characters), ShellVersion from `org.gnome.Shell` (32 characters,
omitted if unknown). `GetExtensionInfo` maps states 1/2/3/4/99 to
active/inactive/error/outdated/missing, empty info to missing and other states to
unknown. Without a Shell owner, the state is unknown.

The report also sends `desktop`, `desktopVersion` (when known), and `clipboard`.
On GNOME these identify GNOME and Shell's version; clipboard follows the extension
state, with missing mapped to pending. The `shell` and `extension` keys remain
compatible with 0.2 hosts. On KDE, `desktopVersion` is the cached result of
`kwin_wayland --version` (KWin ships with each Plasma release; `plasmashell --version` can crash), `extension` is unknown, and `shell` is absent. Other
desktops use the first entry of `XDG_CURRENT_DESKTOP`, limited to 32 characters.

## Clipboard on KDE and other Wayland desktops

A colon-separated `XDG_CURRENT_DESKTOP` containing GNOME always selects the
extension backend. Otherwise `wayland_clipboard.py` connects to `WAYLAND_DISPLAY`
(absolute, or relative to `XDG_RUNTIME_DIR`), binds the first seat and uses
data-control. Without either manager it reports unsupported and exits successfully;
transport errors and a finished device fail the service for systemd to restart.
The agent sends sync once its backend is ready. Text aliases are preferred over
PNG and accepted only with valid UTF-8. Transfers use a five-second timeout and
the same 16 MiB limit. Pipe reads and source writes share one select loop, including
when the compositor asks the agent to serve its own selection.

The agent atomically writes `$XDG_RUNTIME_DIR/linuxvm/clipboard.json` as mode 0600
in a mode 0700 folder. It contains `backend` (`gnome-extension` or `data-control`),
`state` (`active`, `unsupported`, or `error`) and `protocol` (the manager interface
name, or empty). Outside GNOME, status reads this file, uses unknown when absent
or invalid, and reports changes within about one second. On GNOME, status keeps
using Shell's extension state.

## Clipboard D-Bus API and access boundary

Session name `dev.linuxvm.Clipboard`, object `/dev/linuxvm/Clipboard`, interface
`dev.linuxvm.Clipboard1` exports:

- `GetSelection() → (s mime, ay data)`: UTF-8 text preferred over PNG; empty for
  unsupported, empty, stale, oversized or timed-out selections.
- `SetSelection(s mime, ay data) → ()`: canonical `text/plain;charset=utf-8` or
  `image/png`, 1–16777216 bytes. Invalid data returns
  `dev.linuxvm.Clipboard.Error.InvalidData`.
- `Changed()`: data-free broadcast when the CLIPBOARD owner changes.

Both methods first obtain the sender's `GetConnectionCredentials`, require the
Shell's UID, and check `/proc/<pid>/cgroup` for the exact user-unit component
`linuxvm-clipboard.service`. The unit directly ExecStarts Python, so the agent
runs in that cgroup. Results are cached per unique bus name and invalidated by
NameOwnerChanged; pending authorization cannot repopulate a stale cache after
name changes or extension disable. Unauthorized requests receive
`dev.linuxvm.Clipboard.Error.AccessDenied` before clipboard access.

This reduces accidental access and Wayland focus bypass through this API, but
is not a strong same-user security boundary: a same-user process able to move
itself into the unit's cgroup can impersonate the agent, and a cached caller can
move later. Confined snaps and Flatpaks are already restricted by their D-Bus
mediation. `Changed()` carries no clipboard content. St.Clipboard still allocates
a complete GBytes before the extension can enforce the payload size limit.

Disable disconnects signals, fails pending reads, unexports the object and
releases its bus name. Text aliases `text/plain`, `UTF8_STRING`, `TEXT`, `STRING`
are accepted when valid UTF-8.

## Build and verify

```sh
/opt/homebrew/bin/python3.14 guest/build.py
PYTHON=/opt/homebrew/bin/python3.14 guest/build-tools-iso.sh
/opt/homebrew/bin/python3.14 -m unittest discover guest/tests -v
```

Outputs: `guest/dist/linuxvm-guest_<version>_all.deb`,
`guest/dist/linuxvm-guest-<version>-1.noarch.rpm` and
`guest/dist/guest-tools.iso`. xorriso creates Rock Ridge plus Joliet with label
`LINUXVM-TOOLS`; root ownership, directories/install.sh 0755, other files 0644,
and fixed 2000-01-01 UTC timestamps. Two builds produce identical bytes; the
old makehybrid normalizer is removed. xorriso warns about the label's hyphen
under strict ISO9660 rules; both descriptors preserve the required label.

Run `./install.sh` on the disc. It requires exactly one
`linuxvm-guest_*_all.deb` and exactly one `linuxvm-guest-*.noarch.rpm`.
It uses sudo apt-get on Ubuntu, otherwise sudo dnf on Fedora; other systems
are unsupported. Both packages use the same file tree and generated version.
The RPM owns only its three private directories and uses root ownership, fixed
timestamps, SHA-256 file/payload/header digests and a gzip newc payload.
Upgrades enable and start the clock service/timer and globally enable status for the next login.
Removal stops current user agents, disables system/global units and reloads
managers and udev; Debian purge and RPM removal also remove timezone state.

macOS tests cover logic, syntax, package metadata and Rock Ridge/Joliet contents.
GNOME, D-Bus, systemd, udev, virtio, PipeWire and 9p require the in-guest checks
in [BUILD-REPORT.md](BUILD-REPORT.md). No VM was used for this implementation.
Other adaptations are from [Try Omarchy v1.3.0](https://github.com/omacom/try-omarchy)
(MIT); its notice is included in the package.
