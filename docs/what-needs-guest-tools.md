# What needs the guest tools

Linux runs in the app without any of our software inside it. Most of the experience comes from the VM's virtual hardware, which Linux's own drivers handle. The guest tools are the `linuxvm-guest` package on the Guest Tools disc. They add the integrations that need a program inside Linux, and they are made for Ubuntu 26.04 Desktop with GNOME Shell 50.

Checked on 3 November 2026 in a fresh Ubuntu 26.04.1 VM, first with guest tools 0.2.1 and then after removing them. The scrolls in that test were replayed on the virtual touchpad, not made on a real trackpad. The display results, and gestures on a real trackpad, come from Milestone 0 ([notes](milestone-0-notes.md)). That run had no guest tools, but it already used the [touchpad defaults](#touchpad-defaults) below.

## Works without the guest tools

- **Graphics and display.** Graphics are accelerated through VirGL. Linux gets the Mac display's refresh rate. In full screen, GNOME picks a matching resolution and scale by itself: 3024 × 1900 at 120 Hz and 200 % on a 14-inch MacBook Pro. Resizing the window outside full screen hasn't been tested yet.
- **Pointer.** Linux's own cursor shapes appear, such as the text cursor and resize arrows, with no second Mac arrow.
- **Trackpad gestures.** Two-finger scrolling, pinch to zoom, and two-finger swipes back and forward in browsers all work. The app's scroll speed setting works too, because the Mac applies it. Some Linux touchpad settings start differently; see [Touchpad defaults](#touchpad-defaults).
- **Mouse and keyboard.** Typing, clicks and mouse-wheel scrolling all work.
- **Sound.** Linux plays sound on the Mac's current output device and records from the Mac's current microphone. macOS asks once for permission to use the microphone.
- **Network.** Linux reaches the internet through the Mac, and the app's port forwards work.
- **Power.** The app's Shut Down asks Linux to shut down, like pressing a power button. Restart and Shut Down inside Linux work too.
- **Pause while the Mac sleeps.** The Mac pauses the VM before it sleeps and resumes it after. Without the guest tools, Linux's clock falls behind; see [the table below](#needs-the-guest-tools).
- **Clock at startup.** Linux reads the time from the VM's hardware clock, which follows the Mac.
- **Discs.** You can insert and eject the installer disc. The Guest Tools disc is always attached, as the `LINUXVM-TOOLS` drive.
- **The VM's other settings in the app.** Processors, memory, disk size, display options and port forwards all apply.

## Needs the guest tools

| Feature | With the guest tools | Without them |
| --- | --- | --- |
| Shared clipboard | Text and PNG images copy both ways, up to 16 MiB each. Needs GNOME Shell 50. | No shared clipboard. |
| Mac sound devices | Each Mac speaker and microphone appears in Linux's Sound settings. Choosing one there plays or records through that Mac device. | Linux has one output and one input, the virtual sound card. They use the Mac's current devices. |
| Time zone | Linux uses the Mac's time zone from startup and follows when it changes. It stops following once you set a zone in Linux. | Linux keeps the zone chosen when it was installed. |
| Clock after Mac sleep | Linux sets its clock forward within a few seconds of the Mac waking. | Linux's clock stays behind by however long the Mac slept. In a test with 2 minutes of sleep, Ubuntu's time service started correcting it after about 6 minutes. It corrects gradually, by about 5 seconds per minute, so an hour of sleep would take about 12 hours to correct. Restarting Linux, or running `sudo chronyc makestep`, corrects it at once. |
| Shared folder | Mounted at `/mnt/mac`, with a link in your home folder named after the Mac folder. | Not mounted. You can mount it by hand: `sudo mkdir -p /mnt/mac && sudo mount -t 9p -o trans=virtio,version=9p2000.L mac /mnt/mac`. |
| Touchpad defaults | Set for the virtual touchpad; see [Touchpad defaults](#touchpad-defaults). | Ubuntu's defaults. |
| Guest Tools section in the app | The VM's page shows the installed version, the Linux and GNOME versions, and whether the clipboard is running. It says when the disc has a newer version. `linuxvmctl status` also shows the version. | Shows "Not reported". |

The clipboard, the Mac sound devices, the home-folder link and the report to the app start when someone logs in to the desktop. The time zone, the clock and the `/mnt/mac` mount work from startup.

On a GNOME version the guest tools don't support yet, the clipboard is off and the app says so. Everything else in the table still works.

## Touchpad defaults

The Mac turns each trackpad scroll into two fingers on a virtual touchpad. The guest tools set Linux up for that touchpad. Settings you change yourself in Linux take precedence.

| Setting | Guest tools | Ubuntu's default | Why |
| --- | --- | --- | --- |
| Tap to click | Off | On | A precaution: the touch contacts the Mac creates for scrolling must never count as taps. Ubuntu's default hasn't been tried with a real trackpad. |
| Disable while typing | Off | On | A precaution. In the test it had no effect: Linux doesn't pair the VM's keyboards with the virtual touchpad, so scrolling right after typing still worked. |
| Natural scrolling | On | On | Matches the Mac's default. |
| Jump detection | Off | On | libinput discards a touch that moves more than 20 mm in 12 ms, or speeds up by more than 7 mm in one frame, as a hardware glitch. Try Omarchy found that fast swipes cross these limits and then don't scroll; this hasn't been measured at this app's scroll speed. This setting is a libinput quirk for the virtual touchpad only, and Linux's Settings app doesn't show it. |

## Installing them

1. In Ubuntu, open the `LINUXVM-TOOLS` disc in Files.
2. Open a terminal in that folder and run `sh install.sh`. It asks for your password and may download a few Ubuntu packages.
3. Log out and back in.

To update, do the same with the disc from a newer app. To remove them, run `sudo apt purge linuxvm-guest`.

## Other distributions

The guest tools are an Ubuntu package. The virtual hardware is standard virtio, so the features in [Works without the guest tools](#works-without-the-guest-tools) should work on other ARM64 distributions too. Only Ubuntu 26.04 with GNOME 50 has been tested, though. On any Linux whose kernel has 9p over virtio, you can mount the shared folder by hand.
