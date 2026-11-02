# Supervisor storage verification — 2 November 2026

Verified from the `t3/supervisor-storage-removal` worktree using its debug `linuxvmctl`, with QEMU, firmware and bridge helper from `/Applications/Linux VM.app/Contents`. No app UI or host–guest interface changed.

`swift test --package-path macos`:

```text
✔ Test run with 31 tests in 5 suites passed after 0.009 seconds.
```

`swift build --package-path macos` succeeded. The existing 20 tests and 11 added storage tests passed. Tests cover the pure removal policy, exact volume identity, symlink and `/tmp` normalization, similarly named mounts, boot/data exclusion, changed/ejected/absent media, absent shares, `st_dev` fallback, and callback integration with a failed-QMP kill of an owned test process.

## Setup commands

Paths below abbreviate the actual temporary directory as `$T`, the worktree binary as `$CTL`, and the returned VM identifier as `$ID`. The final run used volume suffix `CRFP0N`, VM `434FA87C-1BD4-4B9C-8C9B-B60CE03F1D48`, supervisor PID 42829 and QEMU PID 42849. Only one test VM ran at a time, with 1 CPU, 2048 MiB RAM and an 8 GiB sparse raw disk. Product resource limits were unchanged.

```sh
swift build --package-path macos
CTL="$PWD/macos/.build/out/Products/Debug/linuxvmctl"
hdiutil create -size 12g -fs APFS -volname LVMSTOR-A-CRFP0N -type SPARSEBUNDLE "$T/A.sparsebundle"
hdiutil create -size 1g -fs APFS -volname LVMSTOR-B-CRFP0N "$T/B.dmg"
hdiutil create -size 1g -fs APFS -volname LVMSTOR-C-CRFP0N "$T/C.dmg"
# Each image was attached with hdiutil attach -nobrowse -plist IMAGE.
export LINUXVM_LIBRARY=/Volumes/LVMSTOR-A-CRFP0N/library
export LINUXVM_CONTENTS="/Applications/Linux VM.app/Contents"
"$CTL" create --name stor-test --cpus 1 --memory 2048 --disk 8
mkdir /Volumes/LVMSTOR-C-CRFP0N/share
"$CTL" set "$ID" --shared-folder /Volumes/LVMSTOR-C-CRFP0N/share
# iso-content contained one small text file.
hdiutil makehybrid -iso -joliet -o /Volumes/LVMSTOR-B-CRFP0N/x.iso "$T/iso-content"
LINUXVM_DEBUG_SLEEP_SIGNALS=1 "$CTL" run "$ID" >"$T/supervisor.log" 2>&1 &
```

The supervisor was launched directly with `run`, never with `start`. Its temporary run directory was `/tmp/linuxvm.6niJMR`. The VM only booted firmware. SIGUSR1/SIGUSR2 sent to this supervisor produced QMP states `paused` and `running`, with the normal pause/resume log lines; the Mac was never put to sleep.

## Commands and observed results

```text
$ diskutil eject /Volumes/LVMSTOR-A-CRFP0N
Unmount ... failed: at least one volume could not be unmounted
Unmount was dissented by PID 42829 (...)                         [exit 1]
supervisor: Linux VM “stor-test” is running from this drive. Shut it down first.

$ diskutil eject /Volumes/LVMSTOR-C-CRFP0N
Unmount ... failed: at least one volume could not be unmounted
Unmount was dissented by PID 42829 (...)                         [exit 1]
supervisor: This drive is shared with Linux VM “stor-test”. Shut it down first.

$ "$CTL" insert "$ID" /Volumes/LVMSTOR-B-CRFP0N/x.iso             [exit 0]
query-block: install, inserted.file=.../x.iso, tray_open=false
$ diskutil eject /Volumes/LVMSTOR-B-CRFP0N
Disk /Volumes/LVMSTOR-B-CRFP0N ejected                            [exit 0]
query-block: install, no inserted medium, tray_open=true
supervisor: Ejected the installer disc before unmounting /Volumes/LVMSTOR-B-CRFP0N
```

`diskutil` printed the dissenting PID, but did not print the supplied dissent string on this macOS version. The exact messages above were recorded in the supervisor log and passed to `DADissenterCreate`.

The disc image was reattached, `x.iso` copied to `changed.iso`, and the medium replaced directly over the control QMP socket, leaving `config.json` at `x.iso`:

```json
{"execute":"blockdev-change-medium","arguments":{"id":"install-cd","filename":"/Volumes/LVMSTOR-B-CRFP0N/changed.iso","format":"raw","read-only-mode":"read-only"}}
```

QMP confirmed `inserted.file=.../changed.iso`. On this macOS version `hdiutil detach -force` still sends an approval request first. To verify the already-disconnected path, only the owned supervisor was briefly SIGSTOPed during disc detach, then SIGCONTed immediately after detach returned. QEMU kept running throughout. The pending approval was recognized as stale because the original mount/device was gone.

```text
$ kill -STOP 42829
$ hdiutil detach -force /Volumes/LVMSTOR-B-CRFP0N                 [exit 0]
$ kill -CONT 42829
0.061 s after resume: query-block has no inserted medium, tray_open=true; QEMU alive
supervisor: The installer disc's drive was disconnected; ejected the disc

$ hdiutil detach -force /Volumes/LVMSTOR-C-CRFP0N                 [exit 0]
QEMU alive
supervisor: The drive shared with Linux VM “stor-test” was disconnected; keeping the VM running

$ hdiutil detach -force /Volumes/LVMSTOR-A-CRFP0N                 [exit 0]
QEMU gone in 0.116 s (timed from invoking detach)
supervisor: The drive holding the VM was disconnected; stopping QEMU immediately
supervisor: QEMU exited with status 0
supervisor process exit: 74
run directory removed: true
```

After reattaching the library, `linuxvmctl status "$ID"` returned `stopped`, confirming the lock was released. All attached test images were detached, and all test images, VM data and temporary directories were deleted. No user's library, Ubuntu VM, UTM VM or harness VM was touched.

A physical cable pull and a live QEMU that acknowledges `quit` but remains alive until the two-second watchdog were not exercised. Forced APFS detach covered removal, and the integration test covered SIGKILL when QMP cannot connect. Finder's visual presentation of the dissent string was not checked.
