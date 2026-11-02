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

- **Mac sleep:** pause the VM when the Mac sleeps and resume it afterwards, as Try Omarchy's `VMHostSleepController` does, then correct the guest clock.
- **Storage:** stop cleanly when the storage volume disappears.
- **Login:** start chosen VMs at login. This is optional and needs a decision.

### 5. Guest integration that survives updates

- **GNOME versions:** the extension declares `shell-version: ["50"]`, so a GNOME 51 upgrade would disable it. Choose a version policy and a way to ship updates, such as an apt repository or an update on the Guest Tools disc.
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

## How the work is split

- **GPT-6.1-Sol** takes well-defined, non-UI modules with a written contract and tests: the test harness scripts, the sleep and storage handling in `LinuxVMCore`, guest package changes and the disc builder.
- **Claude** owns all app UI, integration, and verification on this Mac.
- **Shared contract:** host–guest interfaces stay in [host-guest-contract.md](host-guest-contract.md). Change it before changing either side.

## Done means

- Each validation area in the proposal has a repeatable check, a recorded result and the workload it used.
- Scrolling, pinch, swipe and cursor behaviour are compared side by side with Try Omarchy and macOS, and the remaining differences are written down.
- A fresh VM installs and passes the checks without manual steps, and survives repeated starts, shutdowns, reboots and Mac sleep.
- A guest update, including a GNOME update, does not silently remove the integration.

## Open decisions

- **Project location:** the repository lives in a T3 scratch folder. A permanent location would be safer.
- **Guest package updates:** an apt repository, or updates only through the Guest Tools disc.
- **Start at login:** whether VMs should start at login, and whether pausing on Mac sleep should be configurable.
