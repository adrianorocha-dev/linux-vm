# Tests for later

Checks left open when Milestone 2 closed on 3 November 2026. None of them blocks daily use. Pick them up when there is time. Each entry links to where it came from.

## With someone at the Mac

- **Side-by-side comparison.** Compare scrolling, pinch, swipe and the cursor with Try Omarchy and macOS on the same pages, and write down the differences. Include short scrolls, diagonal and horizontal motion, flicks, kinetic glide, and the cursor under load. ([Milestone 2](milestone-2-plan.md#2-trackpad))
- **Scroll direction on a real trackpad.** The fix of 2 November was verified only with replayed contacts. Check that GNOME's Natural setting is right both ways. ([Milestone 2](milestone-2-plan.md#reported-at-the-mac-2-november-2026))
- **Display changes.** Resize the window outside full screen, enter and leave full screen, and move to an external display with a different scale and refresh rate. ([Milestone 2](milestone-2-plan.md#3-cursor-and-display))
- **Focus loss mid-gesture.** Switch apps while scrolling or pinching, then check that no contact stays down and nothing clicks. ([Milestone 2](milestone-2-plan.md#2-trackpad))
- **Starting a VM by clicking in the app.** ([Milestone 1](milestone-2-plan.md#6-carried-over-from-milestone-1))
- **Clipboard images.** Copy a PNG both ways. Text has been checked. ([Milestone 1](milestone-2-plan.md#6-carried-over-from-milestone-1))
- **Sound by ear.** Play sound and record from the microphone. ([Milestone 1](milestone-2-plan.md#6-carried-over-from-milestone-1))
- **Removable storage for real.** Unplug a drive holding a VM or its shared folder, and read Finder's message when an eject is refused. These were tested only with disk images. ([Milestone 2](milestone-2-plan.md#second-wave-2-november-2026))
- **Touchpad without the guest tools.** With Ubuntu's default tap to click on, check whether a short scroll ever counts as a click. Without the jump-detection quirk, check whether fast swipes still scroll. ([What needs the guest tools](what-needs-guest-tools.md#touchpad-defaults))

## Without anyone at the Mac

- **Frame pacing in full screen and on a second display.** Measure with the VM window in front and the display on, because other conditions always pace badly. ([Milestone 2](milestone-2-plan.md#idle-pacing-investigation-2-november-2026))

## Small fixes noticed

- **Leftover file when the guest tools are removed.** `apt purge linuxvm-guest` leaves `/usr/lib/linuxvm/__pycache__/`, which Python creates at run time. The package's removal script should delete it. This needs a new package version. ([What needs the guest tools](what-needs-guest-tools.md#installing-them))
