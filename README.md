# Linux VM

Linux VM is a Mac app for running Linux on Apple Silicon. It aims to make Linux feel at home on a Mac. Trackpad scrolling follows your fingers smoothly, Linux runs at your display's refresh rate and Retina resolution, and you see Linux's own pointer.

All of this has been tested and tuned with Ubuntu 26.04 and Fedora, on GNOME and on KDE Plasma. Other ARM64 distributions can run too; see [Distributions](#distributions).

**[Download Linux VM](https://github.com/adrianorocha-dev/linux-vm/releases/latest)**. It needs an Apple Silicon Mac with macOS 15 or later.

## The idea

On a Mac, the trackpad is how you get around, so that's where Linux VM starts. It presents your trackpad to Linux as a touchpad, so Linux sees two fingers moving, as it would on a laptop. Scrolling follows your fingers, pinch to zoom works, and so do two-finger swipes back and forward in browsers.

This approach, and the patched QEMU runtime that makes it work, come from [Try Omarchy](https://github.com/omacom/try-omarchy). Linux VM builds on that work with its own Mac app, VM management and Linux integration.

## What you get

- **Trackpad.** Smooth two-finger scrolling, pinch to zoom, and swipes back and forward in browsers. Each VM has its own scroll speed setting. Mice and their scroll wheels work too.
- **Display.** Accelerated 3D graphics, so WebGL works in browsers. Linux uses your display's refresh rate, up to 120 Hz on ProMotion displays. In full screen, Linux sees the display's full resolution and size, so a desktop such as GNOME picks a Retina scale by itself. Full screen can also hide the menu bar and Dock and use the area beside the camera.
- **Pointer.** Linux's own cursor shapes, such as the text cursor and resize arrows, with no Mac arrow drawn on top.
- **Sound.** Linux plays through your Mac's speakers or headphones and records from its microphone. macOS asks once for permission to use the microphone.
- **Network.** Linux reaches the internet through your Mac. You can forward a port on your Mac to Linux, for example to SSH into it.
- **Sleep.** The VM pauses while your Mac sleeps and carries on when it wakes.
- **Runs in the background.** VMs keep running when you quit the app. Open the app again to shut them down.
- **Updates.** The app updates itself, and never while a VM is running.

### With the guest tools

The guest tools are an optional package you install inside Linux, from a disc the app provides. They're made for Ubuntu 26.04 and Fedora, with GNOME or KDE Plasma; see [Distributions](#distributions). They add:

- a shared clipboard for text and images, both ways;
- a Mac folder shared with Linux;
- Linux following your Mac's time zone;
- Linux setting its clock right as soon as your Mac wakes;
- each Mac speaker and microphone listed in Linux's sound settings;
- the guest tools' version and status on the VM's page in the app.

[What needs the guest tools](docs/what-needs-guest-tools.md) has the details, including what happens without them.

## Distributions

Linux VM runs ARM64 Linux. Getting the details right takes testing and tuning for each distribution, one at a time.

These are fully supported. Everything on this page has been tested with them, and the guest tools are made for them:

| | GNOME | KDE Plasma |
| --- | --- | --- |
| **Ubuntu** | Ubuntu 26.04 Desktop | Ubuntu 26.04 Desktop with Kubuntu's desktop |
| **Fedora** | Fedora 44 Workstation | Fedora 45 KDE Plasma Desktop |

- **KDE Plasma on Ubuntu.** Kubuntu has no ARM64 installer. Install Ubuntu Desktop, then run `sudo apt install kubuntu-desktop` and choose Plasma when you log in.
- **Fedora 45 Workstation**, with GNOME 51, hasn't been tested yet. The guest tools' shared clipboard doesn't support GNOME 51 yet, so it stays off there.
- **Other ARM64 distributions** should work with everything that comes from the VM's virtual hardware: the display, trackpad, pointer, sound, network and sleep ([details](docs/what-needs-guest-tools.md#works-without-the-guest-tools)). They haven't been tested yet, and the guest tools don't support them yet. You can still [mount a shared folder by hand](docs/what-needs-guest-tools.md#needs-the-guest-tools).

## What you need

- An Apple Silicon Mac (M1 or later) with macOS 15 Sequoia or later. Intel Macs aren't supported.
- An ARM64 Linux installer image. For the best result, use one of the [fully supported distributions](#distributions):
  - **Ubuntu:** on [ubuntu.com/download/desktop](https://ubuntu.com/download/desktop), choose "Download Ubuntu 26.04.1 arm64" to get `ubuntu-26.04.1-desktop-arm64.iso`. Ubuntu 26.10 hasn't been tested.
  - **Fedora KDE Plasma Desktop 45:** on [fedoraproject.org/kde/download](https://fedoraproject.org/kde/download), download the aarch64 Live ISO, `Fedora-KDE-Desktop-Live-45-1.4.aarch64.iso`.
  - **Fedora Workstation 44:** download `Fedora-Workstation-Live-44-1.7.aarch64.iso` from [Fedora 44's release folder](https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Workstation/aarch64/iso/), with its `CHECKSUM` file. Fedora's Workstation download page now offers Fedora 45, which hasn't been tested yet.
- Memory and disk space for the VM. The app suggests 8 GB of memory on a Mac with 16 GB or more, and 4 GB otherwise. The VM's disk takes space on your Mac only as Linux writes to it.

## Getting started

1. **Install the app.** Download `LinuxVM-<version>.dmg` from [Releases](https://github.com/adrianorocha-dev/linux-vm/releases/latest), open it, and drag Linux VM to Applications. The app is signed and notarized by Apple, so it opens like any other app. On its second launch, it asks whether to check for updates automatically.
2. **Create a VM.** Choose File → New Virtual Machine…, then pick the installer image, the number of CPUs, the memory and the disk size. Leave "Start the installer now" on and click Create.
3. **Install Linux.** Linux opens in its own window. Install it as you would on a PC.
4. **Eject the installer.** When the installer restarts the VM, click Eject under Installer Disc on the VM's page in the app, so the VM starts from its own disk. Ubuntu asks for this: when it says to remove the installation medium, click Eject, then press Return in the VM.
5. **Install the guest tools.** Open the `LINUXVM-TOOLS` disc in Linux's file manager: Files in GNOME, or Dolphin in KDE Plasma, where you click the disc to open it. Open a terminal in that folder and run `sh install.sh`. It asks for your password. Then log out and back in.
6. **Go full screen.** Click the window's green button. Linux matches the display's resolution and refresh rate.

### Already have a Linux VM?

File → Import Disk… brings in an existing ARM64 Linux disk, in raw or QCOW2 format, such as one made with another VM app. You can also add its UEFI variables file. The app works on its own copy. On APFS, that copy takes no extra space until one of them changes. Don't import a disk while another app is running it.

## Using it

Each VM's page in the app shows its settings:

- **Resources:** CPUs and memory. You can also enlarge the disk; afterwards, grow the partition inside Linux (in Ubuntu, with the Disks app).
- **Installer Disc:** insert or eject an installer image, even while the VM runs.
- **Sharing:** a Mac folder to share with Linux. With the guest tools, it appears at `/mnt/mac`, with a link in your home folder.
- **Display and Trackpad:** scroll speed, whether full screen hides the menu bar and Dock, whether it uses the area beside the camera, and whether to show the Mac pointer.
- **Sleep:** whether the VM pauses while your Mac sleeps.
- **Network:** port forwards from your Mac to Linux.

Shut down the VM to change its resources, sharing or network. The Logs tab shows what the VM and its helpers have reported.

**Shutting down.** Shut Down asks Linux to shut down, like pressing a power button. In KDE Plasma this needs the guest tools: without them, Plasma shows a logout prompt in the VM instead. Force Stop stops the VM at once, and anything unsaved in Linux is lost. You can also shut down from inside Linux.

**Updates.** Choose Linux VM → Check for Updates… to check now. If an update arrives while a VM is running, an Update button appears in the window. Click it to shut down your VMs and install.

**Where VMs are kept.** Each VM is a folder in `~/Library/Application Support/Linux VM/VMs/`, holding its disk, settings and logs. Deleting a VM in the app moves its folder to the Trash.

**External drives.** While a VM runs, macOS won't eject a drive holding its shared folder. Ejecting a drive that holds its installer image ejects the disc from the VM first. If the drive is unplugged without ejecting, the VM keeps running without the folder or disc.

## Command line

The app includes `linuxvmctl`, at `/Applications/Linux VM.app/Contents/Helpers/linuxvmctl`, for managing VMs from Terminal:

```
linuxvmctl list                       VMs and their state
linuxvmctl check                      runtime capability report
linuxvmctl create --name N [--iso PATH] [--cpus N] [--memory MIB] [--disk GIB]
linuxvmctl import --name N --disk PATH [--efi-vars PATH] [--cpus N] [--memory MIB]
linuxvmctl show VM                    configuration as JSON
linuxvmctl set VM [--name N] [--cpus N] [--memory MIB] [--iso PATH|none]
                  [--shared-folder PATH|none] [--scroll-scale X] [--mac-cursor on|off]
                  [--immersive on|off] [--cover-notch on|off] [--forward HOST:GUEST|none]
                  [--grow-disk GIB] [--pause-during-sleep on|off]
linuxvmctl start VM                   start in the background
linuxvmctl stop VM [--force]          shut down (or stop at once)
linuxvmctl status VM                  state, and the guest tools version
linuxvmctl insert VM PATH | eject VM  change the installer disc while running
linuxvmctl screenshot VM PATH         save the display as PNG
linuxvmctl delete VM                  move a stopped VM to the Trash
```

`VM` is a name, an identifier, or a unique prefix of an identifier.

## Limitations

Linux VM is early software, at version 0.3. So far it has been developed and tested on one MacBook Pro.

- **ARM64 Linux only.** It can't run x86 Linux or Windows.
- **Distributions.** Only the four combinations of Ubuntu or Fedora with GNOME or KDE Plasma under [Distributions](#distributions) are fully supported so far.
- **Display.** Testing has focused on full screen on the Mac's built-in display. Resizing the window and moving to an external display haven't been tested yet.
- **WebGPU** isn't available in Linux browsers. WebGL works.

## How it works

Linux VM runs Linux with QEMU, using Apple's Hypervisor framework, so Linux runs natively on the Mac's processor. Graphics go through virglrenderer to the Mac's GPU. The runtime is Try Omarchy's patched QEMU, with a few changes of our own ([runtime/README.md](runtime/README.md)). It turns trackpad gestures into touches on a virtual touchpad, and tells Linux about the display's refresh rate and scale. Each VM runs under a small supervisor process, which is why VMs keep running when the app quits.

## Credits

Linux VM is built on the work of these open-source projects:

- [Try Omarchy](https://github.com/omacom/try-omarchy): the trackpad, display and full-screen work in its QEMU runtime, and the helper behind the shared clipboard and sound devices.
- [QEMU](https://www.qemu.org): the virtual machine itself.
- [virglrenderer](https://gitlab.freedesktop.org/virgl/virglrenderer): accelerated 3D graphics.
- [Sparkle](https://sparkle-project.org): updates.

Help → Third-Party Licenses lists everything the app includes.

## Feedback

Report problems and ask questions on the [Issues page](https://github.com/adrianorocha-dev/linux-vm/issues).

## Building from source

[docs/development.md](docs/development.md) covers the repository's layout, building the app and its QEMU runtime, the tests, and making releases. The rest of [docs/](docs/) records how the project got here: the investigation, the milestone plans and their measurements.

## License

Linux VM's own code is available under the [MIT License](LICENSE). The app includes open-source software under other licenses, such as QEMU under GPLv2. Help → Third-Party Licenses lists it all, and each [release](https://github.com/adrianorocha-dev/linux-vm/releases) includes its complete source.
