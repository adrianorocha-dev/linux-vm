# Ubuntu VM configuration — final handoff

Configured on 2026-10-29 using UTM 5.0.8 (128), on an Apple M1 Pro (ARM64, 16 GiB RAM), macOS 27.2 (26B123).

## Result

The VM named **Ubuntu** now uses the off-the-shelf UTM QEMU/VirGL graphics recipe:

- QEMU backend, ARM64 (`aarch64`), QEMU 10.0 ARM `virt` machine.
- Hardware virtualization / Use Hypervisor enabled; UEFI enabled.
- `virtio-gpu-gl-pci` accelerated display device.
- **Apple Core OpenGL** host renderer.
- FPS Limit remains **0 / None** (the pre-existing default; no artificial 60 fps cap).
- Auto Resolution enabled.
- Retina Mode enabled; Ubuntu uses 3024 × 1898 with 200% scaling, visually confirmed sharp by the user. Rendering cost has not been benchmarked.
- A successful one-boot custom mode selected 120.00 Hz at this resolution; the exact kernel argument has now been saved persistently and the generated GRUB configuration validated. A fresh boot after saving remains untested.
- Linear upscaling/downscaling.
- CPU remains Default (CPUCount=0); RAM remains 6144 MiB.
- Balloon and RNG enabled; TSO disabled; no custom QEMU arguments.
- Shared networking; Ubuntu’s original MAC `(MAC address)` retained.

Current bundle: `~/Library/Containers/com.utmapp.UTM/Data/Documents/Ubuntu.utm`
Current VM UUID: `F62CAEEA-6AC5-4D33-B56E-102FD42E8FF2`
Installed root disk: `98694ECF-2653-4EEE-ABBC-9E9BC7FABB22.qcow2` (64 GiB sparse capacity).

## Original and backup

Ubuntu originally used Apple Virtualization and was Stopped. Its original configuration was copied using Finder before any edit, parsed successfully, and hashed:

`config.plist` SHA-256: `ea00ed4e88b5a6b85d27ef31b2ebb4e7293344712d4061f815abcb120791167f`

See `manifest.json` beside the original configuration backup. This is a configuration backup, not a full disk-image backup.

After the user explicitly authorized recreation, the original VM and all its existing data were retained and renamed **Ubuntu (Apple backup)** through UTM. Its bundle is:

`~/Library/Containers/com.utmapp.UTM/Data/Documents/Ubuntu (Apple backup).utm`

Keep that retained VM stopped while the new Ubuntu is running, since they retain the same MAC address. No disk from the separate Linux VM was used.

## Linux and preference scope

No start, resume, stop, suspend, configuration update, saved-state discard, or disk modification was performed on **Linux**. UTM initially displayed its state as **Suspended**, despite the expectation in the request that it was running. Its state was preserved. The supported scripting inventory later described it as stopped; no lifecycle command targeted it.

A read-only copy of Linux’s configuration confirmed `Backend=Apple`. The installed UTM preferences explicitly say Renderer Backend applies only to QEMU VMs with GPU acceleration. Therefore changing the renderer from Default to Apple Core OpenGL did not change Linux’s Apple Virtualization graphics path. Other global display/input preferences were left unchanged. No UTM update, quit, or restart was performed.

## Validation performed

- Original configuration backup parsed successfully.
- The new saved configuration was copied through Finder and validated for QEMU, matching ARM64 architecture, Hypervisor, UEFI, virtio-gpu-gl-pci, Auto Resolution, CPU/RAM, MAC, and absence of custom QEMU arguments. This snapshot is in `qemu-created/config.plist`.
- The accelerated configuration booted the existing ARM64 Ubuntu ISO to a graphical live desktop.
- A fresh OS installation completed and powered off before the user clarified that OS installation was unnecessary. The installation used the existing `ubuntu-26.04.1-desktop-arm64.iso` and included spice-vdagent, qemu-guest-agent and mesa-utils. An adriano account was created with the password supplied through the private secret-entry mechanism; plaintext was not logged.
- Installer and seed drives were detached through UTM’s supported configuration API while stopped. The existing installed root disk was explicitly checked by identifier and retained. The same saved-configuration readback confirmed Retina=true and all target settings above.
- The installed system reached the graphical login screen. Secure sign-in was submitted. The QEMU guest agent responded to a read-only `id` check as root. During the later Retina follow-up, the user signed in directly and the graphical desktop was visually confirmed.
- Host display inventory reported built-in 3024×1964 pixels, logical 1512×982 at 120 Hz, and external 2560×1440 at 144 Hz. These are host display modes; UTM presentation cadence was not measured.

## Unverified / deferred

The later refresh-rate follow-up confirmed an accelerated guest GLX context using VirGL, as recorded below. GNOME/Mutter's own rendering context, sustained frame rate and adaptive ProMotion remain unverified. Native UI access initially failed with `cgWindowNotFound`, but recovered for the later follow-ups. The user's native-UI-only preference remains in effect.

