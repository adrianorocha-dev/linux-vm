# Guest tools 0.2.0 implementation report

Implemented entirely within `guest/`. No VM was started, stopped, contacted or
accessed over SSH. No changes to macos/, scripts/, docs/ or runtime/.

## Changes and choices

- Package/control/disc version 0.2.0; extension version 2 with shell-version
  unchanged at `["50"]`. build.py generates the package's `version.py` from its
  VERSION constant, includes it in md5sums, and status imports it without dpkg.
- Root clock helper, credential/RTC-gated oneshot and 5-second boot/60-second
  inactive timer. Deliberate RTC name selection, whole-second lower-bound
  comparison, maximum 2-second sample, strictly >5-second forward-only recovery,
  no RTC writes, and nonblocking try-restart of active timesyncd. Sandbox retains
  only CAP_SYS_TIME. Wake triggers use a five-second monotonic coalescing window.
  Adapted from the specified local Try Omarchy helper, units and clock document;
  MIT attribution extended in the installed copyright file.
- Graphical-session status agent, port condition and active-seat udev access.
  Reports startup, matching extension signals, Shell owner changes and queries.
  Reads PRETTY_NAME/ShellVersion/GetExtensionInfo; maps the six contract states.
  Bounds strings and UTF-8 lines, ignores unknown keys/types and malformed lines,
  discards oversized lines through their newline and exits on transport failure.
- Extension checks session-bus connection UID/PID and exact unified user cgroup
  before accessing either clipboard method. Per-name credential results are
  invalidated on NameOwnerChanged, including in-flight authorization races.
  Agent ExecStart directly runs Python in linuxvm-clipboard.service. Same-user
  cgroup impersonation and cached-caller migration remain possible; this is
  documented, alongside existing snap/Flatpak D-Bus mediation.
- Replaced makehybrid and its normalizer with xorriso Rock Ridge/Joliet.
  Explicit root ownership, 0755 root directory/install.sh, 0644 payload files,
  fixed timestamps and exact LINUXVM-TOOLS label. PATH lookup precedes Homebrew
  fallback; missing xorriso has an actionable error. Installer selects exactly
  one matching package, without a version literal.
- postinst enables/starts new system units on configure, including upgrades,
  and enables status globally for next login. prerm stops new units, including
  agents in existing sessions; remove/deconfigure disables them, upgrade retains
  enablement. Existing postrm already reloads system/user managers and udev on
  remove/purge, leaves upgrade alone, and removes timezone state only on purge;
  it required no change. The 0.1.0 prerm runs during a real 0.1.0 upgrade; the new
  postinst then enables the additional units. Logout/login remains required.

No scope deviations. The RTC helper is named clock.py and invoked by Python,
so package data scripts remain 0644; the disc installer is executable. No GNOME
refresh unit is shipped because GnomeWallClock's cancel-on-set timerfd handles
clock steps. xorriso emits its expected strict-ISO9660 warning for the required
hyphenated label; both primary and Joliet descriptors retain the exact label.

## Validation performed on macOS

All commands exited 0:

```sh
python3 guest/build.py
PYTHON=/opt/homebrew/bin/python3.14 guest/build-tools-iso.sh
/opt/homebrew/bin/python3.14 -m unittest discover guest/tests -v
git diff --check
```

Test output: `Ran 34 tests in 0.290s` / `OK`. Includes Node ESM syntax checks and
an executed cgroup predicate test, shell syntax, package paths/modes/ownership/
version source/md5sums, clock decisions and mocked step/restart, wake coalescing,
status encoding/state mapping/UTF-8 validation/query framing and recovery,
Rock Ridge PX/NM metadata and ownership/modes, Joliet names, labels and payloads.
Existing clipboard/audio/timezone/share tests continue to pass.

Two consecutive complete builds were compared as bytes using Python:

- `linuxvm-guest_0.2.0_all.deb`: identical, 18476 bytes,
  SHA256 `318ed4d9b3657f208b1fc683fc7a783d5ba9703db9c9982dfb1bb2e3bd18369a`.
