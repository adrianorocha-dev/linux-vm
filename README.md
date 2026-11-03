# Linux VM

A macOS app that runs Ubuntu on Apple Silicon with Mac-quality trackpad, display and cursor behaviour. It builds on Try Omarchy's patched QEMU runtime and its Mac bridge helper.

## Layout

- `macos/`: Swift package.
  - `LinuxVMCore`: VM library, QEMU launch, supervision, QMP, runtime checks.
  - `linuxvmctl`: the command-line tool, which is also the per-VM supervisor the app starts.
  - `LinuxVM`: the SwiftUI app.
- `guest/`: the Ubuntu guest tools package (`linuxvm-guest`) and the Guest Tools disc.
- `docs/host-guest-contract.md`: the only interfaces between the Mac and the guest.
- `docs/what-needs-guest-tools.md`: what works without the guest tools, and what needs them.
- `docs/proposal.md`: the investigation and proposal, with Milestone 0 and 1 results. `docs/milestone-0-notes.md` and `docs/utm-ubuntu-report.md` hold the measurements behind it.
- `docs/milestone-3-plan.md`: the current milestone, releasing the app. `docs/milestone-2-plan.md`: Milestone 2, closed on 3 November 2026. `docs/future-tests.md` lists the checks it left for later.
- `runtime/`: our changes to Try Omarchy v1.3.0's QEMU runtime build, and how to build it.
- `scripts/build-app.sh`: assembles `build/Linux VM.app`. `scripts/ssh-vm.sh`, `scripts/qmp-type.py` and `scripts/guest-diagnostics.sh` are test helpers.
- `scripts/harness/`: the test harness. It installs a fresh VM unattended and captures monitor state, screenshots, touchpad input and frame timing from inside the guest. It also repeats a VM's start, reboot, sleep and shutdown (`soak`), and replays touchpad contacts across pauses and reboots (`touch-lifecycle`) ([README](scripts/harness/README.md)).

## How a VM runs

The app starts `linuxvmctl run <id>` in its own session. That supervisor holds the VM folder's lock, starts QEMU, starts the clipboard, audio and time-zone bridges from `omarchy-vm-helper`, restarts a bridge up to five times, and removes its run state when QEMU exits. It also pauses the VM while the Mac sleeps (a per-VM setting, on by default), then prompts Linux to correct its clock, and saves what the guest tools report about themselves. VMs therefore keep running when the app quits. The app and `linuxvmctl` control a running VM through a second QMP socket.

