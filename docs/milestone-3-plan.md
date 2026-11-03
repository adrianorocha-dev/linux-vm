# Milestone 3 plan: release the app

Milestone 2 made the app dependable on this Mac ([plan](milestone-2-plan.md)). Milestone 3 makes it something friends can install and keep up to date, with its licenses in order and its runtime rebuildable from a clean checkout. Its scope comes from the proposal's [Milestone 3](proposal.md#milestone-3--release-and-upstream-work), narrowed by the user on 3 November 2026.

## Starting state

- **App:** version 0.1.0, signed with the user's Developer ID. `scripts/package-dmg.sh` makes a notarized, stapled DMG ([README](../README.md#sharing-the-app)). There are no version tags or releases yet. The repository is private.
- **Licenses:** the bundle ships Try Omarchy's license and the edk2 firmware's licenses. It ships nothing for QEMU (GPLv2) or the 15 libraries in `Contents/Resources/runtime/lib`, several of them LGPL (GLib, libintl, libusb).
- **Runtime build:** every input is pinned by checksum. QEMU, libslirp, virglrenderer and the build tools are built from source archives, and some libraries come from pinned Homebrew bottles. Setting it up takes the manual steps in [runtime/README.md](../runtime/README.md).
- **Updates:** none. Each new version is a DMG sent by hand.

## Workstreams

### 1. Licenses and provenance

- **Inventory.** Record every component in the app bundle and on the Guest Tools disc: its version, its license, and its source archive or bottle with the pinned checksum. That includes our own patches and Try Omarchy's.
- **In the bundle.** Ship each license text in `Contents/Resources/Licenses/`, with one notices file that lists every component.
- **Enforced by the build.** `scripts/build-app.sh` fails when the bundle holds an executable, library or component that the notices don't cover.
- **In the app.** The app can show the notices, for example from its About window.
- **Source.** The source isn't bundled (decision of 2 November). QEMU's GPLv2 requires the source, or a written offer of it, to go with the binary. So the notices carry a written offer to provide the complete source on request. Because the DMG will be public, this covers anyone who downloads it.

### 2. Releases and automatic updates

- **Versions.** `CFBundleShortVersionString` is `MAJOR.MINOR.PATCH`. `CFBundleVersion` is a build number that only grows, because Sparkle compares it. Each release is tagged `vX.Y.Z` in this repository and has short release notes.
- **Sparkle in the app.** Sparkle 2 is embedded in `Contents/Frameworks` and signed with the app. Info.plist names the update feed and the public EdDSA key. The app menu gets "Check for Updates…". Sparkle asks on the second launch whether to check automatically.
- **Running VMs.** A VM runs from inside the app bundle: the supervisor, QEMU and the bridges, which the supervisor restarts from the bundle's path. Replacing the bundle under a running VM would mix the old QEMU with new bridges. So the app installs an update only when no VM is running, and asks you to shut them down first. What actually happens otherwise gets tested before this rule is relaxed.
- **Compatibility.** A newer app opens VM folders written by older ones, which saved 0.1.0 configurations test. After installing, the app checks its runtime as it does today.
- **Hosting.** A public GitHub repository that holds only releases, with no source. Each release carries the DMG, and the update feed (`appcast.xml`) is published there too.
- **Release script.** From a clean `main`, the script:
  - builds and signs the app, then notarizes and staples the DMG;
  - signs the update with the EdDSA key and writes the feed entry;
  - tags the version and publishes the release.

  Publishing is the last step, and it waits for your confirmation.
- **First release.** Friends on 0.1.0, which has no updater, install the first Sparkle version by hand. A second release then checks the update path end to end on a real copy with VMs.

### 3. One-command runtime build

- `scripts/build-runtime.sh` builds the runtime from a clean checkout. It:
  - checks the prerequisites;
  - fetches Try Omarchy at `v1.3.0` and verifies the commit;
  - applies our diff;
  - fetches and verifies every source archive;
  - builds the runtime where `scripts/build-app.sh` expects it.
- Archives made locally from git, QEMU's and keycodemapdb's, are verified by their commit. A different git or gzip then no longer breaks the build.
- It is tested from a fresh clone in a temporary folder, and the result is compared with the current runtime: the same files and the same patches. The test also records the build time.
- `runtime/README.md` shrinks to running the script, plus what it does.