- `guest-tools.iso`: identical, 399360 bytes,
  SHA256 `94645152a6dff6c1d76434e58154f12f13c66cc06a58013319acf6fdfc59f2f0`.

Artifacts are generated in ignored `guest/dist/`, not committed. Repeat with:

```sh
python3 - <<'PY'
from pathlib import Path
import hashlib, os, subprocess
paths = [Path('guest/dist/linuxvm-guest_0.2.0_all.deb'), Path('guest/dist/guest-tools.iso')]
env = {**os.environ, 'PYTHON': '/opt/homebrew/bin/python3.14'}
subprocess.run(['guest/build-tools-iso.sh'], env=env, check=True)
before = [p.read_bytes() for p in paths]
subprocess.run(['guest/build-tools-iso.sh'], env=env, check=True)
for path, previous in zip(paths, before):
    data = path.read_bytes()
    assert data == previous, path
    print(path, len(data), hashlib.sha256(data).hexdigest())
PY
```

## In-guest verification checklist for integrator

These checks remain unperformed. Use the fresh disposable Ubuntu VM already
allocated to integration; run user commands in its GNOME terminal. Do not run
the deliberate clock offsets on an unrelated machine.

1. Disc and upgrade from installed 0.1.0:

   ```sh
   cd /media/"$USER"/LINUXVM-TOOLS
   stat -c '%a %u:%g %n' . install.sh README.txt linuxvm-guest_0.2.0_all.deb
   sudo apt-get install ./linuxvm-guest_0.2.0_all.deb
   dpkg-query -W linuxvm-guest
   systemctl is-enabled linuxvm-clock-recovery.service linuxvm-clock-recovery.timer
   systemctl is-active linuxvm-clock-recovery.timer
   systemctl --global is-enabled linuxvm-status.service
   systemctl list-timers linuxvm-clock-recovery.timer
   ```

   Expect directory/install.sh 755, payloads 644, ownership 0:0, package 0.2.0,
   enabled units and active timer. The successful oneshot normally becomes
   inactive again. On a separate clean-install pass execute `./install.sh` from
   the mounted disc, proving Rock Ridge execution works. Log out and back in.

2. Graphical session, port ACLs, cgroup and D-Bus:

   ```sh
   systemctl --user status linuxvm-clipboard.service linuxvm-status.service
   systemctl --user show linuxvm-clipboard.service -p MainPID -p ControlGroup
   cat /proc/$(systemctl --user show linuxvm-clipboard.service -p MainPID --value)/cgroup
   getfacl /dev/virtio-ports/dev.linuxvm.{clipboard,audio,status,timezone}
   gnome-extensions info clipboard@linuxvm.dev
   gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell \
     --method org.freedesktop.DBus.Properties.Get org.gnome.Shell ShellVersion
   gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell \
     --method org.gnome.Shell.Extensions.GetExtensionInfo clipboard@linuxvm.dev
   gdbus call --session --dest dev.linuxvm.Clipboard --object-path /dev/linuxvm/Clipboard \
     --method dev.linuxvm.Clipboard1.GetSelection
   gdbus call --session --dest dev.linuxvm.Clipboard --object-path /dev/linuxvm/Clipboard \
     --method dev.linuxvm.Clipboard1.SetSelection 'text/plain;charset=utf-8' '[byte 65]'
   ```

   Expect both user agents active, agent PID in the exact user unit cgroup,
   active user's read/write ACL on clipboard/audio/status, root-only timezone,
   extension version 2 active on Shell 50. Both terminal clipboard calls must
   fail with dev.linuxvm.Clipboard.Error.AccessDenied and leave clipboard intact.
   Verify actual Mac↔guest text and PNG copy/paste still work through the agent.
   Disconnect a caller and retry to exercise cache invalidation; disable/enable
   extension while calls are in flight and check Shell logs for no GJS errors.