Each VM is a folder in `~/Library/Application Support/Linux VM/VMs/<id>/` with `config.json`, a sparse raw disk (or an imported QCOW2), the UEFI variable store, `scroll-scale`, `guest.json` (the guest tools' last report) and `logs/`.

The defaults follow our Milestone 0 measurements: the guest's own cursor without the Mac arrow, immersive full screen below the camera housing, and touch scrolling at 0.4 of Try Omarchy's travel.

## Removable storage

While a VM runs, ejecting the drive holding its VM folder or shared folder is refused with a message naming the VM. Ejecting an installer image’s drive first ejects the disc from the VM, then allows the drive to unmount. The supervisor checks the currently inserted disc, including changes made while running.

If a drive is forcibly removed or disconnected, losing the VM folder stops QEMU immediately, without asking Linux to shut down. The supervisor releases its lock, removes its temporary run directory, and exits with status **74** (storage disconnected), even if QEMU exits successfully. It tries QMP `quit`, then kills QEMU if that fails or QEMU remains alive after two seconds. Losing an installer image ejects the disc and keeps the VM running; losing a shared folder is logged and also keeps it running. DiskArbitration notifications and a once-per-second filesystem check detect removal. The Mac’s boot/data volume is excluded.

## Building

Prerequisites: an Apple Silicon Mac with macOS 15 or newer, Xcode command line tools, pkg-config, and Python 3.11 or newer with working venvs (`brew install pkgconf python@3.14`). See [runtime/README.md](runtime/README.md).

Steps:
1. Build the QEMU runtime: `scripts/build-runtime.sh`.
2. Build the guest tools: `python3 guest/build.py` and `guest/build-tools-iso.sh`. The disc needs `xorriso` (`brew install xorriso`).
3. Build the app: `scripts/build-app.sh`. It ends with a runtime capability check. To share it, see [Sharing the app](#sharing-the-app).

Tests:
- `swift test --package-path macos`
- `python3 -m unittest discover guest/tests`
- `python3 -m unittest discover scripts/harness/tests`
- `python3 -m unittest discover scripts/tests` (clones the pinned Try Omarchy source if `.deps/try-omarchy` is absent; does not build it)

## Sharing the app

`scripts/build-app.sh` signs ad hoc, so the build runs only on this Mac without a Gatekeeper warning. To share it, sign it with a Developer ID and have Apple notarize it:

1. Once per Mac, in Xcode → Settings → Accounts → Manage Certificates, add a "Developer ID Application" certificate for your team. Then store notary credentials in the keychain: `xcrun notarytool store-credentials linuxvm-notary --apple-id <Apple ID> --team-id <team ID>`, with an app-specific password from account.apple.com.
2. Build with the identity: `LINUXVM_SIGN_IDENTITY="Developer ID Application: <name> (<team ID>)" scripts/build-app.sh`. Every executable gets the identity, the hardened runtime and a secure timestamp. QEMU keeps the hypervisor and microphone entitlements (`macos/Resources/qemu.entitlements`); the app and supervisor have the microphone one (`macos/Resources/app.entitlements`).
3. Package and notarize: `LINUXVM_SIGN_IDENTITY=… LINUXVM_NOTARY_PROFILE=linuxvm-notary scripts/package-dmg.sh`. It writes `build/Linux VM <version>.dmg`, signed, notarized and stapled.

For the app to update itself through Sparkle, step 2 also needs `LINUXVM_UPDATE_FEED` (the feed's https URL) and `LINUXVM_UPDATE_KEY` (the EdDSA public key). Without them the app has no updater. An update never installs while a VM runs. See [Milestone 3](docs/milestone-3-plan.md#sparkle-in-the-app-3-november-2026).

Recipients need an Apple Silicon Mac with macOS 15 or later. Without `LINUXVM_NOTARY_PROFILE`, step 3 only signs the image, to check the steps; any signing identity works for that.

## Releasing

Complete the certificate and notary setup in [Sharing the app](#sharing-the-app).
Install GitHub CLI (`brew install gh`) and sign in with `gh auth login`.
Create a public releases repository with an initial README commit and no app source.
Set its owner/name in `scripts/release-config.json`.
The script derives the feed URL as `https://github.com/<owner>/<name>/releases/latest/download/appcast.xml`.

Run `.deps/sparkle-2.10.0/bin/generate_keys` once to create the EdDSA key in your login keychain.
If needed, unpack [Sparkle 2.10.0](https://github.com/sparkle-project/Sparkle/releases/download/2.10.0/Sparkle-2.10.0.tar.xz) there after verifying its SHA-256 is `c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c`.
Put the printed public key in the config's `public_key`.
Back up the private key securely.
The release script fetches and verifies absent tools.

Set `source_archive_directory` to a durable absolute folder outside the repository, or set `LINUXVM_RELEASE_SOURCE_DIR` on this Mac.
Set `offer_contact` in `licenses/manifest.json` to your source-offer contact.
Commit these settings; placeholders block a release.

For each release, set `CFBundleShortVersionString` in `macos/Resources/Info.plist` to `MAJOR.MINOR.PATCH` and raise the integer `CFBundleVersion` above every published build.
Add `docs/releases/VERSION.md` using the [notes format](docs/releases/README.md).
Build the Guest Tools disc using [Building](#building).
Commit and push these changes, then run from a clean `main` equal to `origin/main`:

```sh
LINUXVM_SIGN_IDENTITY="Developer ID Application: <name> (<team ID>)" python3 scripts/release.py VERSION
```

The script builds, signs, notarizes, and retains source before asking to publish.
It uses `linuxvm-notary` unless `LINUXVM_NOTARY_PROFILE` names another profile.
Review the summary and back up the retained source archive before typing `publish`.
Keep that archive for at least three years after the version's last distribution.
The script pushes an annotated source tag, creates a public draft release, publishes it, and checks the public bytes.
Artifacts stay in `build/release/VERSION/`, including `LinuxVM-VERSION.dmg` and `appcast.xml`.
Use `--dry-run` to do all preparation, including signing and notarization, without tagging, pushing, or publishing.
A later run of the same commit reuses the retained archive, so a dry run and then the real release collect the source once. Retained archives are never overwritten.
If publication fails partway through, inspect the origin tag and public release before retrying.

## Command line

```
linuxvmctl list | check
linuxvmctl create --name N --iso PATH [--cpus N] [--memory MIB] [--disk GIB]
linuxvmctl import --name N --disk PATH [--efi-vars PATH]
linuxvmctl start|stop [--force]|status|show|delete VM
linuxvmctl set VM [--cpus N] [--memory MIB] [--iso PATH|none] [--shared-folder PATH|none] [--scroll-scale X] [--pause-during-sleep on|off] ...
```

`status` also shows the guest tools version a VM last reported, and whether it is older than the app's Guest Tools disc.

The tool is at `Linux VM.app/Contents/Helpers/linuxvmctl`.

## Licenses

The app's notices, source offer, license texts and provenance manifest live in `Contents/Resources/Licenses/`.
`scripts/build-app.sh` checks license texts, every bundle file and the files inside the Guest Tools disc before signing, then checks coverage again after signing.
Developer ID builds and tests also verify all third-party input pins, checksums and upstream license bytes.
Ad hoc builds use local checks without cloning or downloading inputs.
Original app and Guest Tools code has no manifest checksums.
Their notice versions come from Info.plist and guest/build.py.
An unlisted component or missing license text stops the build.
Developer ID builds also require a source-offer contact and resolved provenance gaps.
Linux VM’s own code is available under the MIT License ([LICENSE](LICENSE)).
See [licenses/README.md](licenses/README.md) for the inventory, current release blockers and how to add a component.

Retain release source outside the app with `python3 scripts/retain-release-source.py --output /path/to/retained/linux-vm-VERSION-source.tar.gz`.
The collector verifies sources, bottle formulas and patches and records their checksums.
Keep a complete archive for at least three years after the release's last distribution.
ANGLE's revision comes from its binary version string.
Its permissive dependency notices use pinned DEPS reference revisions and impose no source-distribution obligation.
The collector requires all copyleft sources and treats ANGLE's source as best effort.
See [source retention](licenses/README.md#retaining-release-source) for the contents and subset test.
