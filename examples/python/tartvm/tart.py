"""Thin, validated wrapper over the tart CLI.

Every VM name is checked against the project prefix before any mutating call, so a typo
or a hostile value can never delete the operator's own VMs. TART_HOME is always set, so
this project's images live apart from anything else on the Mac.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from tartvm.config import ConfigError, Settings
from tartvm.runner import Runner

IPV4_RE = re.compile(r"(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)")
FORBIDDEN_RUN_FLAGS = ("--dir", "--net-bridged", "--disk")


class TartError(RuntimeError):
    pass


@dataclass
class Clock:
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic


class Process(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


class Launcher(Protocol):
    def start(self, argv: Sequence[str], env: Mapping[str, str], log_path: Path) -> Process: ...


class PopenLauncher:
    """Starts `tart run` in the background. The argv is not logged: on first boot it holds
    the guest password (--provisioning-opts)."""

    def start(self, argv: Sequence[str], env: Mapping[str, str], log_path: Path) -> Process:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as fh:
            return subprocess.Popen(
                list(argv),
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # Ctrl-C in the terminal must not kill the VM mid-write
            )


@dataclass(frozen=True)
class Tart:
    runner: Runner
    settings: Settings

    @property
    def env(self) -> dict[str, str]:
        return {
            "HOME": str(Path.home()),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "TART_HOME": str(self.settings.home),
            # Auto-prune may delete *other* cached images to make room for a clone.
            "TART_NO_AUTO_PRUNE": "1",
        }

    def name(self, name: str) -> str:
        if not re.fullmatch(rf"{self.settings.prefix}-[a-z]+-[A-Za-z0-9_.-]+", name):
            raise ConfigError(f"refusing to manage VM with unexpected name {name!r}")
        return name

    def _run(self, *args: str, check: bool = True, timeout: float | None = None) -> str:
        argv = [str(self.settings.tart), *args]
        return self.runner.run(argv, env=self.env, check=check, timeout=timeout).stdout

    def vms(self) -> dict[str, dict[str, Any]]:
        raw = self._run("list", "--source", "local", "--format", "json")
        try:
            items = json.loads(raw or "[]")
        except json.JSONDecodeError as exc:
            raise TartError(f"cannot parse tart list output: {raw[:120]!r}") from exc
        return {str(i["Name"]): i for i in items if isinstance(i, dict) and "Name" in i}

    def create_from_ipsw(self, name: str, ipsw: Path, disk_gb: int) -> None:
        self._run(
            "create",
            "--from-ipsw",
            str(ipsw),
            "--disk-size",
            str(disk_gb),
            "--disk-format",
            "asif",
            self.name(name),
            timeout=3600,
        )

    def clone(self, source: str, name: str) -> None:
        self._run("clone", self.name(source), self.name(name), timeout=600)

    def configure(self, name: str, *, random_mac: bool, display: str | None = None) -> None:
        s = self.settings
        args = ["set", self.name(name), "--cpu", str(s.cpus), "--memory", str(s.memory_gb * 1024)]
        if random_mac:
            args.append("--random-mac")  # two clones of one image must not share a DHCP lease
        if display is not None:
            if not re.fullmatch(r"[0-9]{3,4}x[0-9]{3,4}", display):
                raise ConfigError(f"invalid display size {display!r}")
            args += ["--display", display]
        self._run(*args)

    def ip(self, name: str, wait: int) -> str:
        out = self._run("ip", "--wait", str(wait), self.name(name), timeout=wait + 30).strip()
        if not IPV4_RE.fullmatch(out):
            raise TartError(f"tart ip returned an unexpected address: {out[:40]!r}")
        return out

    def stop(self, name: str, timeout: int = 60) -> None:
        # Presses the virtual power button; macOS may answer with a dialog, and tart then
        # cuts power after the timeout. Never rely on it to flush a guest's last writes.
        self._run(
            "stop", "--timeout", str(timeout), self.name(name), check=False, timeout=timeout + 60
        )

    def delete(self, name: str) -> None:
        self._run("delete", self.name(name))

    def rename(self, old: str, new: str) -> None:
        self._run("rename", self.name(old), self.name(new))

    def run_argv(
        self, name: str, *, graphics: bool = False, provisioning: str | None = None
    ) -> list[str]:
        argv = [str(self.settings.tart), "run", "--no-audio", "--no-clipboard"]
        if not graphics:
            argv.append("--no-graphics")
        if provisioning is not None:
            argv.append(f"--provisioning-opts={provisioning}")
        argv.append(self.name(name))
        if any(a.startswith(FORBIDDEN_RUN_FLAGS) for a in argv):
            raise ConfigError("test VMs never get host shares, extra disks, or bridged networks")
        return argv


def provisioning_opts(user: str, password: str, full_name: str = "Test User") -> str:
    """First-boot account + SSH via the macOS 27 guest provisioning API (host and guest
    must both be macOS 27+). Values are comma-separated, so restrict them hard."""
    if not re.fullmatch(r"[a-z][a-z0-9]{1,30}", user):
        raise ConfigError("guest user must be lowercase alphanumeric")
    if not re.fullmatch(r"[A-Za-z0-9]{16,64}", password):
        raise ConfigError("guest password must be 16-64 alphanumeric characters")
    if not re.fullmatch(r"[A-Za-z0-9 ]{1,40}", full_name):
        raise ConfigError("full name must be letters, digits and spaces")
    return ",".join(
        [
            f"fullName={full_name}",
            f"username={user}",
            f"password={password}",
            "logsInAutomatically=true",  # GUI session exists, so `open` works over SSH
            "enablesRemoteLogin=true",
        ]
    )
