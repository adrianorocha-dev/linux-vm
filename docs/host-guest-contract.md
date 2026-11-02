# Host–guest contract

The Mac app (`macos/`) and the Ubuntu guest tools (`guest/`) meet only at the interfaces below.

## Virtual devices

- `virtio-serial-pci` with these `virtserialport` names.
  - Three ports are QEMU UNIX sockets served by an `omarchy-vm-helper` bridge from Try Omarchy v1.3.0. The wire protocol on each is exactly the one that bridge speaks; see `NativeClipboardBridge.swift`, `NativeAudioBridge.swift` and `NativeTimeZoneBridge.swift` in `.deps/try-omarchy/macos/Sources/OmarchyVMHelper/`.
    - `dev.linuxvm.clipboard`: helper `--bridge-native-clipboard`.
    - `dev.linuxvm.audio`: helper `--bridge-native-audio` (QEMU runs with `OMARCHY_SDL_AUDIO_CONTROL_DIRECTORY`).
    - `dev.linuxvm.timezone`: helper `--bridge-native-timezone`. Besides zone names it carries `{"type":"wake"}` after the Mac wakes (see [Mac sleep](#mac-sleep-and-the-guest-clock)).
  - `dev.linuxvm.status` is served by our supervisor (`linuxvmctl run`), not by the helper. See [Guest status](#guest-status). Added in app and guest tools 0.2.0.
- The shared Mac folder, when enabled: `virtio-9p-pci` with mount tag `mac`, exported with `security_model=none,multidevs=remap,guest_owner_uid=1000,guest_owner_gid=1000`. Files appear owned by uid/gid 1000, the first Ubuntu user.
- The virtual touchpad `QEMU Virtio Pinch Touchpad` (`virtio-pinch-pci`). The Mac has already applied the scroll scale. Its finger-scroll contacts follow the fingers, without the Mac's natural scrolling, so the guest's own touchpad setting picks the direction. Guest tools 0.2.1 default natural scrolling on. Earlier app builds sent the Mac's direction, and guest tools 0.2.0 and earlier turned natural scrolling off to match; with a current app, such a VM scrolls the traditional way until its guest tools are updated or the setting is changed.
- The PL031 real-time clock of QEMU's `virt` machine. It follows the Mac's UTC clock, including while the VM is paused. Linux usually reaches it through the UEFI firmware as `rtc-efi`.

## Host settings

The Mac passes one systemd credential, `linuxvm.host`, through SMBIOS type 11 (`io.systemd.credential.binary:linuxvm.host=<base64>`). It holds `key=value` lines:

- `timezone=<IANA zone>`: the Mac's zone at launch.
- `shared_folder_name=<name>`: present only when a folder is shared. URL-safe base64 of the Mac folder's last path component, without padding.

The guest treats every value as untrusted. The credential's presence also tells the guest tools that they run under this app.

## Mac sleep and the guest clock

When the Mac is about to sleep, the supervisor pauses each running VM over QMP (`stop`), unless the VM's "pause while the Mac sleeps" setting is off. When the Mac wakes, it resumes only a pause it made itself, then posts the Darwin notification `dev.tryomarchy.host-wake`. The time-zone bridge forwards that as `{"type":"wake"}` on `dev.linuxvm.timezone`. A wake is posted for every running VM, paused or not, because Linux's clock also stops while the Mac sleeps.

The message carries no time. On wake, guest tools 0.2.0 and later compare the system clock with the RTC. If the system clock is more than 5 seconds behind, they step it forward to the RTC's time. They never move the clock backward and never write the RTC. Network time synchronization handles small and backward corrections. A periodic check covers missed wake messages. All of this runs only when the `linuxvm.host` credential is present.

## Guest status

`dev.linuxvm.status` tells the Mac which guest tools a VM runs and whether its integration is working. The app compares the version with its Guest Tools disc and reports a disabled extension.

Both directions carry UTF-8 JSON objects, one per line, at most 4096 bytes per line. Each side ignores message types and keys it does not know, and drops lines that are too long or malformed.

- Guest → Mac:

  ```json
  {"type":"status","package":"0.2.0","os":"Ubuntu 26.04.1 LTS","shell":"50.1","extension":"active"}
  ```

  - `package`: the installed `linuxvm-guest` version, `MAJOR.MINOR.PATCH`.
  - `os`: `PRETTY_NAME` from `/etc/os-release`, at most 128 characters.
  - `shell`: GNOME Shell's version, at most 32 characters, or absent if unknown.
  - `extension`: the state of `clipboard@linuxvm.dev` in GNOME Shell:
    - `active`: enabled and running;
    - `inactive`: installed but disabled;
    - `outdated`: GNOME Shell rejects it as made for another Shell version;
    - `error`: it failed to load or run;
    - `missing`: GNOME Shell does not know it;
    - `unknown`: anything else, including a transition.
- Mac → guest: `{"type":"query"}`. The guest answers with a status message.

The guest sends a status message when its agent starts, when the extension's state changes and when asked. The sender is a user service in the graphical session, so a VM reports only while someone is logged in. The Mac keeps the last report for each VM across runs and treats every value as untrusted.

## Guest tools delivery

The app attaches `guest-tools.iso` (volume label `LINUXVM-TOOLS`) to every VM as a removable read-only USB CD. It contains `linuxvm-guest_<version>_all.deb`, `install.sh` and `README.txt`. From 0.2.0 the disc has Rock Ridge extensions, so `install.sh` is executable.

## Versions and compatibility

- Every change to the guest package raises its version.
- Interfaces are only added, never changed incompatibly: new ports, message types and keys. A guest service whose port is absent does not start. So an older app works with newer guest tools, and a newer app works with older guest tools, which simply send no status.
- The clipboard extension declares only the GNOME Shell major versions it was tested on. After a GNOME upgrade to an untested version, GNOME Shell marks it out of date, the status reports `"extension":"outdated"`, and the app says so. Updated guest tools ship on the Guest Tools disc; there is no apt repository.
