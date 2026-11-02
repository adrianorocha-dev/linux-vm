# Milestone 2 plan: make the experience the product

Milestone 1 delivered a working app, supervisor and guest tools ([proposal](proposal.md#milestone-1-first-build)). Milestone 2 makes the experience dependable in daily use and measurable against Try Omarchy and macOS. Its scope comes from the proposal's [Milestone 2](proposal.md#milestone-2--make-the-experience-the-product) and [validation criteria](proposal.md#what-smooth-must-mean-in-our-validation).

## Starting state

- **App:** `/Applications/Linux VM.app`, built from `main`. Rebuild with `scripts/build-app.sh` and copy the result over the installed app.
- **VM:** "Ubuntu", imported from the Milestone 0 prototype, with the guest tools installed. It runs on 8 GB with SSH forwarded to port 2222 (`scripts/ssh-vm.sh 2222 …`).
- **Installer:** `test-media/ubuntu-26.04.1-desktop-arm64.iso`, plus the autoinstall seed used for the Milestone 1 fresh-install test. Both are git-ignored.
- **Runtime build inputs:** `.deps/` ([runtime/README.md](../runtime/README.md)).

## Workstreams

### 1. Test harness first

Everything else is measured with it.

- **Unattended fresh install.** Turn the Milestone 1 manual steps into one script: generate a throwaway key and password hash, serve the autoinstall seed, type the GRUB arguments over QMP, wait for the installed system, install the guest tools and log in. Today these steps live in `scripts/qmp-type.py` and shell history.
- **Guest-side capture.**
  - `libinput debug-events` recordings for scroll, pinch and swipe.
  - Mutter's monitor state, meaning mode, refresh and scale.
  - Screenshots from inside the guest, since QMP `screendump` is black under VirGL.
- **Presentation timing.** A defined workload and a tool that reports frame intervals and stalls, and documents exactly what it observes.

### 2. Trackpad

- **Scrolling:** check short scrolls, diagonal and horizontal motion, flicks and kinetic glide against the same page in macOS. At 0.4 the feel is "much closer, not perfect", and slow scrolls may need their own gain curve rather than one constant.
- **Pinch and swipe:** pinch begin, update and end. Zoom should stay at the pointer, and repeated pinches should work. Check browser back and forward.
- **Lifecycle:** losing focus mid-gesture, switching between scroll and pinch, pause and resume, and reboot. None of these should leave a stuck contact, a click or duplicated momentum.

### 3. Cursor and display

- **Cursor:** alignment, hotspot transitions and response under load, with the guest-drawn cursor. An `NSCursor` built from the cursor plane is the fallback if delay appears.
- **Window and full screen:**
  - Mutter following window resizes outside full screen. This is untested; only full screen was measured.
  - Full-screen transitions.
  - Notch handling.
- **External displays:** moving between displays with different scale and refresh. This is untested.

### 4. Host lifecycle

- **Mac sleep:** pause running VMs when the Mac sleeps and resume them when it wakes, as Try Omarchy's `VMHostSleepController` does. Then correct the guest clock. This is on by default, with a per-VM setting to turn it off.
- **Storage:** stop cleanly when the storage volume disappears.
- **Login:** VMs do not start at login. This was decided on 2 November 2026.

### 5. Guest integration that survives updates

- **GNOME versions:** the extension declares `shell-version: ["50"]`, so a GNOME 51 upgrade would disable it. Choose a version policy. Updates ship only on the Guest Tools disc for now; there is no apt repository. The app should say when a VM's installed package is older than the disc's.
- **Package updates:** version every package change, and make each app version work with older and newer packages.

### 6. Carried over from Milestone 1

- **Unverified:**
  - images through the clipboard;
  - audio playback and recording by ear;
  - starting a VM by clicking in the app.
- **Guest tools disc:** it lacks Rock Ridge, so `install.sh` is not executable. Build it with a tool that writes Rock Ridge, or ship a launcher the Files app can run.
- **Clipboard access:** any process in the session can call the clipboard D-Bus interface. Restrict callers, for example to the agent's unique bus name or a same-user check.
- **VirGL:** Apple's GLSL 4.10 rejects shaders that request `GL_ARB_draw_instanced`, and their draws are dropped. Find which apps hit this.
- **Branding:** the bridge helper's log lines say "Omarchy". This is cosmetic and needs a helper patch.

## Progress

### First wave (2 November 2026)

GPT-6.1-Sol built three modules against the updated [contract](host-guest-contract.md); Claude reviewed, fixed and integrated them, added the app UI and verified them on fresh VMs installed by the harness.

- **Test harness** ([scripts/harness](../scripts/harness/README.md)). `fresh-install` installs Ubuntu unattended, with automatic GNOME login and the guest tools, in about 13½ minutes (4 GB, 4 CPUs). It refuses to run beside another VM, removes only VMs it created, and cleans up on Ctrl-C. Guest-side tools capture Mutter's monitor state and EDID, a PNG through the screenshot portal, libinput and evdev recordings with an analyzer, and frame timing. QMP multi-touch events reach the virtual touchpad, so scroll and pinch can be replayed without a person.
- **Mac sleep.** The supervisor pauses a running VM when the Mac sleeps, unless its new "Pause while the Mac sleeps" setting is off, and resumes only a pause it made. After every wake it prompts Linux, which steps its clock forward from the RTC when it is more than 5 seconds behind. The shutdown deadline no longer counts Mac sleep. Verified with simulated sleep (`LINUXVM_DEBUG_SLEEP_SIGNALS`): after 40 seconds paused, the guest clock was within 0.1 s of the Mac's a second after wake, and with the setting off the VM kept running and still got its wake. A real Mac sleep is verified too (see below).
- **Guest status.** Guest tools 0.2.0 report their version, Ubuntu and GNOME versions and the clipboard extension's state on `dev.linuxvm.status`. The supervisor keeps the last report in `guest.json`; the app's new Guest Tools section and `linuxvmctl status` show it and say when the disc is newer. Verified live, including the extension being turned off and on.
- **Upgrade.** A fresh VM with guest tools 0.1.0 sent no report, and the app worked without one. `./install.sh` from the new disc upgraded it to 0.2.0: the system units started at once, and after the next login the extension was active again and a 0.2.0 report arrived. Until that login the clipboard is off, as the installer says. Removing and purging the package left no units or state behind.
- **GNOME version policy.** The extension lists only tested GNOME versions. After an untested GNOME upgrade the report says `outdated` and the app says so; updates ship on the disc.
- **Carried over from Milestone 1.** The disc now has Rock Ridge, and `./install.sh` runs from it. The clipboard D-Bus interface accepts only the clipboard agent's unit; other callers get `AccessDenied`. Mac → guest text still crossed through the agent.

Fixed during verification: GNOME's version was missing from the first status report after login; Ubuntu 26.04 runs chrony, not systemd-timesyncd, so the clock recovery failed after a successful step; the app's Shut Down had been routed through the supervisor's deadline signal.

First presentation measurements (harness run `20261102-124520`, an 800×600 GTK animation in a 2240×1260 window at 120 Hz and scale 1.67). They observe the guest compositor's presentation feedback, not the Mac's display:

| Run | Median | p95 | Intervals over 1.5 frames |
|---|---|---|---|
| Right after first login | 14.3 ms | 35.9 ms | 61% |
| Idle, repeated | 8.9 ms | 18.5 ms | 34% |
| Four busy guest processes | 8.0 ms | 10.1 ms | 2% |

The guest paces frames better when it is busy than when it is idle. Slow vCPU wakeups or macOS scheduling QEMU's threads on efficiency cores are the first suspects.

### At the Mac (2 November 2026)

The user's "Ubuntu" VM was upgraded from guest tools 0.1.0 to 0.2.0 with `./install.sh`; after the next login it reported 0.2.0, GNOME 50.1 and an active extension.

- **Clipboard.** Text crossed both ways, Mac → guest and guest → Mac.
- **Real Mac sleep.** The Mac slept from 17:04 to 18:06 UTC. The supervisor paused QEMU at 17:04:00, five seconds before macOS logged the sleep. Power Nap was on, and the VM stayed paused through about 20 dark wakes, one of them 20 minutes long, and resumed at 18:06:30, a second after the full wake. At 18:06:31 the guest stepped its clock forward by about 62 minutes and restarted chrony, which picked an NTP source at 18:06:38. Evidence: the VM's `logs/supervisor.log`, `pmset -g log`, and the guest journal for `linuxvm-clock-recovery` and `chrony`.

### Next

- With the user at the Mac: scrolling, pinch, swipe and cursor compared with Try Omarchy and macOS; window resizes, full-screen transitions and an external display; starting a VM from the app.
- Presentation: explain the idle pacing (full screen against window, idle against load, QEMU thread QoS) before tuning anything.
- Trackpad lifecycle checks with QMP replay: stuck contacts across pause, resume and focus loss.
- Storage that disappears.
- VirGL's `GL_ARB_draw_instanced` and the helper's "Omarchy" log lines.

## How the work is split

- **GPT-6.1-Sol** takes well-defined, non-UI modules with a written contract and tests: the test harness scripts, the sleep and storage handling in `LinuxVMCore`, guest package changes and the disc builder.
- **Claude** owns all app UI, integration, and verification on this Mac.
- **Shared contract:** host–guest interfaces stay in [host-guest-contract.md](host-guest-contract.md). Change it before changing either side.

## Done means

- Each validation area in the proposal has a repeatable check, a recorded result and the workload it used.
- Scrolling, pinch, swipe and cursor behaviour are compared side by side with Try Omarchy and macOS, and the remaining differences are written down.
- A fresh VM installs and passes the checks without manual steps, and survives repeated starts, shutdowns, reboots and Mac sleep.
- A guest update, including a GNOME update, does not silently remove the integration.

## Decisions

Made on 2 November 2026:

- **Project location:** the repository lives at `~/ccsandbox/linux-vm`.
- **Guest package updates:** only through the Guest Tools disc, for now.
- **Start at login:** VMs do not start at login.
- **Mac sleep:** VMs pause while the Mac sleeps.
