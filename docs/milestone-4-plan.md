# Milestone 4 plan: Fedora and KDE Plasma

Milestone 3 released the app with automatic updates ([plan](milestone-3-plan.md)). Milestone 4 makes the guest tools work on Fedora, and on KDE Plasma under both Ubuntu and Fedora. The user set its scope on 4 November 2026. It follows the proposal's [guest integration profiles](proposal.md#5-guest-integration-profiles): one common protocol, a package for each distribution and an adapter for each desktop.

## Profiles

| | GNOME | KDE Plasma |
| --- | --- | --- |
| Ubuntu | Ubuntu 26.04, GNOME 50, supported since Milestone 1 | Ubuntu 26.04 with Kubuntu's `kubuntu-desktop`, Plasma 6.6 |
| Fedora | Fedora 44 Workstation, GNOME 50 | Fedora 45 KDE Plasma Desktop, Plasma 6.8 |

Fedora 44 with KDE, and Fedora 45 Workstation with GNOME 51, wait for later. Until GNOME 51 is tested, the clipboard extension declares only GNOME 50. On Fedora 45 Workstation, the app therefore reports it as off for that GNOME version.

Kubuntu publishes no ARM64 image: cdimage.ubuntu.com lists only amd64 for 26.04 and 26.04.1 (checked on 4 November 2026). On a Mac, Kubuntu's desktop therefore comes from adding `kubuntu-desktop` to Ubuntu 26.04's ARM64 desktop install. GNOME stays installed beside Plasma, so the guest tools must use the integration of the session that is running.

Test installs come from the user's `Fedora-Workstation-Live-44-1.7.aarch64.iso` and `Fedora-KDE-Desktop-Live-45-1.4.aarch64.iso`, and from `test-media/ubuntu-26.04.1-desktop-arm64.iso`. Each is checked against its project's published checksums. All testing uses throwaway VMs, and the user's Fedora VM stays untouched.

## Starting state

- **Guest tools 0.2.2:** one Debian package for Ubuntu 26.04 with GNOME 50. `install.sh` runs `apt-get`, and the package depends on `gnome-shell`.
- **Already desktop-neutral:** audio (`pactl` over PipeWire), the time zone, clock recovery, the shared folder's mount and home-folder link, the udev rule and the libinput quirk.
- **GNOME only:**
  - the clipboard, through the `clipboard@linuxvm.dev` extension;
  - the touchpad defaults, through a GSettings override;
  - the status report, which sends GNOME Shell's version and the extension's state.
- **Fedora 44 Workstation** runs in the user's VM without guest tools. The user reports that most things work.
- **KDE Plasma** hasn't been tried.
- **The harness** installs only Ubuntu, unattended from its desktop image.
- **The app's** Guest Tools section shows "GNOME" with its version, and the extension's state.

## Workstreams

### 1. Test installs without anyone at the Mac

The survey and every later check need fresh VMs. So the harness first learns to install each new profile unattended, with a test user, automatic login, passwordless sudo and SSH, like its Ubuntu install.

- **Fedora:** a kickstart, if the live images accept one. Otherwise, Fedora's network installer with the Workstation or KDE environment group.
- **Ubuntu with Plasma:** the existing Ubuntu install, then `kubuntu-desktop`, with Plasma's Wayland session logging in automatically.
- **Session checks:** each desktop gets its own, as GNOME has today.

### 2. Survey, before guest-tools code

On a fresh VM of each new profile, without guest tools, check what [What needs the guest tools](what-needs-guest-tools.md) lists for Ubuntu:

- rendering through VirGL, the refresh rate and scale, and following window resizes and full screen;
- the guest's cursor;
- touchpad scrolling (direction, tap to click, scrolling right after typing), pinch and swipe navigation;
- sound, network and Mac sleep;
- a shared folder mounted by hand.

Also check:

- **KDE:**
  - whether KWin offers Wayland's data-control protocol to ordinary clients, so `wl-paste --watch` and `wl-copy` work without a window;
  - where Plasma takes a system-wide touchpad default for the virtual touchpad that user settings still override;
  - whether Plasma's clock follows a step of the system clock;
  - whether the `LINUXVM-TOOLS` disc appears and mounts in Dolphin.
- **Fedora:**
  - SELinux with the 9p shared folder, the root services and the virtio ports;
  - whether Fedora's own GSettings overrides outrank ours;
  - whether Fedora 45's RPM accepts an unsigned local package from `dnf install`;
  - which time service runs, for clock recovery.
