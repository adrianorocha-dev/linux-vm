# Milestone 3 plan: release the app

**Closed on 4 November 2026.** [Milestone 4](milestone-4-plan.md) adds Fedora and KDE Plasma.

Milestone 2 made the app dependable on this Mac ([plan](milestone-2-plan.md)). Milestone 3 makes it something friends can install and keep up to date, with its licenses in order and its runtime rebuildable from a clean checkout. Its scope comes from the proposal's [Milestone 3](proposal.md#milestone-3--release-and-upstream-work), narrowed by the user on 3 November 2026.

## Starting state

- **App:** version 0.1.0, signed with the user's Developer ID. `scripts/package-dmg.sh` makes a notarized, stapled DMG ([development notes](development.md#sharing-the-app)). There are no version tags or releases yet. The repository is private.
- **Licenses:** the bundle ships Try Omarchy's license and the edk2 firmware's licenses. It ships nothing for QEMU (GPLv2) or the 15 libraries in `Contents/Resources/runtime/lib`, several of them LGPL (GLib, libintl, libusb).
- **Runtime build:** every input is pinned by checksum. QEMU, libslirp, virglrenderer and the build tools are built from source archives, and some libraries come from pinned Homebrew bottles. Setting it up takes the manual steps in [runtime/README.md](../runtime/README.md).
- **Updates:** none. Each new version is a DMG sent by hand.

## Workstreams

### 1. Licenses and provenance

- **Inventory.** Record every component in the app bundle and on the Guest Tools disc: its version, its license, and its source archive or bottle with the pinned checksum. That includes our own patches and Try Omarchy's.
- **In the bundle.** Ship each license text in `Contents/Resources/Licenses/`, with one notices file that lists every component.
- **Enforced by the build.** `scripts/build-app.sh` fails when the bundle holds an executable, library or component that the notices don't cover.
- **In the app.** The app can show the notices, for example from its About window.
- **Source.** The source isn't bundled in the app (decision of 2 November). Instead, each release publishes its complete corresponding source next to its DMG on the GitHub release (decision of 3 November). GPLv2 counts source offered from the same place as the binary as distributing it. The notices name that release page and the repository's Issues page for questions.
- **Source archive.** A script gathers each release's complete corresponding source into one archive. That covers every pinned archive and git source, the upstream source and formula of every Homebrew bottle we ship, our patches, and the build scripts.

### 2. Releases and automatic updates

- **Versions.** `CFBundleShortVersionString` is `MAJOR.MINOR.PATCH`. `CFBundleVersion` is a build number that only grows, because Sparkle compares it. Each release is tagged `vX.Y.Z` in this repository and has short release notes.
- **Sparkle in the app.** Sparkle 2 is embedded in `Contents/Frameworks` and signed with the app. Info.plist names the update feed and the public EdDSA key. The app menu gets "Check for Updates…". Sparkle asks on the second launch whether to check automatically.
- **Running VMs.** A VM runs from inside the app bundle: the supervisor, QEMU and the bridges, which the supervisor restarts from the bundle's path. Replacing the bundle under a running VM would mix the old QEMU with new bridges. So the app installs an update only when no VM is running, and asks you to shut them down first. What actually happens otherwise gets tested before this rule is relaxed.
- **Compatibility.** A newer app opens VM folders written by older ones, which saved 0.1.0 configurations test. After installing, the app checks its runtime as it does today.
- **Hosting.** This repository's GitHub releases, now that it's public. Each release carries the DMG, the update feed (`appcast.xml`) and the source archive.
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
- **Verified with clicks** when 0.2.0 updated itself to 0.2.1: the shut-down prompt, Sparkle's update window, and Install and Relaunch. See [Second release](#second-release-021-4-november-2026).

### One-command runtime build (3 November 2026)

GPT-6.1-Sol built it, and Claude reviewed and merged it.

