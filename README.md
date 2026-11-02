# Linux VM

A macOS app that runs Ubuntu on Apple Silicon with Mac-quality trackpad, display and cursor behaviour. It builds on Try Omarchy's patched QEMU runtime and its Mac bridge helper.

## Layout

- `macos/`: Swift package.
  - `LinuxVMCore`: VM library, QEMU launch, supervision, QMP, runtime checks.
  - `linuxvmctl`: the command-line tool, which is also the per-VM supervisor the app starts.
  - `LinuxVM`: the SwiftUI app.
- `guest/`: the Ubuntu guest tools package (`linuxvm-guest`) and the Guest Tools disc.
- `docs/host-guest-contract.md`: the only interfaces between the Mac and the guest.
- `runtime/`: our changes to Try Omarchy v1.3.0's QEMU runtime build, and how to build it.
- `scripts/build-app.sh`: assembles `build/Linux VM.app`.

## How a VM runs

The app starts `linuxvmctl run <id>` in its own session. That supervisor holds the VM folder's lock, starts QEMU, starts the clipboard, audio and time-zone bridges from `omarchy-vm-helper`, restarts a bridge up to five times, and removes its run state when QEMU exits. VMs therefore keep running when the app quits. The app and `linuxvmctl` control a running VM through a second QMP socket.

Each VM is a folder in `~/Library/Application Support/Linux VM/VMs/<id>/` with `config.json`, a sparse raw disk (or an imported QCOW2), the UEFI variable store, `scroll-scale` and `logs/`.

The defaults follow our Milestone 0 measurements: the guest's own cursor without the Mac arrow, immersive full screen below the camera housing, and touch scrolling at 0.4 of Try Omarchy's travel.

## Building

Prerequisites: the patched QEMU runtime and the pinned QEMU source archive, set up as described in [runtime/README.md](runtime/README.md).

Steps:
1. Build the guest tools: `python3 guest/build.py` and `guest/build-tools-iso.sh`.
2. Build the app: `scripts/build-app.sh`. It ends with a runtime capability check.

Tests:
- `swift test --package-path macos`
- `python3 -m unittest discover guest/tests`

## Command line

```
linuxvmctl list | check
linuxvmctl create --name N --iso PATH [--cpus N] [--memory MIB] [--disk GIB]
linuxvmctl import --name N --disk PATH [--efi-vars PATH]
linuxvmctl start|stop [--force]|status|show|delete VM
linuxvmctl set VM [--cpus N] [--memory MIB] [--iso PATH|none] [--shared-folder PATH|none] [--scroll-scale X] ...
```

The tool is at `Linux VM.app/Contents/Helpers/linuxvmctl`.

## Licenses

The QEMU runtime and the bridge helper come from Try Omarchy (MIT, `Contents/Resources/LICENSE.try-omarchy`) and QEMU (GPLv2 with component exceptions). The edk2 firmware's licenses ship beside it. Review the full bundle before distributing it.
