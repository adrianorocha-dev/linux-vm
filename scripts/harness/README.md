# VM harness

Host requirements: macOS/Apple Silicon, `/opt/homebrew/bin/python3.14`, OpenSSH,
`/opt/homebrew/bin/openssl`, and the installed Linux VM app. Host Python uses only
the standard library. These tools never rebuild or replace the app.

## Fresh install

```sh
scripts/harness/fresh-install
# Keep the test VM for captures (explicitly clean it up afterwards):
scripts/harness/fresh-install --keep
scripts/harness/ssh harness-runs/20261102-123456 uname -a
scripts/harness/cleanup harness-runs/20261102-123456
```

`LINUXVMCTL` overrides `/Applications/Linux VM.app/Contents/Helpers/linuxvmctl`.
`--iso PATH` overrides the ISO, which defaults to the repository's
`test-media/ubuntu-26.04.1-desktop-arm64.iso`.
Fedora images are selected automatically when the filename contains `Fedora`.
For a renamed image, use `--profile fedora --iso PATH`; Fedora always requires an
explicit ISO. `--profile ubuntu` explicitly selects the existing Ubuntu path.
Unknown image names require an explicit profile.

```sh
scripts/harness/fresh-install --iso test-media/Fedora-Workstation-Live-44-1.7.aarch64.iso
scripts/harness/fresh-install --iso test-media/Fedora-KDE-Desktop-Live-45-1.4.aarch64.iso
# Install a candidate RPM and retain the VM for investigation:
scripts/harness/fresh-install --profile fedora --iso test-media/Fedora-KDE-Desktop-Live-45-1.4.aarch64.iso --rpm /path/to/linuxvm-guest.noarch.rpm --keep
```

`--deb PATH` (Ubuntu) or `--rpm PATH` (Fedora) installs a candidate guest package
instead of the installed app's Guest Tools disc. `--run-dir PATH` chooses a new,
nonexistent output directory.

Each VM has 4096 MiB, four CPUs, a sparse 32 GiB disk, a unique harness name,
a forwarded loopback SSH port, and a throwaway ed25519 key. The harness refuses
to start while any QEMU process is present, and serializes concurrent harness
launches across worktrees with a host lock. Stop existing VMs yourself; it never
stops the user's Ubuntu or UTM VMs. The window appearing on the Mac is expected.
Do not start another VM while this harness runs.

For Ubuntu, the seed server binds loopback; QEMU user networking reaches it through
10.0.2.2. It serves all four NoCloud files. GRUB is controlled through one QMP
connection using the existing `qmp-type.py` module. The serial terminal state
locates the kernel line and verifies the complete arguments before Ctrl-X.
This avoids depending on a fixed number of Down presses. The final installer
late-command marks the target complete. The host then waits for QMP RESET or the
installer media-removal prompt before ejecting (and presses Enter at that prompt).
Ejecting at the late-command alone is unsafe: the live squashfs is still needed
during shutdown. The final command runs only
after target installation, sudoers, automatic login and the installed-system
marker have been written. SSH must see that marker, so a live ISO session cannot
be mistaken for a successful installation.

Fedora boots its live image with serial console, sshd and a systemd credential
containing the throwaway public key for root. GRUB's default media-test entry is
moved up once before editing; the complete argument echo is allowed 60 seconds
to catch up. The harness uploads `ks.cfg` and starts non-live
`anaconda --cmdline --kickstart /root/ks.cfg` detached from SSH, with a fixed UTF-8
locale. `liveimg` copies the image's squashfs rather than fetching packages.
Anaconda's live mode ignores kickstarts, so `--liveinst` is deliberately absent.
The kickstart sets up tester, passwordless sudo, GDM/Plasma automatic login and
both desktops' first-run markers. It powers off; only a stopped VM advances to
ISO removal and first boot as tester. The installed-system marker is required.
Anaconda errors or exit without power-off fail the run; failures collect
`/tmp/*.log` and `/root/anaconda.out` in `anaconda-logs.tar` when SSH is available,
plus `anaconda.out` and `anaconda-monitor.log`. The live SSH phase uses
`--boot-timeout`, and Anaconda uses `--install-timeout`.

The guest package is installed, the guest reboots, and the harness waits for an
active tester Wayland session on seat0. GNOME requires the active clipboard
extension and audio/clipboard user services. KDE requires audio, clipboard and
status user services plus `linuxvm/clipboard.json` reporting `state: active`
(Guest Tools 0.3.0 or newer). The tools disc is mounted read-only by label with
sudo, including on KDE where it does not mount automatically. No person needs to
log in. Desktop login is automatic and sudo is passwordless: use these installers
only for disposable test VMs.

Timeouts: GRUB menu 180 s; installation 3600 s (`--install-timeout`); each boot
600 s (`--boot-timeout`); integration session 180 s; guest package installation
600 s; normal shutdown 90 s (10 s if still in firmware/GRUB), then forced stop
30 s. Individual host commands and QMP reads are bounded too. Installer errors/panics and unexpected early resets
fail immediately; installer debug output is mirrored into the serial log. A failed phase
names its log; command failures also save `<phase>-error.log`.

