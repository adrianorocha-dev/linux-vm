# Milestone 4 plan: Fedora and KDE Plasma

Milestone 3 released the app with automatic updates ([plan](milestone-3-plan.md)). Milestone 4 makes the guest tools work on Fedora, and on KDE Plasma under both Ubuntu and Fedora. The user set its scope on 4 November 2026. It follows the proposal's [guest integration profiles](proposal.md#5-guest-integration-profiles): one common protocol, a package for each distribution and an adapter for each desktop.

## Profiles

| | GNOME | KDE Plasma |
| --- | --- | --- |
| Ubuntu | Ubuntu 26.04, GNOME 50, supported since Milestone 1 | Kubuntu 26.04, Plasma 6.6 |
| Fedora | Fedora 44 Workstation, GNOME 50 | Fedora 45 KDE Plasma Desktop, Plasma 6.7 or 6.8 (to confirm) |

Fedora 44 with KDE, and Fedora 45 Workstation with GNOME 51, wait for later. Until GNOME 51 is tested, the clipboard extension declares only GNOME 50. On Fedora 45 Workstation, the app therefore reports it as off for that GNOME version.

Test installs come from the user's `Fedora-Workstation-Live-44-1.7.aarch64.iso` and `Fedora-KDE-Desktop-Live-45-1.4.aarch64.iso`, and from a Kubuntu 26.04.1 ARM64 image. Each is checked against its project's published checksums. All testing uses throwaway VMs, and the user's Fedora VM stays untouched.

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
- **Kubuntu:** autoinstall, if Kubuntu's installer supports it. Otherwise, Ubuntu's installer with `kubuntu-desktop`.
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
- **Kubuntu:** whether an ARM64 Kubuntu image exists. If not, Ubuntu 26.04 with `kubuntu-desktop` stands in, since its packages are the same.

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

## How the work is split

- **GPT-6.1-Sol**, each part with a written contract and tests:
  - the harness's Fedora and Kubuntu installs;
  - the RPM builder;
  - the KDE clipboard backend;
  - the status changes in the guest;
  - `install.sh`.
- **Claude:** the survey, the contract, SELinux and desktop checks in the VMs, the app's UI, review, integration and the release.

## Steps that belong to the user

- Checks at the Mac: the real trackpad on KDE and on Fedora, and anything judged by eye.
- A signing key for the RPM, if Fedora requires one.
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
- **KDE on Ubuntu:** Kubuntu 26.04.
- **Test VMs:** throwaway installs only. The user's Fedora VM isn't used.

## Open

- Package signing on Fedora 45, after the survey.
