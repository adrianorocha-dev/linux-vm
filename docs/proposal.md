# A polished Linux VM app for macOS

Investigation and proposed architecture · 30 October 2026

**Status:** Research and design only. No wrapper implementation, runtime build, or VM migration has been started. Existing UTM VMs remain outside this project's control. This revision corrects the first draft after its claims were checked against upstream sources, and adds a survey of alternatives.

## Recommendation

Build a macOS app around a pinned QEMU runtime, initially supporting **Apple Silicon and Ubuntu ARM64 with GNOME/Wayland**. The main goal is a trackpad that feels as close to native macOS as it does in Try Omarchy v1.3.0, the latest release. In UTM, scrolling still feels poor even with the guest at 120 Hz. Try Omarchy presents trackpad scrolls and pinches to Linux as two-finger input on a virtual touchpad. Our app should reproduce that behavior closely: two-finger scrolling, pinch to zoom, the browser swipe navigation that finger scrolling enables, and wheel scrolling for mice. The one deliberate difference is the cursor. Try Omarchy shows only the macOS arrow; our app should show the guest's cursor shapes (see Cursor presentation). Make trackpad input, display quality, cursor behavior and pointer response the first engineering milestones. Add other distributions through explicit, tested guest profiles.

Start from Try Omarchy's MIT-licensed launcher, runtime builder and patches rather than writing a new app from scratch. Its launcher is small. The work that determines the experience is in the runtime patches and the guest integration, and Try Omarchy has already done most of the runtime half. Keep the input implementation separate from the launcher and guest-specific setup. Once its behavior is validated, we can adapt the useful parts for UTM and propose changes to the appropriate upstream projects.

The distinction is ownership of the experience: a UTM setup tool can select good settings, while our app can also control the runtime, presentation and input paths. We should take on that extra maintenance deliberately and keep the initial feature set narrow. The alternatives section explains why QEMU remains the practical base today, and what could change that.

## What we investigated

This document combines four kinds of evidence:

