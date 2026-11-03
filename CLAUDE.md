# Working on Linux VM

Read `README.md` for what the app does and `docs/development.md` for the layout, building and releasing, then `docs/milestone-3-plan.md` for the current milestone. `docs/milestone-2-plan.md` records Milestone 2 (closed), `docs/future-tests.md` the checks it left for later, and `docs/proposal.md` the investigation and the Milestone 0 and 1 results.

## Build and test

- Build the QEMU runtime: `scripts/build-runtime.sh`.
- Build the app: `scripts/build-app.sh`. It ends with the runtime capability check. To install, copy `build/Linux VM.app` over `/Applications/Linux VM.app` while the app is quit.
- Build to share: [Sharing the app](docs/development.md#sharing-the-app). Creating certificates and notary credentials is the user's step; never handle their passwords.
- Run the tests: `swift test --package-path macos` and `/opt/homebrew/bin/python3.14 -m unittest discover guest/tests`, `python3 -m unittest discover scripts/harness/tests`, and `python3 -m unittest discover scripts/tests`. The last command clones the pinned Try Omarchy source if absent. It does not build it.
- Rebuild the guest tools: `python3 guest/build.py` and `guest/build-tools-iso.sh`. Then rebuild the app, which bundles the disc.
- The QEMU runtime and its inputs live in git-ignored `.deps/` ([runtime/README.md](runtime/README.md)).
- Bundle provenance and license texts live in `licenses/`. Update the manifest when bundle paths or third-party inputs change. Original app and Guest Tools versions come from their source files. See [licenses/README.md](licenses/README.md).

## Verifying on this Mac

- **Screenshots:** QMP `screendump` is black under VirGL. Check the guest from inside instead: `scripts/ssh-vm.sh 2222 …` for the imported "Ubuntu" VM, plus `scripts/guest-diagnostics.sh`.
- **App UI:** check it with the app's own window snapshots: `LINUXVM_SNAPSHOT=/tmp/prefix` with `LINUXVM_SNAPSHOT_TAB`, `LINUXVM_SNAPSHOT_SHEET`, `LINUXVM_SNAPSHOT_HEIGHT` and `LINUXVM_SNAPSHOT_SCROLL=end`. Point `LINUXVM_LIBRARY` and `LINUXVM_CONTENTS` at a throwaway folder to show made-up VMs and reports. The agent has no Screen Recording or Accessibility permission.
- **Mac sleep without sleeping:** start the supervisor with `LINUXVM_DEBUG_SLEEP_SIGNALS=1`; then SIGUSR1 simulates the Mac going to sleep and SIGUSR2 its wake.
- **Other QEMU accelerator options:** `LINUXVM_DEBUG_QEMU_ACCEL=hvf,kernel-irqchip=off` on `linuxvmctl start` replaces `-accel hvf`, for example to compare QEMU's own interrupt controller with the macOS one.
- **Presentation timing:** measure with the VM window in front and the Mac awake. Another app in front can change the result, and with the display off it is always bad. Turn off the guest's screen blanking first (`gsettings set org.gnome.desktop.session idle-delay 0`), or runs after five idle minutes record nothing.
- **Typing into a VM:** use `scripts/qmp-type.py`.
- **Host resources:** this Mac has 16 GB. Do not run two 8 GB VMs at once.
- **Test VMs:** shut them down and delete them when you are done. Never modify the user's UTM VMs.

## Working agreement

- Delegate well-defined, non-UI modules to GPT-6.1-Sol (T3 `delegate_task`, Codex provider) with a written contract and tests. Never delegate UI work. Review its output before integrating.
- Host–guest interfaces live in `docs/host-guest-contract.md`. Change the contract first.
- Commit at sensible checkpoints on `main`. The remote is the public `adrianorocha-dev/linux-vm`. Keep personal details out of the repository: no email addresses, home-folder paths, locations or device identifiers.