## Progress

### Sparkle in the app (3 November 2026)

- **In the bundle.** Sparkle 2.10.0, pinned in `macos/Package.resolved`, sits in `Contents/Frameworks`, signed with the rest of the app. Its XPC services are left out, because the app isn't sandboxed. The app menu has "Check for Updates…".
- **Configuration.** `scripts/build-app.sh` writes the feed and the public key into Info.plist from `LINUXVM_UPDATE_FEED` and `LINUXVM_UPDATE_KEY`. A build without them has no updater. Silent installs are off (`SUAllowsAutomaticUpdates`), so every update is shown before it installs.
- **Replacing the bundle under a running VM, tested.** QEMU kept running, and so did the bridges that were already running. A bridge that restarted could not attach: macOS reports no path for the running QEMU, whose file had been deleted, so the helper refuses it. The clipboard stayed off for the rest of that run.
- **So updates wait for VMs.** An update found while a VM runs isn't downloaded. The window shows "Update to …" instead, which shuts the VMs down and then installs. An install that starts while a VM runs waits the same way. One case remains: Sparkle always installs an update it has already downloaded when the app quits. If a VM was started after the download, it keeps running, but its bridges can't restart until the VM restarts.
- **Verified on this Mac** with two Developer ID test copies, a test bundle identifier, a throwaway EdDSA key and a local feed:
  - with a VM running, the check fetched the feed, downloaded nothing, and the window showed "Update to 0.2.1";
  - with no VM running, Sparkle downloaded and verified the DMG and installed 0.2.1 two seconds after the app quit. This used silent installs, which only the test copies allow;
  - the updated copy kept its Developer ID signature, passed its runtime check and started its VM.
- **Not verified yet:** the path with clicks. That is Sparkle's update window, Install and Relaunch, and the shut-down prompt. It needs someone at the Mac.

### One-command runtime build (3 November 2026)

GPT-6.1-Sol built it, and Claude reviewed and merged it.

- **`scripts/build-runtime.sh`** checks the prerequisites and clones Try Omarchy at the pinned commit. It applies our diff, then builds. It accepts a pristine or an exactly patched checkout and refuses anything else.
- **Pinned by commit.** QEMU and keycodemapdb are fetched by commit, checked with `git fsck`, and archived again from the verified objects. Local git and gzip versions no longer matter. `scripts/build-app.sh` gets its firmware source the same way. The commits live in `runtime/source-pins.sh`.
- **Verified.** A fresh clone with no cache built the runtime in 2 minutes 25 seconds, and the app built from it passed `linuxvmctl check`. The result has the same 17 files, libraries, entitlements and patches as the previous runtime. Fourteen files are byte-identical. QEMU, libslirp and virglrenderer differ only by the macOS SDK they were built with (27.2 instead of 27.0). The main checkout was rebuilt the same way in 1 minute 45 seconds.

## Steps that belong to the user

- **The EdDSA key pair.** Sparkle's `generate_keys` keeps the private key in your login keychain and prints the public key for Info.plist. Back the private key up: without it, installed copies can't be updated.
- **The public releases repository:** its name, and creating it.
- **Approving each publish.**

## How the work is split

- **GPT-6.1-Sol:** the one-command runtime build, the license inventory with the build's notices check, and the release script.
- **Claude:** Sparkle in the app and all its UI, signing, integration, and verification on this Mac.

## Done means

- A clean checkout builds the runtime with one command, and then the app.
- Every component in the app and on the disc has its license and source recorded, and the build fails if one is missing.
- A copy of one release, with VMs, updates itself to the next release and keeps its VMs.
- Releases are tagged and have release notes.

## Decisions

Made on 3 November 2026:

- **Scope:** licenses, updates and the one-command runtime build. Help and diagnostics, a second distribution (Fedora) and upstream proposals wait.
- **Updates:** Sparkle, with releases published publicly.

Carried over:

- **Source:** not bundled with the app (2 November).

## Open

- The name of the public releases repository.
- A license for our own code. There is none yet, which doesn't block the notices.
