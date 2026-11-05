"""Fedora live-image installation helpers (no host dependencies beyond the stdlib)."""
import base64
import re
import subprocess

from common import CTL, run, wait_for


def detect_profile(iso, profile=None):
    if profile:
        return profile
    name = str(iso).rsplit('/', 1)[-1].lower()
    if 'fedora' in name:
        return 'fedora'
    if 'ubuntu' in name:
        return 'ubuntu'
    raise ValueError('Unknown ISO name; specify --profile ubuntu or --profile fedora')


def public_key_text(public_key):
    kind, key, *_ = public_key.split()
    if kind != 'ssh-ed25519' or not re.fullmatch(r'[A-Za-z0-9+/=]+', key):
        raise ValueError('Expected an ed25519 public key')
    return f'{kind} {key}'


def grub_arguments(public_key):
    credential = base64.b64encode((public_key_text(public_key) + '\n').encode()).decode()
    return (' console=ttyAMA0 systemd.wants=sshd.service '
            'systemd.set_credential_binary=ssh.authorized_keys.root:' + credential)


def kickstart(public_key, password_hash):
    if not re.fullmatch(r'\$6\$[./A-Za-z0-9$]+', password_hash):
        raise ValueError('Expected a SHA512-crypt password hash')
    return f'''cmdline
liveimg --url=file:///run/initramfs/live/LiveOS/squashfs.img
lang en_US.UTF-8
keyboard us
timezone UTC --utc
rootpw --lock
user --name=tester --gecos="Tester" --groups=wheel --iscrypted --password={password_hash}
sshkey --username=tester "{public_key_text(public_key)}"
ignoredisk --only-use=vda
zerombr
clearpart --all --initlabel --drives=vda --disklabel=gpt
autopart --type=btrfs --noswap
bootloader
firstboot --disable
services --enabled=sshd
poweroff

%post --erroronfail
echo 'tester ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-tester
chmod 440 /etc/sudoers.d/90-tester
mkdir -p /etc/gdm
printf '[daemon]\\nAutomaticLoginEnable=True\\nAutomaticLogin=tester\\n' > /etc/gdm/custom.conf
mkdir -p /etc/plasmalogin.conf.d
printf '[Autologin]\\nUser=tester\\nSession=plasma.desktop\\n' > /etc/plasmalogin.conf.d/90-harness-autologin.conf
mkdir -p /home/tester/.config
touch /home/tester/.config/gnome-initial-setup-done
chown -R tester:tester /home/tester/.config
restorecon -R /home/tester/.config || true
systemctl set-default graphical.target
# Prevent KDE's first-run wizard from logging in as plasma-setup.
touch /etc/plasma-setup-done
touch /var/lib/linuxvm-harness-installed
%end
'''


START_SCRIPT = '''#!/bin/sh
rm -f /run/anaconda/bus.address /run/user/0/anaconda.pid /var/run/anaconda.pid
export LANG=C.UTF-8 LC_ALL=C.UTF-8
exec anaconda --cmdline --kickstart /root/ks.cfg
'''


def anaconda_failure(text):
    # Anaconda also logs ERR for harmless things, such as a console font it can't
    # set, so only these count. An exit without a power-off is caught separately.
    return next((line for line in text.splitlines()
                 if any(marker in line for marker in ('CmdlineError', 'Traceback'))), None)


def install(guest, vm_id, directory, timeout):
    """Run Anaconda detached; only the resulting power-off counts as success."""
    def stopped():
        return run([CTL, 'status', vm_id]).stdout.splitlines()[0] == 'stopped'

    script = directory / 'start-anaconda.sh'
    script.write_text(START_SCRIPT)
    try:
        guest.put(directory / 'ks.cfg', '/root/ks.cfg')
        guest.put(script, '/root/start-anaconda.sh')
        guest.ssh("rm -f /root/anaconda.exit; nohup sh -c 'sh /root/start-anaconda.sh; echo $? > /root/anaconda.exit' > /root/anaconda.out 2>&1 < /dev/null &")
        def finished():
            if stopped():
                return True
            try:
                result = guest.ssh('cat /tmp/anaconda.log /root/anaconda.out 2>/dev/null; '
                                   'if test -f /root/anaconda.exit; then echo HARNESS_ANACONDA_EXITED; cat /root/anaconda.exit; fi',
                                   check=False, timeout=15)
            except subprocess.TimeoutExpired:
                return stopped()
            # The latest snapshot only: the logs are whole files, read every poll.
            (directory / 'anaconda-monitor.log').write_text(result.stdout + result.stderr)
            # SSH can disappear during the final power-off, before status catches up.
            if result.returncode == 255:
                return stopped()
            failure = anaconda_failure(result.stdout)
            if failure or 'HARNESS_ANACONDA_EXITED' in result.stdout:
                if stopped():
                    return True
                raise RuntimeError(f'Anaconda failed or exited without power-off: {failure or result.stdout[-300:]}')
            return False
        wait_for('Anaconda power-off', finished, timeout, directory / 'anaconda-monitor.log')
    except BaseException:
        # Best effort: retain the original error even if SSH has gone away.
        try:
            result = guest.ssh('tar -cf /root/harness-anaconda-logs.tar /tmp/*.log /root/anaconda.out', check=False, timeout=30)
            (directory / 'anaconda-collect.log').write_text(result.stdout + result.stderr)
            guest.get('/root/harness-anaconda-logs.tar', directory / 'anaconda-logs.tar')
            guest.get('/root/anaconda.out', directory / 'anaconda.out')
        except Exception as error:
            (directory / 'anaconda-collect-error.log').write_text(str(error))
        raise