- **Ubuntu with Plasma:** which login manager runs after `kubuntu-desktop` is installed, and whether the GNOME and Plasma sessions each keep their own settings.

The results go into `what-needs-guest-tools.md`, one section per profile. Checks with the real trackpad and by eye need the user.

### 3. The contract first

`host-guest-contract.md` changes before the code:

- **Status:** new keys:
  - `desktop`: `GNOME`, `KDE`, or the session's own name for another desktop;
  - `desktopVersion`;
  - `clipboard`: the clipboard's state, on any desktop.

  GNOME guests keep sending `shell` and `extension`, so 0.2 apps still read them.
- **Delivery:** the disc carries a `.deb` and an `.rpm` of the same version. `install.sh` picks one by the system's package manager.
- **Shared folder:** its files belong to uid and gid 1000, the first user on both Ubuntu and Fedora.

### 4. Guest tools 0.3.0

- **Two packages from one tree:** `linuxvm-guest` as a `.deb` and as a `noarch` `.rpm`, with the same files, version and behavior.
  - Both are built on the Mac with Python's standard library, and are reproducible byte for byte, as the `.deb` is today.
  - The RPM's scriptlets do what `postinst`, `prerm` and `postrm` do, following RPM's upgrade order and arguments.
- **Dependencies name no desktop:** Python 3 with GObject, `pactl` and systemd. `wl-clipboard` is recommended, for KDE. The `gnome-shell` dependency goes.
- **Clipboard on KDE:** a backend modeled on Try Omarchy's `omarchy-native-clipboard-bridge`, which uses `wl-paste --watch` and `wl-copy`. It keeps today's size limits and echo suppression. The agent picks the extension or this backend from the session. On GNOME, nothing changes.
- **Touchpad defaults on KDE:** natural scrolling on, with tap to click and disable while typing off. They apply to the virtual touchpad only, set where the survey finds.
- **Fedora specifics:** whatever the survey finds about SELinux, overrides and package signing. If Fedora 45 requires signed packages, the user chooses between a project signing key and an explicitly unsigned install.
- **`install.sh`** uses `apt-get` or `dnf`. On any other system, it names the supported ones.

### 5. The app

- The Guest Tools section shows the desktop and its version, and the clipboard's state on either desktop. GNOME's "off for this GNOME version" stays.
- Wherever the app and the disc say Ubuntu but mean Linux, they say Linux. The install steps say to open the disc in Files or Dolphin.
- The README's [Distributions](../README.md#distributions) lists the four profiles once they pass.

### 6. Release

Guest tools 0.3.0 ship on the disc of app 0.3.0, which is released the way 0.2.1 was. An Ubuntu VM with 0.2.2 updates from the new disc.

## Progress

### Unattended Fedora installs (4–5 November 2026)

- **The live images ignore a kickstart.** Anaconda reads `--kickstart` only outside live mode (`if options.ksfile and not options.liveinst`).
- **What works instead:**
  - GRUB's entry gets three extra kernel arguments: `console=ttyAMA0`, `systemd.wants=sshd.service` and the systemd credential `ssh.authorized_keys.root`, which carries a throwaway key. The live session then accepts root SSH within 35 seconds.
  - Over SSH, a non-live `anaconda --cmdline --kickstart` installs with `liveimg --url=file:///run/initramfs/live/LiveOS/squashfs.img`. So the installed system has exactly the image's packages, and nothing is downloaded.
  - The kickstart names the disk (`ignoredisk --only-use=vda`). Its `%post` sets passwordless sudo and automatic login through GDM or `plasmalogin`, and powers off.
  - A Fedora 45 KDE install took about 6 minutes.
- **KDE's first-run wizard.** On Fedora 45 KDE, `plasma-setup.service` logs in as a `plasma-setup` user instead, unless `/etc/plasma-setup-done` exists. The kickstart creates that file.
- **In the harness.** GPT-6.1-Sol turned these steps into a Fedora profile of `scripts/harness/fresh-install`, chosen from the image's name or `--profile fedora`. Its session checks follow the desktop: GNOME's extension, or KDE's clipboard state. Claude reviewed and merged it, with two fixes. The harness kept every poll's copy of Anaconda's logs, and now keeps only the latest. It also failed a good Fedora 44 install, on Anaconda's harmless "ERR … setting console font" line; now only a `CmdlineError`, a traceback, or an exit without power-off count as failure.
- **Ubuntu with Plasma** isn't a harness profile yet. Its test VM was the harness's Ubuntu install with `kubuntu-desktop` added by hand. The `shared/default-x-display-manager` answer kept GDM, and AccountsService set the user's session to `plasma`.

