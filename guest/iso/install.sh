#!/bin/sh
set -eu
cd -- "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
sudo apt-get install -y ./linuxvm-guest_0.1.0_all.deb
printf '\nLog out of Ubuntu and back in to load the clipboard extension and guest services.\n'
