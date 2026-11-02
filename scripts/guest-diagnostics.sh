#!/bin/bash
# Milestone 0 objective checks, run inside the guest as the desktop user:
#   scripts/ssh-vm.sh 2222 bash -s < scripts/guest-diagnostics.sh

section() { printf '\n== %s ==\n' "$1"; }

section 'System'
. /etc/os-release && echo "$PRETTY_NAME"
uname -r
gnome-shell --version 2>/dev/null
dpkg-query -W -f='${Package} ${Version}\n' mutter-common libinput10 libmutter-18-0 2>/dev/null
loginctl list-sessions --no-legend
for s in $(loginctl list-sessions --no-legend | awk '{print $1}'); do
  loginctl show-session "$s" -p Type -p Name -p State -p Desktop
done

section 'GPU and EDID'
ls /sys/class/drm
for c in /sys/class/drm/card*-*; do
  [[ -f $c/status ]] || continue
  echo "$c: $(cat "$c/status") modes: $(head -3 "$c/modes" | tr '\n' ' ')"
  [[ -s $c/edid ]] && edid-decode "$c/edid" 2>/dev/null | grep -E 'Maximum image size|DTD 1|Detailed mode|Hz' | head -8
done
cat /proc/cmdline

section 'Mutter renderer and monitor mode'
journalctl -b --user -o cat 2>/dev/null | grep -i -E 'renderer|GL_RENDERER|virgl|hardware cursor|cursor' | tail -10
gdbus call --session --dest org.gnome.Mutter.DisplayConfig --object-path /org/gnome/Mutter/DisplayConfig \
  --method org.gnome.Mutter.DisplayConfig.GetCurrentState 2>/dev/null |
  grep -o -E "'[0-9]+x[0-9]+@[0-9.]+'|is-current': <true>|'scale': <[0-9.]+>|[0-9]+\.[0-9]+, \[[0-9., ]+\], \{'is-current" | head -10

section 'Cursor plane'
if command -v drm_info >/dev/null; then
  sudo drm_info 2>/dev/null | grep -E -A6 'type: CURSOR|Plane [0-9]+' | grep -E 'Plane|type|CRTC|FB|SRC|CRTC_[XYWH]' | head -30
fi

section 'Input devices'
sudo libinput list-devices 2>/dev/null | grep -E '^Device|^Capabilities|^Tap-to-click|^Nat.scrolling|^Disable-w-typing|^Scroll methods|^Click methods'
echo
sudo libinput quirks list /dev/input/event* 2>/dev/null | sort -u
for e in /dev/input/event*; do
  n=$(cat "/sys/class/input/${e##*/}/device/name" 2>/dev/null)
  [[ $n == *Pinch* ]] && { echo "$e $n"; sudo libinput quirks list "$e"; }
done

section 'GNOME touchpad settings'
for k in tap-to-click disable-while-typing natural-scroll send-events speed; do
  echo "$k=$(gsettings get org.gnome.desktop.peripherals.touchpad "$k")"
done

section 'Apps'
command -v firefox chromium loupe papers eog evince ptyxis gnome-terminal 2>/dev/null
snap list 2>/dev/null | awk 'NR > 1 {print $1, $2}'
