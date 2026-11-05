# What needs the guest tools

Linux runs in the app without any of our software inside it. Most of the experience comes from the VM's virtual hardware, which Linux's own drivers handle. The guest tools are the `linuxvm-guest` package on the Guest Tools disc. They add the integrations that need a program inside Linux.

They support these four combinations:

| | GNOME | KDE Plasma |
| --- | --- | --- |
| Ubuntu 26.04 | GNOME 50 | Kubuntu's desktop (`kubuntu-desktop`), Plasma 6.6 |
| Fedora | Fedora 44 Workstation, GNOME 50 | Fedora 45 KDE Plasma Desktop, Plasma 6.8 |

Kubuntu publishes no ARM64 installer, so on a Mac its desktop comes from installing `kubuntu-desktop` on Ubuntu 26.04. Fedora 45 Workstation, with GNOME 51, hasn't been tested yet. The shared clipboard stays off there, because our GNOME Shell extension declares only GNOME 50.

How this was checked:
- **Ubuntu 26.04.1 with GNOME:** checked on 3 November 2026 in a fresh VM, first with guest tools 0.2.1 and then after removing them. The scrolls in that test were replayed on the virtual touchpad, not made on a real trackpad.
- **Fedora and KDE Plasma:** checked on 4 and 5 November 2026 in fresh VMs of each, with guest tools 0.3.0. Those checks ran with nobody at the Mac. On 5 November the same VMs were also tried at the Mac: the real trackpad, the display in full screen, the clock after the Mac slept, and the disc in Dolphin all worked. The exact scale and refresh rate Plasma chose weren't recorded.
- **Display and real-trackpad gestures:** these come from Milestone 0 ([notes](milestone-0-notes.md)), on Ubuntu with GNOME. That run had no guest tools, but it already used the [touchpad defaults](#touchpad-defaults) below.

## Works without the guest tools

- **Graphics and display.** Graphics are accelerated through VirGL. Linux gets the Mac display's refresh rate. In full screen, GNOME picks a matching resolution and scale by itself: 3024 × 1900 at 120 Hz and 200 % on a 14-inch MacBook Pro. In a window, Fedora 44's GNOME picked 2240 × 1260 at 120 Hz and a 167 % scale. Plasma's choices in full screen looked right at the Mac; their values weren't recorded. Resizing the window outside full screen hasn't been tested yet.
- **Pointer.** Linux's own cursor shapes appear, such as the text cursor and resize arrows, with no second Mac arrow.
- **Trackpad gestures.** Two-finger scrolling, pinch to zoom, and two-finger swipes back and forward in browsers all work. The app's scroll speed setting works too, because the Mac applies it. Some Linux touchpad settings start differently; see [Touchpad defaults](#touchpad-defaults).
- **Mouse and keyboard.** Typing, clicks and mouse-wheel scrolling all work.
- **Sound.** Linux plays sound on the Mac's current output device and records from the Mac's current microphone. macOS asks once for permission to use the microphone.
- **Network.** Linux reaches the internet through the Mac, and the app's port forwards work.
- **Power.**
  - **GNOME:** the app's Shut Down asks Linux to shut down, like pressing a power button.
  - **KDE Plasma:** the same button opens a logout prompt that waits for a click, so Shut Down doesn't finish. Shut down from inside Linux, or use Force Stop. The guest tools fix this.
  - **Inside Linux:** Restart and Shut Down work on both.
- **Pause while the Mac sleeps.** The Mac pauses the VM before it sleeps and resumes it after. Without the guest tools, Linux's clock falls behind; see [the table below](#needs-the-guest-tools).
- **Clock at startup.** Linux reads the time from the VM's hardware clock, which follows the Mac.
- **Discs.** You can insert and eject the installer disc. The Guest Tools disc is always attached, as the `LINUXVM-TOOLS` drive. GNOME opens it by itself. In KDE Plasma it appears in Dolphin, which opens it when you click it.
- **The VM's other settings in the app.** Processors, memory, disk size, display options and port forwards all apply.

## Needs the guest tools

| Feature | With the guest tools | Without them |
| --- | --- | --- |
| Shared clipboard | Text and PNG images copy both ways, up to 16 MiB each. On GNOME it needs GNOME 50 and goes through our GNOME Shell extension. On KDE Plasma it uses Plasma's own clipboard protocol. | No shared clipboard. |
| Mac sound devices | Each Mac speaker and microphone appears in Linux's sound settings. Choosing one there plays or records through that Mac device. | Linux has one output and one input, the virtual sound card. They use the Mac's current devices. |
| Time zone | Linux uses the Mac's time zone from startup and follows when it changes. It stops following once you set a zone in Linux. | Linux keeps the zone chosen when it was installed. |
| Clock after Mac sleep | Linux sets its clock forward within a few seconds of the Mac waking. | Linux's clock stays behind by however long the Mac slept. In a test with 2 minutes of sleep, Ubuntu's time service started correcting it after about 6 minutes. It corrects gradually, by about 5 seconds per minute, so an hour of sleep would take about 12 hours to correct. Restarting Linux, or running `sudo chronyc makestep`, corrects it at once. Fedora uses the same time service. |
| Shared folder | Mounted at `/mnt/mac`, with a link in your home folder named after the Mac folder. It works with Fedora's SELinux enforcing. | Not mounted. You can mount it by hand: `sudo mkdir -p /mnt/mac && sudo mount -t 9p -o trans=virtio,version=9p2000.L mac /mnt/mac`. |
| Touchpad defaults | Set for the virtual touchpad; see [Touchpad defaults](#touchpad-defaults). | The desktop's own defaults. |
| Power button in KDE Plasma | Shuts Linux down, so the app's Shut Down works. | Opens a logout prompt that waits for a click. |
| Guest Tools section in the app | The VM's page shows the installed version, the Linux version, the desktop and its version, and whether the clipboard works. It says when the disc has a newer version. `linuxvmctl status` shows the same. | Shows "Not reported". |

The clipboard, the Mac sound devices, the home-folder link and the report to the app start when someone logs in to the desktop. The time zone, the clock and the `/mnt/mac` mount work from startup.

On a GNOME version the guest tools don't support yet, the clipboard is off and the app says so. Everything else in the table still works.

## Touchpad defaults

The Mac turns each trackpad scroll into two fingers on a virtual touchpad. The guest tools set Linux up for that touchpad. Settings you change yourself in Linux take precedence. On GNOME they're a GSettings override; on KDE Plasma they're system defaults in `/etc/xdg/kcminputrc`, for the virtual touchpad only.

| Setting | Guest tools | GNOME's default (Ubuntu and Fedora) | KDE Plasma's default | Why |
| --- | --- | --- | --- | --- |
| Tap to click | Off | On | On | A precaution: the touch contacts the Mac creates for scrolling must never count as taps. The desktops' default hasn't been tried with a real trackpad. |
| Disable while typing | Off | On | On | A precaution. In the Ubuntu test it had no effect: Linux doesn't pair the VM's keyboards with the virtual touchpad, so scrolling right after typing still worked. |
| Natural scrolling | On | On | Off | Matches the Mac's default. |
| Jump detection | Off | On | On | libinput discards a touch that moves more than 20 mm in 12 ms, or speeds up by more than 7 mm in one frame, as a hardware glitch. Try Omarchy found that fast swipes cross these limits and then don't scroll; this hasn't been measured at this app's scroll speed. This setting is a libinput quirk for the virtual touchpad only, and Linux's settings apps don't show it. |

## Installing them

1. Open the `LINUXVM-TOOLS` disc in Linux's file manager: Files on GNOME, or Dolphin on KDE Plasma, where you click the disc to open it.
2. Open a terminal in that folder and run `sh install.sh`. It installs with apt on Ubuntu, or dnf on Fedora. It asks for your password and may download a few packages.
3. Log out and back in.

To update, do the same with the disc from a newer app. To remove them, run `sudo apt purge linuxvm-guest` on Ubuntu, or `sudo dnf remove linuxvm-guest` on Fedora. Removing them leaves no files behind.

## Other distributions

The guest tools are an Ubuntu package and a Fedora package. The virtual hardware is standard virtio, so the features in [Works without the guest tools](#works-without-the-guest-tools) should work on other ARM64 distributions too. Only the four combinations above have been tested, though. On any Linux whose kernel has 9p over virtio, you can mount the shared folder by hand.
