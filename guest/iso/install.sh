#!/bin/sh
set -eu
cd -- "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
set -- ./linuxvm-guest_*_all.deb
[ "$#" -eq 1 ] && [ -f "$1" ] || { echo 'Expected exactly one linuxvm-guest Debian package on this disc.' >&2; exit 1; }
deb=$1
set -- ./linuxvm-guest-*.noarch.rpm
[ "$#" -eq 1 ] && [ -f "$1" ] || { echo 'Expected exactly one linuxvm-guest RPM package on this disc.' >&2; exit 1; }
rpm=$1
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y "$deb"
elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y "$rpm"
else
    echo 'LinuxVM guest tools support Ubuntu and Fedora.' >&2
    exit 1
fi
printf '\nLog out and back in to start the shared clipboard and the other guest services.\n'
