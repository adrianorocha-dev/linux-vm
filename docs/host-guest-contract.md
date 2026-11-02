# Host–guest contract

The Mac app (`macos/`) and the Ubuntu guest tools (`guest/`) meet only at the interfaces below.

## Virtual devices

- `virtio-serial-pci` with these `virtserialport` names. On the Mac, each port is a QEMU UNIX socket served by an `omarchy-vm-helper` bridge from Try Omarchy v1.3.0. The wire protocol on each port is exactly the one that bridge speaks; see `NativeClipboardBridge.swift`, `NativeAudioBridge.swift` and `NativeTimeZoneBridge.swift` in `.deps/try-omarchy/macos/Sources/OmarchyVMHelper/`.
  - `dev.linuxvm.clipboard`: helper `--bridge-native-clipboard`.
  - `dev.linuxvm.audio`: helper `--bridge-native-audio` (QEMU runs with `OMARCHY_SDL_AUDIO_CONTROL_DIRECTORY`).
  - `dev.linuxvm.timezone`: helper `--bridge-native-timezone`.
- The shared Mac folder, when enabled: `virtio-9p-pci` with mount tag `mac`, exported with `security_model=none,multidevs=remap,guest_owner_uid=1000,guest_owner_gid=1000`. Files appear owned by uid/gid 1000, the first Ubuntu user.
- The virtual touchpad `QEMU Virtio Pinch Touchpad` (`virtio-pinch-pci`). The Mac has already applied the scroll direction and scale.

## Host settings

The Mac passes one systemd credential, `linuxvm.host`, through SMBIOS type 11 (`io.systemd.credential.binary:linuxvm.host=<base64>`). It holds `key=value` lines:

- `timezone=<IANA zone>`: the Mac's zone at launch.
- `shared_folder_name=<name>`: present only when a folder is shared. URL-safe base64 of the Mac folder's last path component, without padding.

The guest treats every value as untrusted.

## Guest tools delivery

The app attaches `guest-tools.iso` (volume label `LINUXVM-TOOLS`) to every VM as a removable read-only USB CD. It contains `linuxvm-guest_<version>_all.deb`, `install.sh` and `README.txt`.