- **Local observations:** native controls and guest diagnostics from our Ubuntu VM in UTM 5.0.8, plus the user's successful 120 Hz test.
- **Source inspection:** UTM 5.0.8 and Try Omarchy's current release, **v1.2.0**, commit `4b948a8a44f5289863dd7a258378cef0ad46028f`. Earlier research used v0.5.1; its scrolling implementation alone no longer describes the current release. The user's reference experience is v1.3.0 (`13d63df`, 24 October 2026), whose scrolling patches, guest quirk and documentation are unchanged from v1.2.0. We also read UTM's CocoaSpice client, upstream QEMU master (11.1.50), the SPICE protocol headers, Mutter and GNOME's settings schemas where a claim depended on them.
- **Published documentation** for Apple's Virtualization framework, UTM, Parallels Desktop and VMware Fusion, used in the alternatives survey.
- **First Milestone 0 run (1 November 2026):** a disposable Ubuntu 26.04 VM (GNOME 50.1, Wayland) booted with the QEMU runtime bundled in the installed Try Omarchy 1.2.0, tested by the user on this Mac. Results are in [Milestone 0: first results](#milestone-0-first-results) and [the run notes](milestone-0-notes.md).
- **Proposals:** the architecture, milestones and acceptance criteria below. These are engineering recommendations, not features we have implemented or benchmarked.

Try Omarchy's reported validation results belong to that project and its test machines. We have run its bundled runtime with an Ubuntu guest, but not its gesture tests or end-to-end suite. Source claims cite upstream files at pinned tags.

## What our UTM work established

On this M1 Pro Mac, Ubuntu now has matching ARM64 hardware virtualization, a QEMU backend, `virtio-gpu-gl-pci`, Apple Core OpenGL, Auto Resolution and Retina Mode. A guest GLX diagnostic reported an accelerated **VirGL** context using the Apple M1 Pro, rather than llvmpipe. That diagnostic does not establish the renderer used by every application or by GNOME's compositor.

The initial blurry result improved after selecting **200% guest scaling** at **3024 × 1898**. Retina needs both an appropriate pixel resolution and sensible guest scaling; enabling it alone did not deliver the intended appearance.

Ubuntu originally selected **75 Hz**. That number comes from QEMU: when the display frontend supplies no refresh rate, QEMU writes 75 Hz into the virtual display's EDID ([`edid-generate.c`](https://gitlab.com/qemu-project/qemu/-/blob/master/hw/display/edid-generate.c)). UTM's SPICE display path supplies none. The user's temporary kernel argument, `video=Virtual-1:3024x1898MR@120e`, produced a displayed **120.00 Hz** mode and a perceived improvement. We then saved that exact argument, backed up GRUB defaults and validated the generated entries. A fresh normal reboot after the persistent edit remains untested. The argument is a fixed mode for this window size, not a general display-sync solution, and a VM on our own runtime should not inherit it.

UTM's FPS limit was already unset. Its 5.0.8 host view targets the display's maximum frame rate in that case. A host rendering target and a guest refresh mode are separate facts; neither proves sustained 120 fps, low input latency or adaptive ProMotion. See the [local configuration report](utm-ubuntu-report.md) and [UTM preferences documentation](https://docs.getutm.app/preferences/macos/).

For input, native controls showed Ubuntu's Capture Input off and automatic capture off. UTM's [input view](https://github.com/utmapp/UTM/blob/v5.0.8/Platform/macOS/Display/VMMetalView.swift) uses absolute positions in that mode. No input settings were changed, and pointer latency was not measured.

After the 120 Hz change, trackpad scrolling in the UTM guest still felt poor. The source explains why: refresh rate is not the cause.

- UTM's scroll handler reads `event.deltaY`, AppKit's coarse, line-based delta, rather than the point-precise `scrollingDeltaY` that trackpads provide. It ignores the horizontal axis.
- It passes that value to CocoaSpice's “smooth” scroll mode. Despite the name, [CocoaSpice](https://github.com/utmapp/CocoaSpice/blob/main/Sources/CocoaSpice/CSInput.m) adds the deltas up and sends one whole wheel-button click each time the total crosses 1.
- SPICE cannot express anything finer: its mouse messages have only up and down wheel buttons.

Linux therefore sees a mouse wheel turning one notch at a time, and each notch scrolls a fixed step of a few lines. Kinetic scrolling after a flick arrives as more notches. No guest setting can turn those steps back into continuous motion.

## How Try Omarchy achieves its integration

### The overall system

Try Omarchy packages a Swift/AppKit launcher, a patched QEMU 11.1.1 runtime and firmware, a factory guest disk, and a separate guest integration package. Its matching ARM64 guest uses Apple Hypervisor.framework. Graphics pass through virtio-gpu and VirGL to a native Cocoa display using Apple OpenGL 4.1 core. The guest remains an independently updating Omarchy system.

This is a coordinated host/runtime/guest design. The launcher alone does not provide its desktop behavior. Our first version can follow that separation while allowing a normal Ubuntu installation instead of requiring a factory image. [Architecture](https://github.com/omacom/try-omarchy/blob/v1.2.0/docs/architecture.md)

### Display resolution, scale and refresh

Upstream QEMU's Cocoa frontend already reports the host display's nominal refresh rate, which ends up in the virtual display's EDID. Try Omarchy's [dynamic-display patch](https://github.com/omacom/try-omarchy/blob/v1.2.0/macos/patches/qemu-cocoa-dynamic-display.patch) adds a fallback to the screen's maximum frame rate and refreshes the information on screen, backing-scale and fullscreen changes.

The patch has no separate channel for the backing scale. It writes the scale into the EDID's physical size, assuming 110 logical DPI and rounding to whole centimetres. It also rounds the pixel size to a multiple of 2 or 3 so that Hyprland gets whole-number logical dimensions. A guest helper reads the EDID and applies the mode and scale through Hyprland.

Mutter also picks a default scale from the EDID's DPI, so this encoding may partly work under GNOME. Mutter uses its own thresholds and remembers per-monitor choices in `monitors.xml`, so this needs a test. The Hyprland helper cannot simply be installed into Ubuntu. Our app must coordinate backing pixels, guest mode and scale continuously, including fullscreen transitions and movement between displays.

The inspected implementation does not prove adaptive refresh or sustained delivery at the selected rate. Our diagnostics should distinguish host display capability, guest-selected mode and measured frame presentation.

### Cursor presentation

Try Omarchy's [Hyprland profile](https://github.com/omacom/try-omarchy/blob/v1.2.0/guest/package/try-omarchy/files/usr/share/try-omarchy/hyprland.lua) makes the guest cursor invisible, and its [launch script](https://github.com/omacom/try-omarchy/blob/v1.2.0/macos/run-qemu-gpu.sh) runs QEMU with `show-cursor=on`, so the window shows the macOS arrow. Visible pointer motion then does not wait for the guest. Nothing carries the guest's cursor shape to the host, so the pointer stays an arrow over text fields, window edges and links. That trade-off suits a keyboard-driven tiling desktop. On GNOME it would be a regression, so we should not copy it.

A better design takes the cursor image and hotspot from the guest and draws them at the host pointer position. The pieces exist:

- Mutter 46 and later set cursor hotspots on the cursor planes of virtual GPUs ([Mutter !3337](https://gitlab.gnome.org/GNOME/mutter/-/merge_requests/3337), using the kernel's [cursor-plane hotspot support](https://patchew.org/linux/20231023074613.41327-1-aesteve@redhat.com/) for virtio-gpu). GNOME on Ubuntu 26.04 should therefore send its cursor image to the host instead of drawing it into the frame.
- Upstream QEMU's Cocoa frontend already receives that image through `dpy_cursor_define` and draws it in a separate layer. It positions the layer from the pointer position the guest reports, which adds a guest round trip to visible motion.

The frontend change is to position the guest's cursor image from the host pointer while the tablet is absolute, or to turn the image into an `NSCursor`. Verify shape changes, hotspot coordinates, visibility and scaling before suppressing any guest cursor.

The first Milestone 0 run confirmed both halves of the problem. Mutter puts a 64×64 ARGB image on the virtio-gpu cursor plane, and the user saw I-beam and resize shapes. With `show-cursor=on`, the macOS arrow was also drawn on top. The guest's cursor lagged behind it, and near the top of the screen the two separated. A second run hid the macOS arrow (`show-cursor=off`) and used immersive full screen below the notch. The user then reported no perceptible cursor delay. That leaves only the guest's cursor, still positioned from the guest. So `show-cursor=off` with the existing cursor layer is the baseline for the Ubuntu profile. An `NSCursor` built from the guest's image and hotspot remains a fallback if delay shows up under load. It would let macOS move the pointer with no guest round trip.

### Scrolling

Try Omarchy has two ways to deliver trackpad scrolling, added in different releases. The native feel we want was observed on v1.3.0, where precise trackpad scrolls take the synthetic-touchpad path described second.

**High-resolution wheel (since v0.5.0, September 2026).** The [precise-scroll patch](https://github.com/omacom/try-omarchy/blob/v1.2.0/macos/patches/qemu-cocoa-precise-scroll.patch) reads AppKit's point-precise deltas, keeps the fractional remainder between events, and sends vertical and horizontal high-resolution wheel events (`REL_WHEEL_HI_RES`, `REL_HWHEEL_HI_RES`) through virtio input. A wheel notch is 120 units, so a small trackpad movement becomes a small fraction of a notch instead of nothing or a whole one. Legacy wheel events are still sent at every 120 units for older applications. macOS momentum after a flick is forwarded the same way, so the kinetic tail comes from macOS. To carry these events the patch extends QEMU's public input API: `InputAxis` gains wheel axes, where upstream has only `x` and `y`.

**Synthetic touchpad (since v1.2.0, October 2026).** The [touch-scroll patch](https://github.com/omacom/try-omarchy/blob/v1.2.0/macos/patches/qemu-cocoa-touch-scroll.patch) instead moves two synthetic contacts on a virtual touchpad, a new `virtio-pinch-pci` device that Try Omarchy first built for pinch zoom. Linux then sees ordinary two-finger touchpad scrolling, with a scroll stop when the fingers lift. macOS momentum for that gesture is dropped, and guest applications run their own kinetic scrolling, as on a Linux laptop. The [commit that introduced it](https://github.com/omacom/try-omarchy/commit/a9b69999fcc76081d2c46f789c92870ba127d5b1) was titled “Let a two-finger swipe go back and forward in browsers”: its motivation was swipe navigation, which browsers only recognize from finger scrolling. The wheel path remains for mouse wheels, for momentum after other scrolls, and for scrolls outside the focused view.

Both paths fix what UTM gets wrong: they use precise deltas, carry the horizontal axis, and do not round to whole notches. They differ in who owns the feel. With the wheel path, macOS acceleration and momentum shape the motion and the guest applies it. With the touchpad path, the guest's libinput and toolkits shape it, which needs more guest tuning but makes applications treat the input as a touchpad. Applications also differ in how well they handle high-resolution wheel events, and some still snap to whole notches.

The touchpad path is therefore the reference, and our app should adopt it. Pinch zoom and swipe navigation need the same touchpad device, so a wheel-only design would not meet the goal. As in Try Omarchy, the wheel path remains for mouse wheels, momentum after other scrolls, and scrolls outside the focused view.

The touchpad path's [documentation](https://github.com/omacom/try-omarchy/blob/v1.2.0/docs/trackpad-scrolling.md) describes the guest configuration it needs: avoid reversing natural scrolling twice, account for libinput's recognition thresholds, and prevent synthetic motion from being rejected as a hardware jump. Contacts must also be released correctly on cancellation and focus loss. Some of that configuration carries over to GNOME and some does not. GNOME's defaults come from [`org.gnome.desktop.peripherals.touchpad`](https://gitlab.gnome.org/GNOME/gsettings-desktop-schemas/-/blob/master/schemas/org.gnome.desktop.peripherals.gschema.xml.in), and GNOME applies them to every touchpad rather than per device.

- **Jump detection.** The libinput quirk that disables jump detection for the device does not depend on the compositor and should transfer unchanged.
- **Scroll direction.** GNOME enables natural scrolling for touchpads by default. Try Omarchy moves the contacts in the direction macOS already chose and turns natural scrolling off for its device. On GNOME that would reverse scrolling a second time. A cleaner design undoes the macOS direction on the host (`NSEvent.isDirectionInvertedFromDevice`) so the contacts follow the fingers, then lets GNOME's own setting decide.
- **Tap to click.** GNOME enables it by default; Try Omarchy disables it for its device. Short scrolls land and lift two contacts quickly, which libinput could read as a two-finger tap (a secondary click). Try Omarchy's 1.6 mm first move may prevent this; it must be tested.
- **Disable while typing.** GNOME enables it by default. Test whether libinput pairs the virtual keyboard with the synthetic touchpad and suppresses scrolling after typing.
- **Scroll speed.** Neither GNOME nor libinput has a touchpad scroll-speed setting. The speed we observed combines Try Omarchy's host-side curve (contacts move 0.12 mm per point on fast scrolls, down to 0.35 times that on slow ones) with Omarchy's own Hyprland setting `touchpad.scroll_factor = 0.4` and per-terminal adjustments. On GNOME the host gesture logic must own all of that tuning.
- **Momentum.** Dropping host momentum must be tested in applications that do and do not implement kinetic scrolling.

### Pinch to zoom

The [pinch bridge](https://github.com/omacom/try-omarchy/blob/v1.2.0/docs/pinch-zoom.md) turns macOS magnification events into two contacts on the same virtual touchpad. AppKit reports only a relative magnification, not finger positions, so the bridge places two symmetric contacts 25 mm apart around a fixed centre and moves them apart or together. The fixed centre keeps the gesture from moving the pointer. Each gesture's spacing stays between 0.125 and 3.5 times the starting spacing, inside the advertised sensor; the user lifts and pinches again to go further. Ending or cancelling the gesture, leaving the view, losing window focus, invalid values and VM state changes all release both contacts. Resuming the VM sends an extra release, because QEMU drops input while the VM is stopped. Scrolling and pinch share the touchpad's two slots, so starting one ends the other.

Linux reports the result as a standard touchpad pinch, and libinput's own gesture recognition still applies. Applications must support pinch for it to do anything. Try Omarchy validates it in native Wayland Chromium and Firefox. On GNOME we must also check the applications users expect to zoom, such as the image viewer and document viewer. Rotation and three- or four-finger gestures are outside Try Omarchy's design, and outside ours.

The pinch device needs the same per-device guest settings as scrolling (no tap to click, no disable-while-typing), so the GNOME issues listed above apply to pinch as well.

### Runtime ownership

Try Omarchy's [runtime builder](https://github.com/omacom/try-omarchy/blob/v1.2.0/macos/build-qemu-gpu-runtime.sh) pins source archives and patches by checksum, then stages the runtime and dependencies. Its [launch script](https://github.com/omacom/try-omarchy/blob/v1.2.0/macos/run-qemu-gpu.sh) checks expected devices and uses QMP for control. Its feature set depends on that built runtime; arbitrary installed QEMU binaries are not equivalent.

The runtime is heavily patched. v1.2.0 carries 30 QEMU patches plus patches to VirGL and libslirp, about 9,200 lines in total. Upstream QEMU's Cocoa frontend has no OpenGL support: `gl=on` comes from [`qemu-texture-borrowing-11.1.patch`](https://github.com/omacom/try-omarchy/blob/v1.2.0/macos/patches/qemu-texture-borrowing-11.1.patch), and VirGL needs further patches to run on Apple OpenGL. The graphics path we plan to use therefore depends on the largest out-of-tree change in the stack. Apple OpenGL stops at version 4.1 core, has been deprecated since macOS 10.14, and gives the guest no Vulkan.

We should review the dependencies of the required graphics, display and input patches before selecting a baseline. Reusing a tested runtime build is a reasonable first experiment. Shipping every unrelated integration would increase our maintenance scope without proving the core experience.

## Alternatives

### Keep UTM and tune it

This is what we did. UTM 5 gives accelerated VirGL, Retina and automatic resolution. [UTM 5.0](https://docs.getutm.app/updates/v5.0/) also added Vulkan 1.3 for Linux guests through Venus and MoltenVK, though its notes say the Linux desktop itself does not render under Vulkan and the Apple Core OpenGL backend we selected does not support Vulkan.

The limits are in its input and display transport. UTM's display and input travel over SPICE through CocoaSpice. SPICE's mouse messages carry a button mask whose only scroll buttons are up and down ([`spice/enums.h`](https://gitlab.freedesktop.org/spice/spice-protocol/-/blob/master/spice/enums.h)): no horizontal axis, no high-resolution wheel and no multitouch. That is why scrolling in our VM moves in steps (see above). SPICE also supplies no refresh rate to QEMU's EDID, which is why Ubuntu chose 75 Hz. Configuration alone cannot fix either.

### Apple Virtualization.framework

Virtualization.framework offers better integration with macOS, such as Rosetta for Linux and the vmnet and USB-passthrough APIs, but its built-in Linux graphics device has no 3D acceleration. macOS 27 adds [custom Virtio devices](https://developer.apple.com/documentation/virtualization/vzcustomvirtiodevice): an app can implement its own device for Linux guests ([WWDC26 session 224](https://developer.apple.com/videos/play/wwdc2026/224/)). Early projects have already used it for 3D: [vzgpu](https://github.com/Quiet-Wolfe/vzgpu) implements a Venus-only virtio-gpu that shows guest apps as separate macOS windows, and [RiftVM](https://medium.com/@everettjf/riftvm-running-3d-accelerated-omarchy-on-a-mac-with-macos-27s-custom-virtio-3f845e1dd08e) runs an accelerated Omarchy desktop. Both are weeks old. vzgpu lists tearing, a renderer crash it patches locally, and support for only one guest.

The API has a gap that matters for input. Its [delegate](https://developer.apple.com/documentation/virtualization/vzcustomvirtiodevicedelegate) receives queue notifications and lifecycle events but no callback when the guest writes the device's configuration space. Linux's virtio-input driver discovers a device's capabilities by writing selectors into configuration space and reading the answer, so a standard virtio-input device, including a high-resolution wheel, cannot be built on this API as documented. A guest daemon creating a `uinput` device from events sent over vsock would avoid the problem (see the input core below).

Virtualization.framework is worth re-evaluating once a custom virtio-gpu matures, because it would remove our dependence on a heavily patched QEMU. Today it would mean writing and maintaining a GPU device ourselves.

### libkrun and krunkit

[libkrun](https://github.com/containers/libkrun) runs lightweight VMs on Hypervisor.framework and provides a Venus virtio-gpu that reaches the Apple GPU through MoltenVK. Its macOS front end, krunkit, is aimed at GPU access for Podman containers. Its README does not describe a display window or input devices; community forks have added them. It would be a renderer and VMM change as large as the app itself.

### A Vulkan path in QEMU

Venus with MoltenVK or KosmicKrisp would give the guest Vulkan and avoid deprecated OpenGL. Upstream QEMU still builds its Venus support only together with an OpenGL display. A [patch series to remove that requirement for macOS](https://patchew.org/QEMU/20260317174915.31829-1-lucaaamaral@gmail.com/) was posted in March 2026 and has not reached master as of 11.1.50. UTM's experience suggests the GNOME desktop would still composite through VirGL for now. Track this as the likely long-term renderer rather than the starting point.

### Commercial hypervisors

[Parallels Desktop 27](https://docs.parallels.com/landing/pdfm-ug/parallels-desktop-for-mac-27-users-guide/parallels-desktop-preferences-and-virtual-machine-settings/virtual-machine-settings/hardware-settings/graphics-settings) documents OpenGL 4.1 for Linux guests. [VMware Fusion](https://knowledge.broadcom.com/external/article/315602/compatibility-considerations-for-arm-gue.html) documents OpenGL 4.3 for ARM Linux guests with a recent kernel and Mesa; users report display problems with 3D enabled on ARM. We found no documentation of how either delivers trackpad scrolling to Linux guests, and we have not tested them. Both are closed, so we could not change their input path. A short hands-on comparison of their scrolling would give Milestone 0 a quality baseline.

### Native Linux

Asahi Linux runs on the M1 Pro without virtualization and uses the real trackpad and GPU. It requires rebooting out of macOS, and its supported distribution is Fedora rather than Ubuntu. It answers a different need from a VM beside macOS.

## Milestone 0: first results

On 1 November 2026 we booted a disposable Ubuntu 26.04.1 VM (GNOME Shell and Mutter 50.1 on Wayland, kernel 7.0) with the QEMU 11.1.1 runtime bundled in the installed Try Omarchy 1.2.0. It used the same virtio-gpu, tablet and `virtio-pinch-pci` devices. Inside the guest we applied Try Omarchy's touchpad settings: its libinput quirk, with tap-to-click, disable-while-typing and natural scrolling turned off. The setup and results are recorded in [the Milestone 0 notes](milestone-0-notes.md); the prototype's scripts were retired after Milestone 1. The user's overall verdict was that it "ran super well".

- **Rendering and refresh:** Mutter runs on KMS atomic with a GBM renderer over VirGL (Apple OpenGL 4.1 on Metal). The EDID's preferred mode carried the host's **119.998 Hz**, and Mutter selected it with no GRUB `video=` argument.
- **Scale:** at the initial small window the guest got the patch's 800×600 minimum. Mutter ignored the 2× density encoded in the EDID and chose scale 1.0. In full screen below the notch, the EDID carried 3024×1900 pixels and 35 × 22 cm. Mutter chose **3024×1900 at 120.001 Hz with scale 2.0** by itself, matching the Mac's 1512×950-point area. So the density encoding works for GNOME at real window sizes.
- **Trackpad:** scrolling, pinch zoom and swipe navigation all worked under GNOME. Scrolling did not feel identical to Try Omarchy. The user suspects a browser difference, since Omarchy uses Chromium and the test was mostly in Firefox. The two need comparing in the same browser before we tune speed on the host side.
- **Cursor:** guest cursor shapes reach the host through the cursor plane. Drawing the guest cursor at the guest-reported position next to the macOS arrow gave a double cursor that lagged and drifted, especially near the menu bar and notch. See [Cursor presentation](#cursor-presentation).
- **Notch:** in non-immersive full screen, the notch patch extends the guest into the strip beside the camera housing, which hid GNOME's clock. GNOME has no notch support, so the Ubuntu profile should keep full screen below the housing (`TRYOMARCHY_NOTCH=0`), or our app should reserve that strip itself. Non-immersive full screen also lets the macOS menu bar slide over the guest, which is a likely cause of the cursor problems near the top edge.
- **VirGL:** one guest GL context had a shader rejected because it requests `GL_ARB_draw_instanced`, which Apple's GLSL 4.10 compiler does not support. Its draws were dropped. The user noticed nothing missing, but this belongs on the renderer's compatibility list.

A second run used immersive full screen, kept the guest below the notch (`TRYOMARCHY_NOTCH=0`) and hid the macOS arrow (`show-cursor=off`). The user reported that the VM felt "much, much better" and that the cursor had no perceptible delay. In Chromium, scrolling still felt "too much force" compared with macOS. That fits the setup. Try Omarchy moves its synthetic contacts 0.12 mm per point of macOS scroll (less for slow scrolls) and leaves the speed to the guest. Omarchy then sets Hyprland's `touchpad.scroll_factor` to 0.4. GNOME 50 has no touchpad scroll-speed setting (`org.gnome.desktop.peripherals.touchpad.speed` affects only pointer motion), so on Ubuntu the same contacts scroll about 2.5 times as far. The correction has to come from the host: scale the contact distance, starting at 0.4, and make it a setting rather than a constant.

## Milestone 1: first build

On 2 November 2026 we built Milestone 1 in this repository ([README](../README.md)). The Mac app, the core library and the command-line tool are ours. GPT-6.1-Sol wrote the Ubuntu guest package against our host–guest contract.

- **App and tooling:** a SwiftUI app and `linuxvmctl` share one core library. It covers a VM library, creating a VM from an installer ISO, importing a raw or QCOW2 disk, CPU, memory and disk settings, swapping the installer disc while running, a shared folder, port forwards, display and scroll settings, start, clean shutdown, force stop, logs and a runtime capability check.
- **Supervision:** each VM runs under its own supervisor process, which owns QEMU and the clipboard, audio and time-zone bridges from Try Omarchy's `omarchy-vm-helper`. VMs keep running when the app quits.
- **Bundle:** the app bundles the patched runtime with our scroll-scale patch, the helper, edk2 firmware from the pinned QEMU source and the Guest Tools disc.
- **Guest tools:** the `linuxvm-guest` package carries:
  - a GNOME Shell extension and agent for the clipboard, since Mutter has no data-control protocol;
  - the Try Omarchy audio agent, adapted;
  - time-zone following;
  - the 9p shared-folder mount and home-folder link;
  - the touchpad quirk and GNOME touchpad defaults.

Verified on this Mac:

- **Fresh install:** a new VM booted the official Ubuntu 26.04.1 Desktop ARM64 ISO and installed onto a sparse 32 GB disk, unattended through autoinstall. It rebooted into the installed system. The installer disc was ejected while the VM ran, and the guest tools were installed from their disc. After the first login, the clipboard extension and agents were active and the time zone followed the Mac.
- **Imported VM:** our Milestone 0 Ubuntu was imported as an APFS clone.
  - Clipboard text crossed in both directions, including non-ASCII characters.
  - The Mac's audio devices appeared in PipeWire.
  - A shared Mac folder mounted with the right ownership, and files crossed both ways.
  - A marker file survived four clean shutdown and start cycles.
- **Tests:** 6 Swift tests and 23 guest package tests pass. The app's windows were checked from images it saves of its own windows.

Not yet verified:

- Clipboard images.
- Audio playback and recording by ear.
- Starting a VM by clicking in the app. That path uses the same library call as `linuxvmctl start`, which was tested.
- Display behaviour on an external monitor.

Known limits:

- Screenshots through QMP are black under VirGL.
- The Guest Tools disc has no Rock Ridge extensions, so its installer runs as `sh install.sh`.
- The clipboard D-Bus interface is open to any process in the user's session.

## Proposed architecture

### 1. A small native app that reuses Try Omarchy's helper

We assessed Try Omarchy v1.3.0's launcher on 2 November 2026. Its Swift package builds unchanged here (Swift 6.4, about 35 seconds). It splits into two products:

- **`omarchy-vm-helper`**, a command-line binary. It provides the Mac side of every integration as a subcommand: audio device routing, clipboard, timezone, battery, camera, authentication, guest status, QMP readiness, disk sparsifying and VM copying. Try Omarchy's launch script starts these bridges once QEMU is ready and restarts them if they exit. They talk to QEMU's virtio-serial sockets and do not depend on the Omarchy image or Hyprland.
- **The launcher app**, about 18,000 lines of Swift plus 11,000 lines of tests. It is built around one VM created from Omarchy's factory image. Storage holds exactly one VM, and the start menu, settings sheets and run session assume it. There is no VM library and no installer-ISO path. The factory download, Omarchy branding, guest-status reports from the `try-omarchy` package, and the bridged-networking daemon (which needs a privileged helper) are woven through the main controllers. Omarchy-specific references are concentrated in the factory download, run session, launcher and application controller.

We therefore no longer recommend forking the whole launcher. Instead:

- **Reuse `omarchy-vm-helper` unchanged** for the Mac side of the bridges, as Try Omarchy's own launch script does.
- **Copy the general-purpose pieces as needed**: the QMP connection, audio device listing, host sleep handling and storage capability checks.
- **Write a small new app** for what Try Omarchy does not have: a VM library, creation from an Ubuntu installer ISO, per-VM settings, and our display and scroll defaults.

Try Omarchy also offers a "VM kit" for embedding its run mode in other apps. It is tied to the Omarchy image download, so it does not fit an Ubuntu VM without the same changes.

The guest side of the bridges is the larger port. The `try-omarchy` package is an Arch package of small Python and shell agents, systemd units and udev rules. Each needs a different amount of work on Ubuntu:

- **Audio routing** (`pactl`) and **the shared folder** (a 9p mount) should run on Ubuntu almost unchanged.
- **Display sync** (`hyprctl`) is not needed, because Mutter already follows the EDID.
- **Clipboard** does not port. Its guest agent relies on `wl-paste --watch`, which needs the wlroots data-control protocol. We confirmed in the Ubuntu guest that Mutter 50 does not provide it; only primary selection is offered. A GNOME guest needs a different clipboard agent, most likely a small GNOME Shell extension that watches the selection and talks to the existing virtio-serial port.
- **Battery** uses a DKMS kernel module, and **Touch ID** works through 1Password. Both can wait.

For the first prototype, let QEMU's Cocoa frontend own the guest display window, as Try Omarchy does. QEMU then runs its own application in a separate process, so the guest window is not part of our app's window. Avoid immediately replacing its rendering surface with an embedded view: that would introduce another graphics integration project before we have validated the desired behavior. A unified display window can follow if the prototype justifies it.

### 2. A versioned runtime bundle

Bundle a known QEMU build, VirGL dependencies and compatible UEFI firmware. Record exact source revisions, patch order, checksums, deployment target and build options. Verify required capabilities rather than inferring them from a version string.

The first graphics path should be the one we are investigating: ARM64/HVF, virtio-gpu/VirGL and native Apple OpenGL. Venus is the likely later renderer. The app should explain a missing required capability instead of silently falling back to a materially different experience.

Runtime updates must preserve VM disks and firmware variables. Store the runtime identity and versioned machine type with each VM; do not automatically advance existing machines to a new virtual hardware definition. Saved-memory-state compatibility is a separate problem and should be deferred initially.

### 3. A VM controller and storage layer

Run one managed QEMU process per VM. Use a private local QMP connection for capability negotiation, state queries and lifecycle requests. QMP provides commands and asynchronous events; receiving a shutdown request acknowledgement is not the same as observing a completed guest shutdown. [QMP reference](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html)

Each VM should own its identity, disk, writable UEFI variables, machine definition and logs. Runtime assets remain separate. Choose a documented writable disk format after checking the desired cloning and future snapshot workflow; support for both raw and qcow2 need not be an initial requirement.

Disk locking must prevent concurrent writers. App closure should follow an explicit lifecycle policy, with graceful guest shutdown as the normal exit path. A timeout must not silently force termination. Import should initially create an independent VM copy after confirming that the source is shut down; we should never point the prototype at a live UTM disk.

Generate QEMU arguments from typed settings. Passing an argument array avoids shell interpretation, but QEMU's own option syntax still needs correct serialization, including filenames with commas. [Invocation reference](https://www.qemu.org/docs/master/system/invocation.html)

### 4. A portable input core with platform adapters

Keep three boundaries explicit:

- **AppKit adapter:** captures precise deltas on both axes, scroll direction, scroll phases, momentum phases, magnification and focus transitions.
- **Gesture logic:** owns fractional accumulation, speed, synthetic contact geometry and IDs for scroll and pinch, hand-over between the two, momentum ownership and cancellation. It should be testable without a running VM or app window. Try Omarchy already keeps this logic in a header its tests compile directly, which we can follow.
- **Transport adapter:** delivers touchpad contacts, and high-resolution wheel events for mice and fallbacks, to the guest.

There are two candidate transports. A virtio input device in QEMU, as Try Omarchy uses, needs no guest daemon but ties the feature to our patched runtime. A small guest daemon that creates a `uinput` wheel or touchpad device from events sent over a virtio-serial port or vsock would work with stock QEMU, UTM and Virtualization.framework, at the cost of a guest component and an extra hop whose timing must be measured. Prototype the first, and keep the second possible.

Pointer movement, cursor presentation and scrolling should remain distinct responsibilities. An ordinary mouse wheel must preserve its discrete behavior, and relative pointer capture should remain available for applications that need it.

This separation helps reuse, but it does not promise that the same source file will fit UTM unchanged. Event transport and device support are part of the feature.

### 5. Guest integration profiles

Define a small common protocol for guest capabilities and status, with distribution-specific packaging and desktop-specific adapters. Initial Ubuntu support should cover display synchronization, scroll-device configuration and diagnostics. Clipboard and folder sharing can follow once their behavior is specified.

Keep integration files package-owned and reversible. Let the guest continue to update its kernel and desktop normally. Version the protocol so an older host or guest can reject unsupported features clearly while retaining basic operation.

Ubuntu/GNOME, Fedora/GNOME and Omarchy/Hyprland may share a runtime but need different configuration and validation. “Boots an arbitrary ARM64 ISO” and “provides the polished experience” should be separate support claims.

## A practical implementation sequence

### Milestone 0 — Prove the runtime and Ubuntu compatibility

Before building any UI, build Try Omarchy's runtime and boot a disposable Ubuntu VM with a launch script derived from its own. Preserve our UTM VM as a reference and leave the separate Linux VM untouched. Do not add the GRUB `video=` argument to the new VM.

Milestone 0 should answer these questions on the actual Mac, with reproducible notes:

- Does GNOME's compositor render through VirGL, and is scaling crisp?
- Does the guest receive the host refresh rate and a usable scale through EDID, and does Mutter follow window resizes, fullscreen and display changes?
- Does Mutter use the virtio-gpu hardware cursor plane, and can the Cocoa frontend draw the guest's cursor image at the host pointer position?
- Does the synthetic-touchpad path feel as good under GNOME as it does in Try Omarchy v1.3.0, in GNOME's own apps, Firefox, Chromium and a terminal? Check direction under GNOME's natural-scrolling default, no accidental tap clicks, no suppression after typing, speed, and kinetic scrolling after a flick.
- Does pinch zoom work in Firefox, Chromium and GNOME's image and document viewers, and does a two-finger horizontal swipe navigate back and forward in the browsers?
- How do Parallels or VMware Fusion compare on the same workload, as a quality baseline?

If these foundations fail, a polished launcher will not resolve them.

### Milestone 1 — A usable native wrapper

Build in two steps.

1. **Daily-use integration in the prototype.** Start `omarchy-vm-helper`'s audio, clipboard and timezone bridges from our launch script, and add the shared folder. Port the guest agents to an Ubuntu package, with a GNOME Shell extension for the clipboard. This makes the current VM usable every day and tests the bridges on GNOME before any UI work.
2. **The app.** A minimal VM library, create-from-ISO flow, CPU/RAM controls, installation-media attachment, start, graceful shutdown, logs and runtime capability reporting, driving the same launch logic and helper. Users can install Ubuntu themselves. A prebuilt guest image is optional future work.

The milestone is complete when a fresh VM installs, survives repeated ordinary starts and shutdowns, and preserves user data. No UTM process, VM or preferences should be required or modified.

### Milestone 2 — Make the experience the product

Integrate the proven input, cursor and display paths into normal use. Verify short scrolls, diagonal movement, horizontal scrolling, flicks, swipe navigation, pinch, switching between scroll and pinch, cursor shapes and coordinate alignment. Cover focus changes, fullscreen transitions and movement between displays with different scale and refresh settings.

At this point, compare input and presentation behavior against the reference VM and macOS using repeatable workloads. Package the integration so a normal guest update does not erase it.

### Milestone 3 — Release and upstream work

Add reproducible runtime builds, signed/notarized app distribution, notices and source provenance, update compatibility checks and recovery documentation. Validate first on this M1 Pro, then additional Apple Silicon hardware before claiming broad support.

Once the input behavior is stable, prepare focused upstream proposals. Expand to another distribution only after the first profile is demonstrably reliable.

## How the trackpad work could reach UTM

The likely contribution is a series of coordinated changes, not a launcher plugin:

1. **Agree on behavior and scope.** Present the problem, input traces and reference behavior to UTM maintainers, with attribution to Try Omarchy. The reference behavior comes from the synthetic touchpad, which carries both scrolling and pinch. Precise, two-axis, high-resolution wheel scrolling is a smaller first step that would already remove UTM's notch-by-notch scrolling.
2. **Adapt host event capture.** UTM's input view must read `scrollingDeltaY` and `scrollingDeltaX` instead of `deltaY`, and preserve scroll phases, momentum, cancellation and focus changes.
3. **Establish the transport.** UTM sends input over SPICE through CocoaSpice, and SPICE's mouse messages cannot express horizontal or high-resolution scrolling. Extending SPICE would require protocol, server and client changes. Two other routes need no SPICE changes. UTM already holds a QMP connection, and QMP `input-send-event` can inject input events, though high-resolution wheel values need the new wheel axes from step 4; its latency as a continuous input stream must be measured. Alternatively, the guest-side `uinput` transport described above could run over a virtio-serial port.
4. **Add runtime/device support where needed.** The high-resolution wheel axes are new QEMU code that changes QEMU's public input API, which needs upstream review. The virtio touchpad device needed for finger scrolling and pinch is further new code. The `uinput` route avoids both but adds a guest package. Host-side smoothing alone cannot provide either contract.
5. **Package compatible guest configuration and tests.** Prove the behavior with UTM's runtime and supported guests, preserving existing mouse, capture and keyboard behavior.

Contribute changes at their actual layer: UTM for its UI, CocoaSpice for its client path, and QEMU for suitable virtual-device or backend changes. A useful first contribution may be smaller than the whole feature. Maintainer agreement and transport feasibility remain open; no contribution has been submitted.

## What “smooth” must mean in our validation

Use separate checks so a selected mode does not stand in for the whole experience:

- **Graphics:** an accelerated guest context uses VirGL; test representative rendering and check compositor/application paths where feasible.
- **Display:** record physical host capability, the refresh rate in the guest's EDID, guest-selected resolution/refresh and guest scale. Verify resize and fullscreen recovery.
- **Presentation:** measure frame intervals and stalls under a defined workload. Document the tool and what it actually observes.
- **Pointer:** check coordinate alignment, that the cursor shape follows the guest, hotspot transitions and response under load. Visible cursor motion and guest click response require separate evaluation.
- **Scrolling:** inspect Linux input events (`libinput debug-events`) for high-resolution wheel or finger-scroll semantics as appropriate. Verify direction, scroll end, horizontal and diagonal motion, very short movements, flicks and kinetic behavior, comparing the same page in macOS. Check that short scrolls never click, and that horizontal swipes navigate in browsers.
- **Pinch:** check `libinput debug-events` for pinch begin, update and end; verify continuous zoom at the pointer in supporting applications, short and repeated pinches, and that a pinch never clicks or moves the pointer.
- **Lifecycle:** lose focus mid-gesture, switch between scroll and pinch, pause/resume and reboot. No stuck contacts, clicks or duplicated momentum should remain.

Deterministic tests can exercise the exact gesture logic and virtual-device ABI. They cannot prove AppKit delivery, live libinput recognition or perceived smoothness. Those need real-Mac integration checks. Avoid claiming “ProMotion” unless we can describe precisely what was measured; a 120 Hz mode alone is insufficient.

## Boundaries and open decisions

The first product should focus on one tested desktop profile. Windows, Intel guests, nested virtualization, general USB passthrough, camera bridges, Touch ID authentication, three/four-finger and rotation gestures in the guest, and saved-memory-state migration can wait.

The highest-priority unknowns are:

- fine tuning of scroll feel on GNOME beyond the host-side scale (0.4 is good enough for now);
- cursor response under load, now that the guest-drawn cursor alone feels immediate in normal use;
- the remaining difference in scroll feel between GNOME and Omarchy, compared in the same browser. Scrolling, pinch and swipe already work;
- scale selection in Mutter at full-window sizes, and its behavior across window resizes and display changes;
- notch and menu-bar handling for GNOME in full screen;
- application behavior when the host stops supplying momentum.

These need experiments before we promise parity with Try Omarchy.

Apple OpenGL compatibility and the runtime patch set also require ongoing maintenance. Start from a reproducible baseline, track each carried patch and its upstream status, and avoid expanding the patch set without a concrete requirement. Re-evaluate the renderer when QEMU's Venus-without-OpenGL work lands, and re-evaluate Virtualization.framework when a custom virtio-gpu for it matures.

Try Omarchy's top-level [license](https://github.com/omacom/try-omarchy/blob/v1.2.0/LICENSE) is MIT. Its QEMU patch files can carry their own license identifiers, and [QEMU documents GPLv2 licensing with component-specific exceptions](https://www.qemu.org/docs/master/about/license.html). Reuse must preserve applicable notices and meet each distributed component's terms; the app's top-level license does not replace those terms. Review the final dependency bundle before distribution.

## Proposed first experiment

The first experiment was **our own isolated Ubuntu VM on Try Omarchy's Cocoa/VirGL runtime**, and it has run (see [Milestone 0: first results](#milestone-0-first-results)). Input, gestures and refresh carried over to GNOME. The notch and the macOS arrow were handled by launch settings, and the cursor then felt immediate. Scroll speed needs GNOME-specific engineering. That runtime has now been built from Try Omarchy v1.3.0's source with one added patch. The patch scales the contacts' travel from a file that is re-read at every scroll, so it can be tuned live. At 0.4, the user found scrolling "much closer" to macOS: not perfect, but good enough for now. Fine tuning is deferred. It may need more than one constant, such as a different gain curve for slow scrolls or changes to GNOME's kinetic glide. For build details see [the run notes](milestone-0-notes.md).

Implementation remains deferred. Project naming, visual design and broader distribution support can follow once the core behavior is proven.