`harness-runs/<local timestamp>/` contains the seed, private SSH key,
`connection.json`, `owned-vm.json`, `host.log`, `http.log`, GRUB edit evidence,
SSH/package/session logs, OS/kernel/desktop/package versions (rpm or dpkg) in
`guest-environment.txt`, Fedora kickstart/Anaconda evidence, VM log copies
(`vm-logs/`, plus `vm-logs-final/` when cleaning up a kept VM)
and `summary.json` with phase durations.
The directory is mode 0700 and git-ignored. Keep it private. HTTP stops on success,
failure or Ctrl-C. By default the harness stops its own VM, waits for it to stop,
copies logs, then removes its folder directly, avoiding Trash disk retention.
`--keep` retains even a failed VM for investigation. Cleanup checks both the
recorded UUID and exact generated name, rejects the protected Ubuntu UUID and
never calls `linuxvmctl delete`. SIGKILL/power loss cannot run cleanup: use
`scripts/harness/cleanup RUN_DIR` afterwards.

## Guest captures

All capture tools connect to an already-running guest. They accept either
`--run RUN_DIR`, or `--port PORT --key PATH [--user tester]`. They do not start,
stop or delete VMs. Use `--install-deps` once per tool to install its guest apt
packages; apt output is saved beside the capture. Existing guests need
passwordless sudo for dependency installation and input recording.

```sh
scripts/harness/monitor-state --run "$run" --install-deps --output "$run/monitor.json"
scripts/harness/screenshot --run "$run" --output "$run/desktop.png"
scripts/harness/record-input --run "$run" --install-deps --seconds 15 --output "$run/input.json"
scripts/harness/analyze-input "$run/input.json" --output "$run/input-analysis.json"
scripts/harness/presentation-timing --run "$run" --install-deps --seconds 15 --output "$run/timing.json"
scripts/harness/presentation-timing --run "$run" --seconds 15 --cpu-load 4 --output "$run/timing-load.json"
```

For the user's **already-running** Ubuntu VM, the connection form is
`--port 2222 --key test-media/ssh/id_ed25519 --user tester` (use the key's absolute
path if it lives in another checkout). Do not start that VM as part of harness QA.
Captures explicitly requested on a guest may install packages or grant portal
permissions there; the fresh-install and cleanup commands only own harness VMs.

`monitor-state` calls Mutter's `GetCurrentState` through python3-gi and emits JSON
with connectors, current/preferred modes and Hz, supported scales and logical
positions, scale and transforms. It also runs `edid-decode` on each nonempty DRM
EDID, retaining the full decode and a short facts list (size, timings, Hz).
This describes the guest output, not the Mac window's measured size or scanout.

`screenshot` calls the XDG Screenshot portal with `interactive=false` and copies
the resulting PNG through SSH. It **persists a test-only permission grant** for
app id `""`, table/id `screenshot`, permission `yes` in the guest permission store,
so no approval dialog needs a person. This permits other unconfined session
processes to request screenshots. Revoke it with this command in the guest
session (or delete the disposable VM):

```sh
gdbus call --session --dest org.freedesktop.impl.portal.PermissionStore \
  --object-path /org/freedesktop/impl/portal/PermissionStore \
  --method org.freedesktop.impl.portal.PermissionStore.DeletePermission screenshot screenshot ''
```