Retina can increase the guest pixel workload approximately fourfold when both dimensions double at 2× scale. If responsiveness or text sizing is poor, turn Retina Mode off in Ubuntu’s Display settings, or use suitable guest scaling. This is a cost explanation, not a measured performance result.

The installed agent packages still need runtime verification in the active graphical session. The local `verify-ubuntu-graphics.sh` is an optional diagnostic script for later use; it was not run in the graphical session.

## Retina clarity follow-up — 2026-10-29

- Native UTM controls confirmed Retina Mode and Auto Resolution were already enabled on Ubuntu, with `virtio-gpu-gl-pci` and Linear scaling filters. No host VM configuration or global preferences were changed during this follow-up.
- Ubuntu was stopped when inspected and was started through its own native Run control. Linux and the retained Apple backup were not operated.
- The user signed in directly. Ubuntu Displays reported **3024 × 1898**, **75.00 Hz**, and **100%** scale in the Retina window.
- Changed Ubuntu's display scale to **200%** through its graphical Displays settings, preserving the high pixel resolution and refresh mode. The final screen showed 200% selected, no pending Apply bar or confirmation dialog, and legible high-resolution text. Built-in Scaling for Legacy Apps was already enabled after the scale change and was left as shown.
- This verifies the selected guest refresh mode and guest HiDPI setting; it does not measure sustained frame rate or establish the active Mesa renderer. No restart or guest package installation was needed.

## 120 Hz investigation — 2026-10-29

- Native UTM Settings reconfirmed Apple Core OpenGL and FPS Limit **0/None**. No global preference was changed.
- Ubuntu's native Displays panel exposed only **75.00 Hz** at **3024 × 1898**. Returning from a temporary windowed view restored this fullscreen resolution and the saved **200%** scale. Automatic resolution changes between windowed and fullscreen were observed.
- In a user-signed-in terminal, `glxinfo -B` reported **Accelerated: yes**, **OpenGL renderer: virgl (Apple M1 Pro)**, **OpenGL 4.1**, and **Mesa 26.0.8-1ubuntu0.3**. This verifies that diagnostic's GLX context rather than every application's or Mutter's context. `echo $XDG_SESSION_TYPE` reported **wayland**, and `/sys/class/drm` listed **card0-Virtual-1** and **renderD128**.
- Try Omarchy v0.5.1 source was inspected. Its patched Cocoa frontend supplies the host refresh rate and backing-pixel dimensions through virtual display information/EDID. Its guest display-sync helper applies fresh modelines and scaling through Hyprland. This differs from UTM's CocoaSpice/Metal presentation path and Ubuntu's GNOME session.
- UTM 5.0.8 source sets its host view's preferred FPS to the host screen maximum when FPS Limit is unset. This is a rendering target, not a measured presentation rate or a guest-mode override. The QEMU EDID code's 75 Hz fallback is consistent with the guest's observed mode; it is not evidence of a universal 75 Hz limit in UTM.
- A one-boot Linux custom-mode trial was investigated. `systemctl reboot --boot-loader-menu 30` was submitted through native guest keyboard controls and rejected with **Boot loader does not support boot into boot loader menu**. No reboot occurred. Further native typing again dropped/repeated keys, so no GRUB edit was attempted and the incomplete input was canceled. The diagnostic terminal was closed normally.
- At the end of the initial investigation, no persistent guest configuration change, UTM configuration change, QEMU argument, firmware change, upgrade, force-stop or action on Linux had been performed. The initial automated investigation left Ubuntu at 75 Hz; the later successful test is recorded below.
- The original manual trial is documented in `ubuntu-120hz-one-boot-test.md`; it requests a temporary kernel mode and does not require rebuilding QEMU. The later successful result and persistent edit are recorded below. Sustained 120 fps/adaptive ProMotion still require separate verification.

## Successful 120 Hz trial and persistence follow-up — 2026-10-29

- The user manually appended `video=Virtual-1:3024x1898MR@120e` to Ubuntu's normal kernel line in GRUB for one boot. Their screenshot showed **3024 × 1898, 120.00 Hz, 200% scaling**, and they reported the result worked.
- Native guest-terminal inspection independently confirmed `/proc/cmdline` contains the exact argument, on kernel `7.0.0-42-generic`.
- Before editing, `/etc/default/grub` had `GRUB_CMDLINE_LINUX_DEFAULT="quiet splash console=tty0"` and an empty `GRUB_CMDLINE_LINUX`. Its installed header documents both this file and `/etc/default/grub.d/*.cfg` as supported inputs followed by `update-grub`.
- Created **`/etc/default/grub.before-120hz` inside Ubuntu**, preserving metadata and avoiding replacement of an existing backup. `diff -s` explicitly confirmed the backup and original were identical before editing. The user authenticated sudo directly in the guest window; no password was sent in chat or read by the agent.
- Using the native terminal and nano, saved exactly one change: `GRUB_CMDLINE_LINUX_DEFAULT="quiet splash console=tty0 video=Virtual-1:3024x1898MR@120e"`. A full `diff -u` against the backup confirmed that single-line change and no other file-content changes. Input corruption was corrected and visually reviewed before saving.
- Ran **`sudo update-grub`** successfully. It sourced the existing kdump-tools drop-in and found kernels `7.0.0-42-generic` and `7.0.0-30-generic`. Its ordinary os-prober-disabled warning did not prevent completion.
- Read back `/boot/grub/grub.cfg`: lines 168, 182 and 209 contain the exact argument in the normal boot entries, preserving root UUID, original arguments and crashkernel settings. `sudo grub-script-check /boot/grub/grub.cfg && echo OK` printed **OK**.
- The setting is persistent on disk. The current successful 120 Hz session was left running; a fresh normal boot after the persistent edit has **not** been tested. No UTM configuration/global preference, Linux lifecycle/configuration, disk or firmware change was needed in this follow-up. No UTM restart or upgrade occurred.
- The guest's selected 120 Hz mode and the user's perceived improvement do not establish sustained 120 fps or adaptive ProMotion.

