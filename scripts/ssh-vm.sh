#!/bin/bash
# Test harness: runs a command in a VM over a forwarded SSH port, as the user
# whose authorized key is test-media/ssh/id_ed25519.
#   scripts/ssh-vm.sh PORT [command...]     (the imported Ubuntu VM uses 2222)
root=$(cd "$(dirname "$0")/.." && pwd -P)
port=${1:?usage: ssh-vm.sh PORT [command]}
shift
exec ssh -q -i "$root/test-media/ssh/id_ed25519" -p "$port" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=5 -o BatchMode=yes tester@127.0.0.1 "$@"