- **`scripts/build-runtime.sh`** checks the prerequisites and clones Try Omarchy at the pinned commit. It applies our diff, then builds. It accepts a pristine or an exactly patched checkout and refuses anything else.
- **Pinned by commit.** QEMU and keycodemapdb are fetched by commit, checked with `git fsck`, and archived again from the verified objects. Local git and gzip versions no longer matter. `scripts/build-app.sh` gets its firmware source the same way. The commits live in `runtime/source-pins.sh`.
- **Verified.** A fresh clone with no cache built the runtime in 2 minutes 25 seconds, and the app built from it passed `linuxvmctl check`. The result has the same 17 files, libraries, entitlements and patches as the previous runtime. Fourteen files are byte-identical. QEMU, libslirp and virglrenderer differ only by the macOS SDK they were built with (27.2 instead of 27.0). The main checkout was rebuilt the same way in 1 minute 45 seconds.

### Licenses and provenance (3 November 2026)

GPT-6.1-Sol built it in three rounds. Claude reviewed each round, redrew the icon, and merged it with one fix.

- **Inventory.** `licenses/manifest.json` lists every component in the app and on the Guest Tools disc, 23 in all with Sparkle. Each has its version, license, source and pinned checksum. `licenses/README.md` explains how to update it.
- **In the bundle.** `Contents/Resources/Licenses/` holds every license text, the upstream copyright notices and `NOTICES.txt` with the written source offer. `LGPL-REPLACEMENT.txt` explains how to replace an LGPL library in a personal copy.
- **Enforced.** The build fails when the bundle or the disc holds a file the manifest doesn't cover. Developer ID builds also verify every third-party input, and refuse while a release blocker remains. The checks add under half a second to an ad hoc build. Changing our own code needs no manifest edit.
- **Findings resolved.** The icon used an SF Symbol, which Apple's license doesn't allow in app icons, so its prompt is now drawn as paths. ANGLE's exact source was established from the version string in the shipped library (commit `bb9e1870521d`), and its bundled third-party code is covered. Zstandard's embedded xxHash and libdivsufsort notices come from its exact source.
- **Source kept for requests.** `scripts/retain-release-source.py` gathers the complete corresponding source of a build into one archive and verifies every checksum. A full run produced 380 MiB from 97 inputs, marked complete.
- **Fixed at merge.** Two ANGLE dependency archives come from Gitiles, which regenerates its archives on every request. They are now pinned by their contents rather than their bytes.
- **Left open:** the source-offer contact, which blocks Developer ID builds until it's set, and a license for our own code.

### Release script (3 November 2026)

GPT-6.1-Sol built it, and Claude reviewed and merged it with one fix.

- **`scripts/release.py VERSION`** checks that `main` is clean and pushed, that the version matches Info.plist, and that the build number beats every published one. It also requires release notes in `docs/releases/VERSION.md`, and an EdDSA key in the keychain that matches the config.
- **It prepares everything first.** It builds, signs and notarizes the app, then verifies the DMG and signs the update. It writes `appcast.xml` with the new release first, followed by the published history, and retains the source. Then it shows a summary.
- **Publishing waits for "publish".** Then it pushes the tag, creates a draft release with the DMG and feed, publishes it, and checks the public bytes. `--dry-run` stops before that step.
- **Config.** `scripts/release-config.json` holds the repository and the public key. While they are placeholders, a release refuses to start and names what's missing. Since the repository went public, the source archive is attached to each release instead of kept in a private folder.
- **Fixed at merge.** A dry run kept the source archive, so the real release of the same commit then refused to run. A verified, complete archive of the same commit is now reused.
- **Verified** with stubbed commands only: 24 tests. Nothing was signed, notarized or published. The first real release will be the end-to-end check.

### First release: 0.2.0 (3 November 2026)

