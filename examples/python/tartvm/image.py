"""Create a sealed base image from an Apple IPSW with first-boot guest provisioning.

Flow: tart create --from-ipsw -> first boot with --provisioning-opts (account + SSH, no
Setup Assistant) -> install a VM-only SSH key over password auth -> optional provisioning
work -> guest shuts itself down -> rename the temporary VM to the image name -> boot a
throwaway clone and verify the seal. A failure deletes the partial VM unless keep_failed.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import string
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from tartvm import checks
from tartvm.guest import Guest, wait_for_ssh
from tartvm.lifecycle import Host, ephemeral_clone, running
from tartvm.runner import Runner
from tartvm.tart import TartError, provisioning_opts

Work = Callable[[Guest], None]


def image_name(prefix: str, inputs: Mapping[str, Any]) -> str:
    """Name derived from every provisioning input (IPSW hash, script hashes, tool pins, a
    revision you bump by hand): change any input and the next run builds a new image."""
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:16]
    return f"{prefix}-image-{digest}"


def ensure_ssh_material(runner: Runner, ssh_dir: Path, comment: str) -> str:
    """A dedicated key + random guest password, useful only for these local VMs."""
    ssh_dir.mkdir(parents=True, exist_ok=True)
    ssh_dir.chmod(0o700)
    key = ssh_dir / "id_ed25519"
    if not key.is_file():
        runner.run(
            ["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(key)]
        )
    pw = ssh_dir / "guest-password"
    if not pw.is_file():
        pw.touch(mode=0o600)
        alphabet = string.ascii_letters + string.digits
        pw.write_text("".join(secrets.choice(alphabet) for _ in range(32)) + "\n")
    pw.chmod(0o600)
    askpass = ssh_dir / "askpass"
    askpass.write_text('#!/bin/sh\nexec /bin/cat -- "$TARTVM_PASSWORD_FILE"\n')
    askpass.chmod(0o700)
    return pw.read_text().strip()


def forget_host_key(runner: Runner, ssh_dir: Path, alias: str) -> None:
    """A rebuilt image has new host keys; drop the old pin for its alias."""
    known = ssh_dir / "known_hosts"
    if known.is_file():
        runner.run(["/usr/bin/ssh-keygen", "-q", "-R", alias, "-f", str(known)], check=False)


def install_key(runner: Runner, guest: Guest, pubkey: str) -> None:
    if not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+ [A-Za-z0-9._-]+", pubkey):
        raise TartError("unexpected SSH public key format")
    runner.run(
        guest.command(
            [
                "/bin/sh",
                "-c",
                'umask 077 && /bin/mkdir -p "$HOME/.ssh" && '
                'printf "%s\\n" "$1" > "$HOME/.ssh/authorized_keys"',
                "sh",
                pubkey,
            ]
        )
    )


def seal(runner: Runner, guest: Guest, password_file: Path) -> None:
    """Sync and power off from inside the guest. The password reaches sudo on stdin only.
    `tart stop` is not used: it can cut power before the last writes reach the disk."""
    res = runner.run(
        guest.command(
            [
                "/usr/bin/sudo",
                "-S",
                "-p",
                "",
                "/bin/sh",
                "-c",
                "/bin/sync && exec /sbin/shutdown -h now",
            ],
            stdin=True,
        ),
        check=False,
        stdin_path=password_file,
    )
    if res.returncode not in (0, 255):  # 255: the connection dropped as the guest went down
        raise TartError(f"seal failed with exit {res.returncode}: {res.stderr[-200:]}")


def create_image(
    host: Host,
    name: str,
    ipsw: Path,
    *,
    disk_gb: int = 80,
    work: Work | None = None,
    keep_failed: bool = False,
) -> None:
    runner, ssh_dir = host.runner, host.settings.ssh_dir
    tmp = name.replace("-image-", "-provision-", 1)
    vms = host.tart.vms()
    for stale in (name, tmp):
        if stale in vms:
            host.tart.delete(stale)
    password = ensure_ssh_material(runner, ssh_dir, f"{host.settings.prefix}-vm")
    forget_host_key(runner, ssh_dir, name)
    host.tart.create_from_ipsw(tmp, ipsw, disk_gb)
    host.tart.configure(tmp, random_mac=False)
    try:
        with running(
            host,
            tmp,
            alias=name,
            boot_timeout=1800,
            expect_power_off=True,
            provisioning=provisioning_opts(host.guest_user, password),
        ) as pw_guest:
            install_key(runner, pw_guest, (ssh_dir / "id_ed25519.pub").read_text().strip())
            guest = pw_guest.with_key()
            wait_for_ssh(runner, guest, host.clock, 120)
            if work is not None:
                work(guest)
            seal(runner, guest, ssh_dir / "guest-password")
        host.tart.rename(tmp, name)
    except BaseException:
        if not keep_failed and tmp in host.tart.vms():
            host.tart.delete(tmp)
        raise
    try:
        with ephemeral_clone(host, name, purpose="sealcheck") as guest:
            argv = host.tart.run_argv(guest.name)
            checks.require(checks.boundary(runner, guest, argv))
    except BaseException:
        if not keep_failed and name in host.tart.vms():
            host.tart.delete(name)
        raise
