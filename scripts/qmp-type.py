#!/usr/bin/env python3
"""Test harness: types into a running VM through its QMP control socket.

    scripts/qmp-type.py VM-ID keys e down down end
    scripts/qmp-type.py VM-ID text ' autoinstall'
    scripts/qmp-type.py VM-ID keys ctrl-x

Key names are QEMU qcodes; combine modifiers with '-' (ctrl-x, shift-a).
"""

import json
import os
import socket
import sys
import time

SHIFTED = {
    '~': 'grave_accent', '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8',
    '(': '9', ')': '0', '_': 'minus', '+': 'equal', '{': 'bracket_left', '}': 'bracket_right', '|': 'backslash',
    ':': 'semicolon', '"': 'apostrophe', '<': 'comma', '>': 'dot', '?': 'slash',
}
PLAIN = {
    ' ': 'spc', '-': 'minus', '=': 'equal', '[': 'bracket_left', ']': 'bracket_right', '\\': 'backslash',
    ';': 'semicolon', "'": 'apostrophe', ',': 'comma', '.': 'dot', '/': 'slash', '`': 'grave_accent', '\n': 'ret',
}


def control_socket(vm_id):
    root = os.path.expanduser('~/Library/Application Support/Linux VM/VMs')
    with open(os.path.join(root, vm_id, 'run.json')) as handle:
        return json.load(handle)['controlSocket']


def qmp(path):
    connection = socket.socket(socket.AF_UNIX)
    connection.connect(path)
    stream = connection.makefile('rw')
    stream.readline()

    def execute(command, **arguments):
        stream.write(json.dumps({'execute': command, 'arguments': arguments}) + '\n')
        stream.flush()
        while True:
            reply = json.loads(stream.readline())
            if 'return' in reply or 'error' in reply:
                if 'error' in reply:
                    raise SystemExit(f"{command}: {reply['error']['desc']}")
                return reply['return']

    execute('qmp_capabilities')
    return execute


def chord(name):
    parts = name.split('-') if name not in ('-',) else [name]
    return [{'type': 'qcode', 'data': part} for part in parts]


def character(char):
    if char.isalpha() and char.isupper():
        return [{'type': 'qcode', 'data': 'shift'}, {'type': 'qcode', 'data': char.lower()}]
    if char.isalnum():
        return [{'type': 'qcode', 'data': char}]
    if char in SHIFTED:
        return [{'type': 'qcode', 'data': 'shift'}, {'type': 'qcode', 'data': SHIFTED[char]}]
    return [{'type': 'qcode', 'data': PLAIN[char]}]


def main():
    vm_id, mode, *rest = sys.argv[1:]
    execute = qmp(control_socket(vm_id))
    sequences = [chord(name) for name in rest] if mode == 'keys' else [character(c) for c in ' '.join(rest)]
    for keys in sequences:
        execute('send-key', keys=keys, **{'hold-time': 40})
        time.sleep(0.06)


if __name__ == '__main__':
    main()
