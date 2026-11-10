"""Boot / use / always-tear-down, as context managers."""

from __future__ import annotations

import logging
import secrets
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from tartvm.config import Settings
from tartvm.guest import Guest, wait_for_ssh
from tartvm.runner import Runner
from tartvm.tart import Clock, Launcher, PopenLauncher, Process, Tart, TartError

log = logging.getLogger(__name__)


@dataclass
class Host:
    runner: Runner
    tart: Tart
    settings: Settings
    guest_user: str
    logs: Path
    launcher: Launcher = field(default_factory=PopenLauncher)
    clock: Clock = field(default_factory=Clock)


def _await_power_off(host: Host, name: str, proc: Process, timeout: float) -> None:
    deadline = host.clock.monotonic() + timeout
    while proc.poll() is None:
        if host.clock.monotonic() >= deadline:
            raise TartError(f"VM {name} did not shut itself down within {timeout:.0f}s")
        host.clock.sleep(5)


def _stop(host: Host, name: str, proc: Process) -> None:
    if proc.poll() is None:
        host.tart.stop(name)
    try:
        proc.wait(timeout=120)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=30)


@contextmanager
def running(
    host: Host,
    name: str,
    *,
    alias: str,
    graphics: bool = False,
    provisioning: str | None = None,
    boot_timeout: float = 600,
    expect_power_off: bool = False,
) -> Iterator[Guest]:
    """Boot `name`, wait for SSH, yield a Guest, and always stop the VM.

    expect_power_off: the block ends with the guest shutting itself down (e.g. sealing an
    image). The VM must stop on its own; a forced stop is a failure because it can lose
    the guest's final writes.
    """
    argv = host.tart.run_argv(name, graphics=graphics, provisioning=provisioning)
    proc = host.launcher.start(argv, host.tart.env, host.logs / f"{name}.log")
    try:
        host.clock.sleep(5)
        if proc.poll() is not None:
            raise TartError(f"tart run exited immediately; see {host.logs / f'{name}.log'}")
        ip = host.tart.ip(name, wait=int(boot_timeout))
        guest = Guest(
            ip,
            host.guest_user,
            host.settings.ssh_dir,
            alias,
            name,
            password_auth=provisioning is not None,
        )
        wait_for_ssh(host.runner, guest, host.clock, boot_timeout)
        yield guest
        if expect_power_off:
            _await_power_off(host, name, proc, 600)
    finally:
        _stop(host, name, proc)


def clone_name(host: Host, purpose: str) -> str:
    return f"{host.settings.prefix}-{purpose}-{secrets.token_hex(4)}"


@contextmanager
def ephemeral_clone(
    host: Host, image: str, *, purpose: str = "run", graphics: bool = False, keep: bool = False
) -> Iterator[Guest]:
    """APFS copy-on-write clone of `image`, booted, deleted afterwards even on failure."""
    name = clone_name(host, purpose)
    host.tart.clone(image, name)
    try:
        host.tart.configure(name, random_mac=True, display="1600x1000" if graphics else None)
        with running(host, name, alias=image, graphics=graphics) as guest:
            yield guest
    finally:
        if keep:
            log.warning("keeping VM %s for inspection; delete it when done", name)
        elif name in host.tart.vms():
            host.tart.delete(name)