### Survey (4–5 November 2026)

- **Fedora 44 Workstation:**
  - **Desktop:** GNOME Shell 50.0 on Wayland, kernel 6.19.10, SELinux enforcing.
  - **Display:** in a window, 2240×1260 at 120 Hz, with GNOME picking a 1.67 scale by itself.
  - **Sound and time:** PipeWire works with the VM's audio device, and chronyd keeps time.
  - **Disc:** it mounts by itself.
  - **Touchpad:** Fedora's defaults are tap to click on, natural scrolling on, disable while typing on. No Fedora settings override touches the touchpad keys, so ours applies.
  - **Clipboard tools:** `wl-clipboard` is installed, but GNOME offers no data-control protocol.
- **Fedora 45 KDE:**
  - **Desktop:** Plasma and KWin 6.8.1, kernel 7.2.11, systemd 262, RPM 6.1 with verify level `all`.
  - **Wayland socket:** `wayland-1`, not `wayland-0`.
  - **Clipboard:** KWin offers `ext_data_control_manager_v1` but not the wlr protocol. `wl-copy` and `wl-paste` 2.3.0 work without a window.
  - **Touchpad:** KDE's defaults are tap to click on, natural scrolling off, disable while typing on. A system-wide `/etc/xdg/kcminputrc` group, `[Libinput][1575][4][QEMU Virtio Pinch Touchpad]`, changes them, and `~/.config/kcminputrc` still takes precedence.
  - **Disc:** it doesn't mount by itself. Dolphin mounts it when it's clicked.
  - **Power button:** it opens Plasma's logout prompt, which waits for a click and gave up after 5 minutes. So the app's Shut Down never finishes, and neither does Shut Down and Install. With `/etc/xdg/powerdevilrc` set to `PowerButtonAction=8`, the VM shut down 8 seconds after the button.
- **Ubuntu 26.04 archive:** wl-clipboard 2.2.1, which predates ext-data-control, and KWin 6.6.6. So the guest tools speak data-control themselves instead of depending on wl-clipboard.
- **Ubuntu 26.04 with `kubuntu-desktop`:**
  - **Desktop:** Plasma and KWin 6.6.6 on Wayland at `wayland-0`, through GDM. GNOME's session stays available.
  - **Clipboard:** KWin 6.6.6 also offers only `ext_data_control_manager_v1`.
  - **Config:** `XDG_CONFIG_DIRS` includes `/etc/xdg`, so the KDE defaults apply here too.
  - **Disc:** it doesn't mount by itself.
  - **Plasma's version:** `plasmashell --version` segfaults, even with `QT_QPA_PLATFORM=offscreen`, while `kwin_wayland --version` works.

### Guest tools 0.3.0 (4–5 November 2026)

- **Packages.** The `.deb` and the `noarch` `.rpm` hold the same files, and the disc carries both. GPT-6.1-Sol built the RPM writer, and Claude reviewed and merged it.
- **Fixes at merge:**
  - the RPM co-owns `/usr/share/gnome-shell` and its `extensions` folder, which nothing else owns on KDE;
  - removal deletes `/mnt/mac`;
  - the copyright file is marked as documentation.
- **Fedora 44 Workstation**, from the disc's `install.sh`, everything checked:
  - the unsigned RPM installs with dnf;
  - `rpm -K` passes the header and payload SHA-256 checks, and `rpm -V` passes;
  - rpmlint reports only policy and style;
  - the Mac received the status report: 0.3.0, Fedora 44, GNOME 50.0, extension active;
  - the touchpad defaults apply;
  - the clipboard carries text and a PNG both ways, byte for byte;
  - the Mac's audio devices appear;
  - the time zone follows the Mac;
  - the shared folder reads and writes, with no SELinux denials;
  - after 40 seconds of simulated Mac sleep, the clock steps forward;
  - an RPM upgrade keeps the services enabled and running;
  - removal leaves nothing behind.
