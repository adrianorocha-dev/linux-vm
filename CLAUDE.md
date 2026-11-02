# Working on Linux VM

Read `README.md` for the layout, then `docs/milestone-2-plan.md` for the current milestone. `docs/proposal.md` holds the investigation and the Milestone 0 and 1 results.

## Build and test

- Build the app: `scripts/build-app.sh`. It ends with the runtime capability check. To install, copy `build/Linux VM.app` over `/Applications/Linux VM.app` while the app is quit.
- Run the tests: `swift test --package-path macos` and `/opt/homebrew/bin/python3.14 -m unittest discover guest/tests`.
- Rebuild the guest tools: `python3 guest/build.py` and `guest/build-tools-iso.sh`. Then rebuild the app, which bundles the disc.
- The QEMU runtime and its inputs live in git-ignored `.deps/` ([runtime/README.md](runtime/README.md)).

## Verifying on this Mac

- **Screenshots:** QMP `screendump` is black under VirGL. Check the guest from inside instead: `scripts/ssh-vm.sh 2222 …` for the imported "Ubuntu" VM, plus `scripts/guest-diagnostics.sh`.
- **App UI:** check it with the app's own window snapshots: `LINUXVM_SNAPSHOT=/tmp/prefix` with `LINUXVM_SNAPSHOT_TAB`, `LINUXVM_SNAPSHOT_SHEET` and `LINUXVM_SNAPSHOT_HEIGHT`. The agent has no Screen Recording or Accessibility permission.
- **Typing into a VM:** use `scripts/qmp-type.py`.
- **Host resources:** this Mac has 16 GB. Do not run two 8 GB VMs at once.
- **Test VMs:** shut them down and delete them when you are done. Never modify the user's UTM VMs.

## Working agreement

- Delegate well-defined, non-UI modules to GPT-6.1-Sol (T3 `delegate_task`, Codex provider) with a written contract and tests. Never delegate UI work. Review its output before integrating.
- Host–guest interfaces live in `docs/host-guest-contract.md`. Change the contract first.
- Commit at sensible checkpoints on `main`. The remote is the private `adrianorocha-dev/linux-vm`.
