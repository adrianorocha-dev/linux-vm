Validated on this 16 GiB Apple Silicon Mac on 2 November 2026, using the installed
`/Applications/Linux VM.app/Contents/Helpers/linuxvmctl`, its QEMU 11.1.1 runtime,
and the supplied Ubuntu 26.04.1 arm64 desktop ISO. The app was not rebuilt or
replaced. Work is on `t3/milestone-2-test-harness`.

The implemented commands are `fresh-install`, `ssh`, `cleanup`, `monitor-state`,
`screenshot`, `record-input`, `analyze-input`, and `presentation-timing` in this
directory. [README.md](README.md) documents their arguments, dependencies,
permissions and measurement contract. Typical use:

```sh
scripts/harness/fresh-install --keep
run=harness-runs/<printed timestamp>
scripts/harness/ssh "$run" uname -a
scripts/harness/monitor-state --run "$run" --install-deps --output "$run/monitor.json"
scripts/harness/screenshot --run "$run" --output "$run/desktop.png"
scripts/harness/record-input --run "$run" --install-deps --seconds 15 --output "$run/input.json"
scripts/harness/analyze-input "$run/input.json" --output "$run/input-analysis.json"
scripts/harness/presentation-timing --run "$run" --install-deps --seconds 15 --output "$run/timing.json"
scripts/harness/presentation-timing --run "$run" --seconds 15 --cpu-load 4 --output "$run/timing-load.json"
scripts/harness/cleanup "$run"
```

Omit `--keep` for install/verification followed by automatic cleanup. Capture tools
also accept `--port PORT --key KEY --user tester` for an already-running guest.
`LINUXVMCTL`, `--iso PATH`, and `--deb PATH` provide the requested overrides.

The successful unattended run is
[`harness-runs/20261102-124520`](../../harness-runs/20261102-124520/), VM
`511C9446-10D1-4511-B3FB-9F446820D2C8`, SSH port `61456` (now deleted). From launch
to an active tester Wayland session on seat0, with the clipboard extension ACTIVE
and both integration user services active, it took **798.961 seconds: 13m 19s**.
It installed the disc's `linuxvm-guest 0.1.0` and rebooted without anyone logging
in. No diagnostic keys were sent after the automatic GRUB edit in this run.

The actual [summary.json](../../harness-runs/20261102-124520/summary.json), after
cleanup, is:

```json
{
  "phases": {
    "seed": 0.238,
    "create": 1.496,
    "grub": 21.670,
    "install": 621.367,
    "installer_reboot": 97.679,
    "first_boot": 21.469,
    "guest_tools": 4.621,
    "tools_reboot": 18.907,
    "session": 11.459
  },
  "success": true,
  "kept": false,
  "total_seconds": 798.961,
  "cleaned_up": true
}
```

Phase durations are seconds. The live installer's graphical-session shutdown
accounted for most of the 97.679-second reboot phase. HTTP logs show successful
fetches of all four seed files and the final completion marker. The QMP log
records guest media ejection followed by `RESET`, reason `guest-reset`; only then
did the host eject/persist removal of the installer ISO. See
[session.log](../../harness-runs/20261102-124520/session.log),
[HTTP log](../../harness-runs/20261102-124520/http.log),
[QMP events](../../harness-runs/20261102-124520/qmp-events.jsonl), and
[guest versions](../../harness-runs/20261102-124520/guest-environment.txt).
The installed system was Ubuntu 26.04.1, kernel 7.0.0-42-generic, GNOME Shell 50.1,
GTK 4.22.4 and libinput 1.31.1. Ubuntu packages are fetched from current repositories;
the harness is repeatable automation, not a frozen package snapshot.

The real capture outputs are:

- [Desktop PNG](../../harness-runs/20261102-124520/desktop.png): 2240×1260 pixels,
  obtained through the guest Screenshot portal without a dialog or host capture
  permissions. I inspected the PNG. GNOME's first-login Welcome app remains
  visible; the user is logged in and the integration is active. Dismissing that
  app is not automated.
- [Monitor JSON](../../harness-runs/20261102-124520/monitor.json): `Virtual-1`,
  current and preferred mode 2240×1260 at 119.998604 Hz, logical origin (0,0),
  scale 1.666667, transform 0. EDID describes 260×150 mm and preferred DTD
  2240×1260 at 119.998600 Hz. Full mode lists and EDID decode are retained.
- [First timing report](../../harness-runs/20261102-124520/timing.json): 15 seconds,
  879 presented frames, 878 intervals, no missing/unfinished feedback. Mean
  16.353 ms, median 14.297 ms, p95 35.892 ms, p99 57.057 ms; 536 intervals above
  1.5× reported refresh, longest 88.324 ms, guest-reported refresh 120.0048 Hz.
  These are observations, not a smoothness acceptance pass.
- [Four-process CPU-load report](../../harness-runs/20261102-124520/timing-load.json)
  and [a later no-load repetition](../../harness-runs/20261102-124520/timing-warm.json)
  also completed with usable presentation feedback. These first-login runs have
  no warmup or controlled background load, so they do not establish a causal
  CPU-load comparison. The raw frames are available for inspection.
- [Idle input capture](../../harness-runs/20261102-124520/input-idle.json),
  [gesture capture](../../harness-runs/20261102-124520/input-mtt.json),
  [analysis](../../harness-runs/20261102-124520/input-mtt.analysis.json),
  [repeat capture](../../harness-runs/20261102-124520/input-mtt-repeat.json), and
  [tablet capture](../../harness-runs/20261102-124520/input-tablet.json). The
  gesture sample contains 770 raw evdev events and 118 parsed libinput events:
  one vertical scroll, 36 scroll events including its stop, total distance
  110.25 libinput units, duration 1.110 s; two pinch begins, 72 updates and two
  ends; no unexpected buttons/motion or contacts left down. The repeat produced
  the same counts and distances, with different delivery timing. The tablet
  capture contains three absolute pointer events and nine raw events.

