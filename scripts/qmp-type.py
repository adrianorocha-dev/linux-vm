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


def qmp(path, timeout=10):
    """Return a command callable with close() and next_event(timeout) methods."""
    connection = socket.socket(socket.AF_UNIX)
    connection.settimeout(timeout)
    connection.connect(path)
    buffered = bytearray()
    events = []

    def receive(wait=timeout):
        deadline = time.monotonic() + wait
        while b'\n' not in buffered:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('QMP response timed out')
            connection.settimeout(remaining)
            chunk = connection.recv(65536)
            if not chunk:
                raise ConnectionError('QMP disconnected')
            buffered.extend(chunk)
        line, _, rest = buffered.partition(b'\n')
        buffered[:] = rest
        return json.loads(line)

    def execute(command, **arguments):
        connection.settimeout(timeout)
        connection.sendall(json.dumps({'execute': command, 'arguments': arguments}).encode() + b'\n')
        deadline = time.monotonic() + timeout
        while True:
            reply = receive(max(.001, deadline - time.monotonic()))
            if 'event' in reply:
                events.append(reply)
            if 'return' in reply or 'error' in reply:
                if 'error' in reply:
                    raise RuntimeError(f"{command}: {reply['error']['desc']}")
                return reply['return']
            if time.monotonic() >= deadline:
                raise TimeoutError(f'QMP {command} timed out')

    def next_event(wait=timeout):
        if events:
            return events.pop(0)
        return receive(wait)

    try:
        receive()
        execute('qmp_capabilities')
    except BaseException:
        connection.close()
        raise
    execute.close = connection.close
    execute.next_event = next_event
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
    try:
        for keys in sequences:
            execute('send-key', keys=keys, **{'hold-time': 40})
            time.sleep(0.06)
    finally:
        execute.close()


if __name__ == '__main__':
    main()