Over SSH, session commands need
`XDG_RUNTIME_DIR=/run/user/$(id -u)` and
`DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus`; tools set these, plus
`WAYLAND_DISPLAY` and `XDG_CURRENT_DESKTOP` from `systemctl --user show-environment`
(including Plasma's `wayland-1`). Only those two variables are imported, with
shell quoting. This assumes tester's active Wayland session, not a multi-seat
desktop. Package installation needs access to the distribution's repositories;
capture tools' `--install-deps` still uses Ubuntu's apt packages. Apt packages are not snapshotted, so versions and
installation durations can change even with the same ISO.

`record-input` discovers the exact QEMU Virtio Pinch Touchpad and tablet devices,
runs one line-buffered `libinput debug-events` reader per device, and records raw
evdev events with CLOCK_MONOTONIC timestamps concurrently. The JSON includes
names, device paths, debug output, process start offsets/exit codes, duration and
raw events. Debug-event clock origins are aligned approximately to each device's
first raw evdev event (libinput starts its clock at the first event, not process
launch). No Python evdev/YAML dependency is needed. It does not grab devices;
normal desktop input continues. Each debug-events reader has its own libinput
context and does not inherit Mutter's per-device runtime settings. It describes
libinput's interpretation, not whether a desktop application consumed a gesture. Lift all fingers before starting and after the
last gesture. Move the pointer into the VM and perform the gestures while it
records. An unattended idle recording verifies the collector, not gesture feel.

`analyze-input` also accepts plain debug-events text. It reports finger scroll
sequence count, signed and absolute axis distances, axis mix, duration, and
all-zero finger scroll stop; pinch/swipe counts and begin/end balance; button
events during a gesture and pointer motion during a pinch; observed raw MT slots
and BTN_TOUCH still down; and timing gaps above 100 ms (`--gap SECONDS`). Scrolls
without a stop split after a 250 ms gap and are flagged. Pauses can be intentional:
a timing gap is not evidence of loss. Debug-only files cannot establish stuck
raw contacts. Contacts already down before capture and capture-boundary
interruptions cannot be classified reliably. Distances are libinput output
units, not Mac trackpad millimetres; sequence grouping is a diagnostic heuristic.

## Presentation timing: measurement contract

The fixed workload is an 800×600 GTK4 DrawingArea with a solid background and an
80×80 rectangle moving horizontally at 200 logical pixels/second. Each GTK tick
queues a redraw. `--cpu-load N` adds N independent Python busy-loop processes,
terminated when the workload exits. Keep the VM window visible and avoid other
activity when comparing runs; the display/window state and host load matter.
There is no warmup phase. First-login background work and cold caches can affect
the result; repeat in a consistent guest state before comparing CPU variants.

The collector queries completed GdkFrameTimings for every requested tick, using
`presentation_time` and `refresh_interval` from compositor presentation feedback.
It retains raw frame counters and timestamps (microseconds), the requested frame
count, incomplete feedback count and zero-presentation count. The report computes
adjacent positive presentation intervals, mean, median, linearly interpolated
p95/p99, longest gap, and intervals greater than 1.5× that frame's reported refresh
interval as stalls. The guest refresh rate is the inverse of the median reported
refresh interval. No frame-clock estimate substitutes for missing presentation
feedback. Fewer than two presented frames is an error with raw output preserved.

This observes when Mutter presented the workload to the guest virtio-gpu output
(guest-side page flips/presentation feedback). It does **not** observe QEMU's host
texture uploads, Cocoa display scheduling, macOS composition, physical panel
scanout, input-to-photon latency, tearing, visual correctness, audio, or all other
guest applications. A stall can reflect workload, GTK, Mutter, guest scheduling
or virtualization delays; the report does not attribute causality. It is not a
Mac refresh-rate measurement. Missing feedback and coalesced/redrawn frames mean
requested ticks and presented frames need not match. Intervals spanning missing
feedback can resemble stalls; inspect frame counters and missing-feedback counts.
The app has a wall-time
watchdog for hidden windows/no ticks; keep its stderr with the JSON.

## Lifecycle soak

```sh
scripts/harness/soak --run "$run" --rounds 5
```

Repeats, on the run's kept VM: start, guest reboot, a simulated Mac sleep (the supervisor's `LINUXVM_DEBUG_SLEEP_SIGNALS` path, 30 s paused by default) and shutdown. Each boot must reach the desktop with the clipboard extension and the guest tools' units active, and must send a fresh guest status report. The guest clock must be within 1.5 s of the Mac's, both after each boot and within 30 s of the simulated wake. It flags failed `linuxvm` units, ext4 recovery or orphan messages (a clean shutdown leaves none), a supervisor or QEMU change across the guest reboot, forced stops and bridge restarts in `supervisor.log`, and a QEMU exit status other than 0. Results go to `soak.json` and `soak.log` in the run directory. `LINUXVMCTL` chooses the build under test; `linuxvmctl start` then runs that build's supervisor. The tool only touches the run's own `harness-` VM.

## Touchpad contact lifecycle

```sh
scripts/harness/touch-lifecycle --run "$run" --sleep-signals --reboot
```

Replays two-finger contacts through QMP `input-send-event` while the guest records them with `record-input`, then checks the `analyze-input` result. A scenario fails if contacts are still down at the end, if begins and ends are unbalanced, if a button event arrives during a gesture, or if a scroll ends without a stop. The scenarios:

- a baseline scroll and pinch;
- a pause in the middle of a scroll, with the lift sent while paused (QEMU refuses input then, as Cocoa's lifts are lost): through QMP `stop`/`cont`, and with `--sleep-signals` through the supervisor's sleep path (the VM must have been started with `LINUXVM_DEBUG_SLEEP_SIGNALS=1`);
- a scroll that continues after a pause;
- 15 quick scroll and pinch cycles;
- a scroll that turns into a pinch without lifting. This one is informational: libinput keeps it a scroll, and Cocoa never sends it because it ends the scroll's contacts before a pinch.
- with `--reboot`, a guest reboot with contacts down, then a fresh scroll.

QMP bypasses the Mac trackpad, Cocoa's gesture translation and focus handling. Focus loss and real gestures still need a person.

## Tests and recorded validation

```sh
/opt/homebrew/bin/python3.14 -m unittest discover scripts/harness/tests
```

See `REPORT.md` for the real Mac run, phase timings, evidence paths, QMP
multi-touch investigation and remaining verification limits.