### Rollback inside Ubuntu

Restore the saved defaults and regenerate the boot menu, then restart Ubuntu normally when ready:

```sh
sudo cp -a /etc/default/grub.before-120hz /etc/default/grub
sudo update-grub
```

For a temporary fallback at boot, use GRUB's edit action on the normal Ubuntu entry and remove only `video=Virtual-1:3024x1898MR@120e` for that boot, preserving all other kernel arguments. Recovery options were not given the new argument because it was added only to `GRUB_CMDLINE_LINUX_DEFAULT`.

This is a fixed custom mode for **3024 × 1898**. Auto Resolution remains enabled; other window sizes or displays may select a different resolution/refresh rate. No adaptive refresh integration was added.

## Mouse and trackpad investigation — 2026-10-30

- Inspected UTM's native Input preferences without changing them. Automatic capture on fullscreen and window focus, Invert scrolling, and Handle input on initial click were all off. Ubuntu's running console showed Capture Input off, so the desktop was already using the uncaptured absolute-pointer path. Linux was not selected or operated.
- UTM 5.0.8's `VMMetalView.scrollWheel` forwards vertical `event.deltaY`; the controller sends it through CocoaSpice's smooth-scroll API. That label does not establish a precision-touchpad event stream in Linux. This host view exposes no horizontal scroll forwarding in that method and no configurable precision/momentum control in the inspected UI. No new mouse-speed, acceleration, scroll, global preference, guest package, or VM setting was applied during this investigation.
- Checked the current Try Omarchy release, **v1.2.0**, rather than relying only on the older v0.5.1 research. Its architecture and trackpad documentation describe a patched Cocoa input path and dedicated virtual touchpad: precise scrolls become two moving contacts, gesture end releases them, and host momentum is suppressed for that path so guest applications can provide kinetic scrolling. The high-resolution wheel path is retained as a fallback. These are runtime/device and guest-integration changes, beyond a UTM configuration script.
- Public source copies used for this comparison are under `refresh-research/try-omarchy-v1.2.0/`. No custom runtime was built or installed. Cursor latency, live Linux input events and finger/momentum behavior have not been measured; further guest tuning remains separate from the architectural limitation.

References: [UTM 5.0.8 input view](https://github.com/utmapp/UTM/blob/v5.0.8/Platform/macOS/Display/VMMetalView.swift), [UTM macOS preferences](https://docs.getutm.app/preferences/macos/), [Try Omarchy v1.2.0 architecture](https://github.com/omacom/try-omarchy/blob/v1.2.0/docs/architecture.md), [trackpad scrolling](https://github.com/omacom/try-omarchy/blob/v1.2.0/docs/trackpad-scrolling.md).

## Official references checked against the installed controls

- [Linux guest support](https://docs.getutm.app/guest-support/linux/): accelerated virtio display, Mesa VirGL, Apple Core OpenGL, Linux desktop Vulkan limitation, and spice-vdagent support.
- [QEMU Display settings](https://docs.getutm.app/settings-qemu/devices/display/): per-VM accelerated display, Auto Resolution and Retina; renderer/driver preferences are global; Retina has a higher processing cost.
- [macOS preferences](https://docs.getutm.app/preferences/macos/): Apple Core OpenGL uses native host OpenGL; default FPS follows the display; this renderer does not support Vulkan/DirectX.
- [QEMU settings](https://docs.getutm.app/settings-qemu/qemu/): matching architecture and Use Hypervisor.
- [Apple Display settings](https://docs.getutm.app/settings-apple/devices/display/): Apple-backend dynamic resolution requires supported macOS guests.
- [UTM 5.0 notes](https://docs.getutm.app/updates/v5.0/): Apple Core OpenGL is available in this release family.
- [Supported UTM scripting](https://docs.getutm.app/scripting/cheat-sheet/): configuration and lifecycle controls used, without direct live-plist editing.
- [Ubuntu update-grub manual](https://manpages.ubuntu.com/manpages/resolute/man8/update-grub.8.html): supported regeneration of `/boot/grub/grub.cfg` using `grub-mkconfig`.
- [Linux kernel video-mode syntax](https://docs.kernel.org/fb/modedb.html): connector-specific custom video mode argument used in the successful trial and persistent setting.