- **Fedora 45 KDE:** the unsigned RPM installs too, despite verify level `all`. dnf only warns that it "skipped OpenPGP checks for 1 package from repository: @commandline". Audio, the time zone, the shared folder, clock recovery and the status report work. The clipboard agent crashes, because its GNOME path asks for GNOME Shell's settings schema; the data-control backend replaces that path.
- **KDE defaults.** The packages now carry `/etc/xdg/kcminputrc` (the touchpad) and `/etc/xdg/powerdevilrc` (the power button). Neither is marked as a user-editable config file, so upgrades replace them and removal deletes them.
- **The clipboard on KDE.** GPT-6.1-Sol wrote `wayland_clipboard.py`, a data-control client using only Python's standard library, and the desktop-neutral status keys. Claude reviewed it in real KWin and fixed four things:
  - KWin 6.8.1 sent `cancelled` twice for the agent's own source. The agent destroyed it twice and crashed with "invalid object 8".
  - The agent forwarded the clipboard that Linux held when it started. Plasma restores that at login, so every login would have replaced the Mac's clipboard.
  - Early in a login, a missing `WAYLAND_DISPLAY` was saved as an error, so the app would briefly have shown "Failed to start".
  - Plasma's version came from `plasmashell --version`, which crashes on Ubuntu; it now comes from KWin.
- **Fedora 45 KDE:** the clipboard carries text both ways twice, and a PNG both ways byte for byte. The Mac received the status report: KDE, 6.8.1, clipboard active. Removal leaves nothing of ours. `/usr/share/gnome-shell` stays because Firefox's search provider lives in it.
- **Ubuntu 26.04 with Plasma:**
  - the clipboard carries text both ways;
  - the touchpad defaults apply;
  - the power button shut the VM down in 6 seconds;
  - the Mac received the status report: KDE, 6.6.6, clipboard active.
- **Ubuntu 26.04 with GNOME, on the final 0.3.0:**
  - the extension is active, and the clipboard carries text both ways;
  - the touchpad defaults apply;
  - the Mac received the status report: GNOME 50.1, with `shell` and `extension` still there for older apps;
  - `apt purge` leaves nothing behind.

  Ubuntu's harness install also passed with 0.3.0.
- **The app** shows each VM's desktop ("KDE Plasma 6.8.1") and its clipboard state, from the new keys, or from the extension's state for 0.2 guests. Checked with window snapshots of made-up reports and in `linuxvmctl status`.
- **Removal leftovers fixed on the way:** an empty `~/.local/state/linuxvm`, and the clipboard state under `/run/user/<uid>/linuxvm`.

## How the work is split

- **GPT-6.1-Sol**, each part with a written contract and tests:
  - the harness's Fedora installs, and Plasma on its Ubuntu install;
  - the RPM builder;
  - the KDE clipboard backend;
  - the status changes in the guest;
  - `install.sh`.
- **Claude:** the survey, the contract, SELinux and desktop checks in the VMs, the app's UI, review, integration and the release.

## Steps that belong to the user

- Checks at the Mac: the real trackpad on KDE and on Fedora, and anything judged by eye.
- Approving the publish.

## Done means

- **Every profile works.** On a fresh VM of each of the four, the disc's `install.sh` installs the guest tools. After logging out and back in, these all work:
  - clipboard text and images, both ways;
  - audio devices;
  - the time zone, and the clock after Mac sleep;
  - the shared folder;
  - the touchpad defaults;
  - the status report.

  Removing the guest tools leaves nothing behind.
- **Unattended.** The harness installs each profile and runs these checks on its own.
- **In the app.** It shows each VM's desktop and whether its clipboard works.
- **Documented.** `what-needs-guest-tools.md` and the README cover all four profiles.
- **Released.** App 0.3.0 ships with guest tools 0.3.0, and a VM with guest tools 0.2.2 updates from its disc.

## Decisions

Made on 4 November 2026:

- **Scope:** Fedora with GNOME, and KDE Plasma on Ubuntu and Fedora.
- **Fedora:** Fedora 44 Workstation and Fedora 45 KDE, from the user's images. Fedora 44 with KDE and Fedora 45 Workstation wait.
- **KDE on Ubuntu:** Kubuntu 26.04's desktop. Kubuntu has no ARM64 image, so tests add `kubuntu-desktop` to Ubuntu 26.04's ARM64 install (user's note, confirmed on cdimage.ubuntu.com).
- **Test VMs:** throwaway installs only. The user's Fedora VM isn't used.

Made on 5 November 2026:

- **No package signing.** dnf installs the disc's unsigned local RPM on Fedora 44 and 45, with a warning.

## Open

- Nothing.
