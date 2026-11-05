"""Desktop state parsers, also sent to guests by common.py."""
import json
import shlex


def parse_session_environment(text):
    """Accept only the desktop variables from systemd's quoted assignments."""
    result = {}
    for assignment in shlex.split(text):
        key, separator, value = assignment.partition('=')
        if separator and key in ('WAYLAND_DISPLAY', 'XDG_CURRENT_DESKTOP'):
            result[key] = value
    return result


def kde_clipboard_active(text):
    try:
        value = json.loads(text)
        return isinstance(value, dict) and value.get('state') == 'active'
    except (ValueError, TypeError):
        return False


if __name__ == '__main__':
    import os
    from pathlib import Path
    import sys

    if sys.argv[1] == 'environment':
        for key, value in parse_session_environment(sys.stdin.read()).items():
            print('export ' + key + '=' + shlex.quote(value))
    elif sys.argv[1] == 'clipboard':
        path = Path(os.environ['XDG_RUNTIME_DIR']) / 'linuxvm/clipboard.json'
        sys.exit(0 if kde_clipboard_active(path.read_text()) else 1)