- **Published** at [v0.2.0](https://github.com/adrianorocha-dev/linux-vm/releases/tag/v0.2.0), from commit `a675d5b`, with the DMG, the update feed and the 398 MB source archive (97 sources, complete).
- **Checked as a download.** The public DMG matched the built one byte for byte. With a quarantine flag, Gatekeeper accepted the DMG and the app copied out of it as notarized Developer ID. `syspolicy_check distribution` passed, and so did the app's runtime check.
- **Found on the way.** The first publish attempt stopped at notarization, before anything was public: the Mac's screen had locked, and macOS doesn't release the notary credentials while it's locked. The release script now checks the notary profile before building, and the [release steps](development.md#releasing) say to keep the Mac unlocked.
- **Updated itself** to 0.2.1 on 4 November, below.

### Second release: 0.2.1 (4 November 2026)

- **Contents.** Guest tools 0.2.2: removing them now deletes the `__pycache__` folder that Python writes at run time, so nothing is left behind. The app's code is unchanged. Checked in the Ubuntu VM:
  - upgrading from 0.2.1 with the disc's installer worked;
  - a purge removed `/usr/lib/linuxvm` with no dpkg warning, and left none of the package's paths;
  - a reinstall reported 0.2.2 with the clipboard extension active.
- **Published** at [v0.2.1](https://github.com/adrianorocha-dev/linux-vm/releases/tag/v0.2.1), from commit `42b3234`, after a dry run. The feed that 0.2.0 checks served the built `appcast.xml` byte for byte, with 0.2.1 first and then 0.2.0.
- **Updated itself, with clicks.** This was the user's copy of the public 0.2.0 DMG in `/Applications`, with three VMs:
  - with Ubuntu 2 running, Check for Updates… asked "Install Linux VM 0.2.1?". Shut Down and Install shut the VM down cleanly, and QEMU exited with status 0;
  - Sparkle's window then showed 0.2.1 with its notes. Install Update and then Install and Relaunch installed and relaunched it;
  - the updated copy is 0.2.1, build 3, notarized Developer ID. It passes its runtime check, and all three VMs are still there;
  - Ubuntu 2 started again under 0.2.1, and its clipboard and audio bridges attached. Its guest tools were then updated to 0.2.2 from the new disc.
- **Fixed after.** The release script's commands inherited its stdin. A confirmation fed to the script, rather than typed, could be read by one of them before the prompt. They now read nothing.

## Steps that belong to the user

- **The EdDSA key pair.** Sparkle's `generate_keys` keeps the private key in your login keychain and prints the public key for Info.plist. Back the private key up: without it, installed copies can't be updated.
- **Making the repository public:** done on 3 November.
- **Approving each publish.**

## How the work is split

- **GPT-6.1-Sol:** the one-command runtime build, the license inventory with the build's notices check, and the release script.
- **Claude:** Sparkle in the app and all its UI, signing, integration, and verification on this Mac.

## Done means

- A clean checkout builds the runtime with one command, and then the app.
- Every component in the app and on the disc has its license and source recorded, and the build fails if one is missing.
- A copy of one release, with VMs, updates itself to the next release and keeps its VMs.
- Releases are tagged and have release notes.

All four were met on 4 November 2026.

## Decisions

Made on 3 November 2026:

- **Scope:** licenses, updates and the one-command runtime build. Help and diagnostics, a second distribution (Fedora) and upstream proposals wait.
- **Updates:** Sparkle, with releases published publicly.

Carried over:

- **Source:** not bundled with the app (2 November).

Made on 3 November 2026, later:

- **Open source.** This repository becomes public, under the MIT License for our own code. Releases are published from it, so there is no separate releases repository.
- **Source with each release.** Each release's complete corresponding source archive is attached to its GitHub release, next to the DMG. Source requests go to the repository's Issues page.
- **Privacy.** Before the repository went public, the author email in its history was rewritten to a GitHub noreply address. Home-folder paths, a location and a device identifier were removed from current and past files.

## Open

- Nothing. The releases repository and our own code's license were decided on 3 November.