The screenshot tool deliberately grants the empty app id the screenshot
permission in this disposable guest. The README explains that persistent grant
and its revocation. Deleting the VM removed the grant. Input readers use their
own libinput contexts, rather than Mutter's runtime device configuration.
Libinput emitted “missing right button, assuming it is a clickpad” for the
virtual touchpad; the raw capture retains that warning. It was not investigated
as a separate runtime issue here.

QMP multi-touch replay is **empirically feasible**. The installed runtime's live
schema exposes `input-send-event` → `mtt`; the pinned QEMU `ui/input.c` dispatches
it, and Try Omarchy's `qemu-cocoa-pinch-zoom.patch` registers an MTT handler for
`virtio-pinch-pci`. The probe sent 127 accepted requests and libinput reported the
scroll and pinch sequences above. Its
[Python experiment](../../harness-runs/20261102-124520/probe-mtt.py) and
[accepted requests/results](../../harness-runs/20261102-124520/mtt-probe.json)
are saved with the run.

Each request groups both contacts into one sync frame. For each slot 0 and 1,
send an `mtt` `update` with its tracking id, followed by `data` events for x/y.
The tested starting coordinates were x=16384±125, y=16384. Move both contacts
together for scroll, or change their separation for pinch. Release **both** with
`type: "end"`, `tracking-id: -1` (axis/value are still mandatory schema fields).
The QMP `device` parameter names a display device, not the touchpad; this probe
omits it. A complete release request is:

```json
{"execute":"input-send-event","arguments":{"events":[{"type":"mtt","data":{"type":"end","slot":0,"tracking-id":-1,"axis":"x","value":0}},{"type":"mtt","data":{"type":"end","slot":1,"tracking-id":-1,"axis":"x","value":0}}]}}
```

This could support automated contact-lifecycle and pause/resume checks. A maintained
replay command and pause/resume regression suite were not built. QMP bypasses
Cocoa's translation, focus handling, scroll gain and the physical Mac trackpad;
those paths and real swipes remain unverified. The probe is an experimental run
artifact with a finally-block release, not a claim of calibrated real-time replay.

Problems found and fixed during implementation:

- Fixed Down counts landed on `set gfxpayload`, as anticipated in the brief.
  The harness now reconstructs the serial terminal, handles firmware private CSI
  sequences and GRUB borders/wrapping, finds `linux`, and verifies its arguments.
- An open single-client QMP connection blocked later connections. The helper now
  provides explicit close and event reading, preserves partial reads across
  timeouts, and releases control before `linuxvmctl` needs it.
- Ejecting at the final late-command was unsafe: the live squashfs was still
  needed, producing I/O errors and a kernel panic on a discarded attempt.
  The final implementation syncs the target and waits for actual reset or the
  media-removal prompt. The clean successful run verified the reset route.
- `nohup` tried to create `nohup.out` in a read-only installer directory. A
  detached `setsid` tail now mirrors installer diagnostics to serial.
- Real libinput output inserts repetition counters before timestamps. The parser
  now handles them. Independent debug readers also start their clocks at the
  first hardware event; the analyzer aligns them approximately with raw evdev.

Sixteen tests pass with
`/opt/homebrew/bin/python3.14 -m unittest discover scripts/harness/tests`.
They cover seed generation, the actual captured gesture sample, deliberate
bad/unbalanced gestures and stuck contacts, timing statistics, serial editor
reconstruction, QMP event/timeout handling, and protected-VM cleanup guards.
`git diff --check` passes. The captured fixture is committed; complete run
artifacts, private keys and repeated timing reports stay git-ignored.

Cleanup is verified in
[cleanup-verification.json](../../harness-runs/20261102-124520/cleanup-verification.json).
The successful VM was kept only for captures, then stopped and removed directly.
A separate [Ctrl-C run](../../harness-runs/20261102-130716-interrupt/summary.json)
exercised the default failure cleanup: seed server stopped, VM stopped, logs
preserved, folder removed. All **seven** VM UUIDs created across development and
validation have no remaining VM folders. The sole remaining VM is the original
`8F611ECF-72A8-4B1B-A54E-811509AC6902` (“Ubuntu”), stopped and untouched. No UTM VM
was operated, and the Mac was never put to sleep.

Remaining limits: no manual Mac trackpad/swipe test; no newer candidate `--deb`
installation test; no physical Mac presentation/scanout measurement; no external
monitor or multi-seat validation; no real run against the existing Ubuntu VM.
The default disc path, portal screenshot, monitor/EDID capture, both input
readers, baseline/CPU-load timing, fresh install and real Ctrl-C cleanup were
verified. The media-removal-prompt branch was not needed in the successful run.

No other documentation was edited. Proposed text for the milestone plan:

> Workstream 1 now has `scripts/harness/`: fresh unattended install with automatic
> GNOME login and integration checks, guest monitor/EDID and PNG capture,
> libinput/evdev recording and analysis, and GTK presentation-feedback timing.
> A 4 GiB/four-CPU fresh run completed in 13m 19s on this Mac; all disposable VMs
> were removed. Timing observes guest virtio-gpu presentation, not Mac scanout.
> QMP MTT replay reaches the virtual touchpad; physical trackpad behavior, swipes
> and pause/resume contact lifecycle still need their workstream-specific checks.
