#!/bin/sh
set -eu
cd -- "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
set -- ./linuxvm-guest_*_all.deb
[ "$#" -eq 1 ] && [ -f "$1" ] || { echo 'Expected exactly one linuxvm-guest package on this disc.' >&2; exit 1; }
sudo apt-get install -y "$1"
printf '\nLog out of Ubuntu and back in to load the clipboard extension and guest services.\n'