3. Status protocol, with host supervisor's test transport capturing raw lines:

   ```sh
   journalctl --user -u linuxvm-status.service -b
   gdbus monitor --session --dest org.gnome.Shell --object-path /org/gnome/Shell
   gnome-extensions disable clipboard@linuxvm.dev
   gnome-extensions enable clipboard@linuxvm.dev
   systemctl --user restart linuxvm-status.service
   ```

   Startup/restart must send package 0.2.0, PRETTY_NAME and ShellVersion, with
   each line <=4096 bytes including newline. Disable/enable must report
   inactive/active (clipboard agent may auto-enable after a delay). Using the
   host transport, send `{"type":"query","future":1}\n`: expect a reply.
   Send unknown type, malformed JSON, invalid UTF-8, UTF-16 JSON and a line
   longer than 4096 bytes, followed by a valid query: only the valid query
   replies, agent remains active. Test missing/outdated/error/transition states
   with extension fixtures in the disposable VM; expect missing/outdated/error/
   unknown respectively. Re-login (Shell owner replacement) must report afresh.
   Simulate port EOF/disconnect: agent fails, systemd restarts and reconnects
   with a fresh status. With an older host lacking the status port, the unit is
   condition-skipped and existing integrations continue working.

4. RTC gate, fallback and actual Mac sleep/wake:

   ```sh
   cat /sys/class/rtc/rtc*/name
   systemctl cat linuxvm-clock-recovery.service linuxvm-clock-recovery.timer
   sudo systemctl start linuxvm-clock-recovery.service
   timedatectl show -p TimeUSec -p RTCTimeUSec -p NTPSynchronized
   journalctl -u linuxvm-clock-recovery.service -u linuxvm-timezone.service -b
   ```

   Expect rtc-efi or PL031 selected and credential imported, no step when near
   RTC. In a VM launched without linuxvm.host, unit must be condition-skipped;
   direct `sudo env -u CREDENTIALS_DIRECTORY python3 /usr/lib/linuxvm/clock.py`
   must do nothing. For controlled offset tests first record NTP state and stop
   the fallback timer; avoid the timer racing the manual observation:

   ```sh
   sudo systemctl stop linuxvm-clock-recovery.timer
   sudo timedatectl set-ntp false
   sudo date -s '15 seconds ago'
   sudo systemctl start linuxvm-clock-recovery.service
   date -u
   sudo date -s '15 seconds'
   sudo systemctl start linuxvm-clock-recovery.service
   date -u
   ```

   Behind must step forward; ahead must remain ahead (no backward correction).
   Repeat at <=5-second lag: no recovery step. With timesyncd inactive, recovery
   must leave it inactive; repeat with active timesyncd and inspect its journal
   for restart after a step. Restore original NTP state, correct any test offset
   with network time, and restart the timer. Verify successive fallback runs
   are about 60 seconds after inactivity, even without wake messages.
   Then perform a real Mac sleep/wake >5 seconds: system clock catches RTC,
   GNOME top bar refreshes without a refresh unit, logs show one recovery for a
   burst of wake messages. Repeat with host pause-on-sleep disabled. No RTC
   writes should occur. Slow-sample/precision rejection is unit-tested; runtime
   fault injection can confirm the helper fails rather than stepping on >2s I/O.

5. Removal/purge and regressions:

   ```sh
   sudo apt-get remove linuxvm-guest
   systemctl --global is-enabled linuxvm-status.service
   systemctl is-enabled linuxvm-clock-recovery.timer
   systemctl --user is-active linuxvm-status.service linuxvm-clipboard.service
   sudo apt-get purge linuxvm-guest
   test ! -e /var/lib/linuxvm/timezone.json
   ```

   Expect disabled/not-found units, stopped session agents, no dangling global
   enablement links and no timezone state after purge. Repeat install/remove
   while logged in; confirm only package-owned share links are removed and
   existing files survive. Reinstall and smoke-test audio route selection,
   timezone manual opt-out persistence, shared-folder links and touchpad defaults.

## Proposed changes outside owned scope

No contract edits are necessary: implementation follows the updated sections.
For host release notes, proposed text: “Guest Tools 0.2.0 reports integration
status, recovers guest time after Mac sleep, restricts clipboard D-Bus access to
its agent, and ships an executable disc installer. Log out and back in after
upgrading.” Integrator must validate the host's status query/notification path
and older/newer host compatibility; those files were not changed here.
