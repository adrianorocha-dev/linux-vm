"""Host command-line entry points for SSH capture and presentation timing."""
import argparse
import json
from pathlib import Path
import shlex
import sys
import uuid
from common import Guest, SESSION, write_json
from analyzer import analyze
from statistics_tools import timing_report

HERE = Path(__file__).resolve().parent


def main():
    tool = Path(sys.argv[0]).name
    parser = argparse.ArgumentParser(description=tool)
    if tool == 'analyze-input':
        parser.add_argument('recording', type=Path)
        parser.add_argument('--output', type=Path)
        parser.add_argument('--gap', type=float, default=.1)
        args = parser.parse_args()
        source = args.recording.read_text()
        result = analyze(json.loads(source) if source.lstrip().startswith('{') else source, gap_seconds=args.gap)
        if args.output:
            write_json(args.output, result)
        print(json.dumps(result, indent=2))
        return
    connection = parser.add_mutually_exclusive_group(required=True)
    connection.add_argument('--run', type=Path, help='Harness run directory')
    connection.add_argument('--port', type=int, help='Existing VM SSH port (does not start it)')
    parser.add_argument('--key', type=Path)
    parser.add_argument('--user', default='tester')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--install-deps', action='store_true', help='Install required guest packages with apt')
    if tool in ('record-input', 'presentation-timing'):
        parser.add_argument('--seconds', type=float, default=10)
    if tool == 'presentation-timing':
        parser.add_argument('--cpu-load', type=int, default=0)
    args = parser.parse_args()
    if args.port and not args.key:
        parser.error('--port requires --key')
    if hasattr(args, 'seconds') and not 0 < args.seconds <= 3600:
        parser.error('--seconds must be in (0, 3600]')
    if hasattr(args, 'cpu_load') and not 0 <= args.cpu_load <= 64:
        parser.error('--cpu-load must be between 0 and 64')
    guest = Guest.from_run(args.run) if args.run else Guest(args.port, args.key, args.user)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    packages = {'monitor-state': 'python3-gi edid-decode', 'screenshot': 'python3-gi',
                'record-input': 'libinput-tools', 'presentation-timing': 'python3-gi python3-cairo python3-gi-cairo gir1.2-gtk-4.0'}
    if args.install_deps:
        result = guest.ssh('sudo env DEBIAN_FRONTEND=noninteractive apt-get update && sudo env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=120 install -y ' + packages[tool], timeout=600, check=False)
        args.output.with_suffix('.apt.log').write_text(result.stdout + result.stderr)
        result.check_returncode()
    try:
        if tool == 'monitor-state':
            result = guest.script(HERE / 'guest/monitor.py')
            write_json(args.output, json.loads(result.stdout))
        elif tool == 'screenshot':
            # Grant only on explicitly selected test VM, before invoking the portal.
            guest.ssh(SESSION + "gdbus call --session --dest org.freedesktop.impl.portal.PermissionStore --object-path /org/freedesktop/impl/portal/PermissionStore --method org.freedesktop.impl.portal.PermissionStore.SetPermission screenshot true screenshot '' \"['yes']\"")
            remote = '/tmp/linuxvm-screenshot-' + uuid.uuid4().hex + '.png'
            try:
                result = guest.script(HERE / 'guest/screenshot.py', [remote], timeout=60)
                guest.get(remote, args.output)
                if args.output.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
                    raise RuntimeError('Portal output is not a PNG')
            finally:
                guest.ssh('rm -f -- ' + shlex.quote(remote), check=False)
        elif tool == 'record-input':
            print(f'Recording for {args.seconds:g}s; gesture on the Mac trackpad now.', flush=True)
            result = guest.ssh('sudo python3 - ' + str(args.seconds), input=(HERE / 'guest/record.py').read_text(), timeout=args.seconds + 30)
            recording = json.loads(result.stdout)
            write_json(args.output, recording)
            write_json(args.output.with_suffix('.analysis.json'), analyze(recording))
        elif tool == 'presentation-timing':
            result = guest.script(HERE / 'guest/timing.py', [args.seconds, args.cpu_load], timeout=args.seconds + 60)
            report = timing_report(json.loads(result.stdout))
            write_json(args.output, report)
            if report['presented_frame_count'] < 2:
                raise RuntimeError('No usable presentation feedback; see output JSON and stderr log')
        else:
            parser.error('unknown tool: ' + tool)
        args.output.with_suffix(args.output.suffix + '.stderr.log').write_text(result.stderr)
    except Exception as error:
        if hasattr(error, 'stderr'):
            args.output.with_suffix(args.output.suffix + '.stderr.log').write_text(error.stderr or '')
        raise
    print(args.output.resolve())


if __name__ == '__main__':
    main()
