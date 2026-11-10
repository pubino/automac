"""SSH access to a running guest with no inheritance from the operator's SSH setup."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from tartvm.runner import Runner
from tartvm.tart import IPV4_RE, Clock, TartError

SSH = "/usr/bin/ssh"
SCP = "/usr/bin/scp"
GUEST_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


@dataclass(frozen=True)
class Guest:
    ip: str
    user: str
    ssh_dir: Path  # id_ed25519, known_hosts, guest-password, askpass
    host_key_alias: str  # the image name: all clones of one image share its host key
    name: str
    password_auth: bool = False

    def __post_init__(self) -> None:
        if not IPV4_RE.fullmatch(self.ip):
            raise TartError(f"invalid guest address {self.ip!r}")

    @property
    def home(self) -> Path:
        return Path("/Users") / self.user

    def with_key(self) -> Guest:
        return replace(self, password_auth=False)

    def _opts(self) -> list[str]:
        opts = {
            "UserKnownHostsFile": str(self.ssh_dir / "known_hosts"),
            "GlobalKnownHostsFile": "/dev/null",
            "HostKeyAlias": self.host_key_alias,
            "ForwardAgent": "no",
            "ForwardX11": "no",
            "ClearAllForwardings": "yes",
            "PermitLocalCommand": "no",
            "ConnectTimeout": "10",
            "ServerAliveInterval": "30",
            "ServerAliveCountMax": "10",
            "LogLevel": "ERROR",
        }
        if self.password_auth:
            opts |= {
                "BatchMode": "no",
                "PubkeyAuthentication": "no",
                "PreferredAuthentications": "keyboard-interactive,password",
                "NumberOfPasswordPrompts": "1",
                "StrictHostKeyChecking": "accept-new",  # first boot of a brand-new image only
            }
        else:
            opts |= {
                "BatchMode": "yes",
                "IdentitiesOnly": "yes",
                "PasswordAuthentication": "no",
                "KbdInteractiveAuthentication": "no",
                "StrictHostKeyChecking": "yes",
            }
        args = ["-F", "/dev/null"]  # ignore ~/.ssh/config entirely
        if not self.password_auth:
            args += ["-i", str(self.ssh_dir / "id_ed25519")]
        for k, v in opts.items():
            args += ["-o", f"{k}={v}"]
        return args

    def _client_env(self) -> list[str]:
        env = ["/usr/bin/env", "-u", "SSH_AUTH_SOCK"]  # the operator's agent never reaches ssh
        if self.password_auth:
            env += [
                f"SSH_ASKPASS={self.ssh_dir / 'askpass'}",
                "SSH_ASKPASS_REQUIRE=force",
                "DISPLAY=none",
                f"TARTVM_PASSWORD_FILE={self.ssh_dir / 'guest-password'}",
            ]
        return env

    def command(
        self, argv: Sequence[str], env: Mapping[str, str] | None = None, *, stdin: bool = False
    ) -> list[str]:
        """Host argv that runs `argv` in the guest with a clean environment.

        Without stdin=True, ssh gets -n: anything you pipe in is discarded. Pass data as an
        argv value or scp a file instead.
        """
        base = {
            "HOME": str(self.home),
            "USER": self.user,
            "LOGNAME": self.user,
            "PATH": GUEST_PATH,
            "LANG": "C",
            "LC_ALL": "C",
        }
        merged = {**base, **(env or {})}
        remote = shlex.join(["/usr/bin/env", "-i", *(f"{k}={v}" for k, v in merged.items()), *argv])
        return [
            *self._client_env(),
            SSH,
            *([] if stdin else ["-n"]),
            *self._opts(),
            f"{self.user}@{self.ip}",
            "--",
            remote,
        ]

    def put(self, runner: Runner, local: Path, remote: Path) -> None:
        runner.run(
            [
                *self._client_env(),
                SCP,
                "-q",
                *self._opts(),
                str(local),
                f"{self.user}@{self.ip}:{remote}",
            ],
            timeout=3600,
        )

    def get(self, runner: Runner, remote: Path, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        runner.run(
            [
                *self._client_env(),
                SCP,
                "-q",
                *self._opts(),
                f"{self.user}@{self.ip}:{remote}",
                str(local),
            ],
            timeout=3600,
        )

    def sha256(self, runner: Runner, remote: Path) -> str:
        out = runner.run(self.command(["/usr/bin/shasum", "-a", "256", str(remote)])).stdout
        digest = out.split(" ", 1)[0]
        if len(digest) != 64:
            raise TartError(f"unparsed shasum output: {out[:80]!r}")
        return digest


def wait_for_ssh(runner: Runner, guest: Guest, clock: Clock, timeout: float) -> None:
    """`tart ip` answering does not mean sshd is up; poll a no-op command."""
    deadline = clock.monotonic() + timeout
    last = ""
    while True:
        try:
            res = runner.run(guest.command(["/usr/bin/true"]), check=False, timeout=60)
            if res.returncode == 0:
                return
            last = (res.stderr or "").strip()[-200:]
        except subprocess.TimeoutExpired:
            last = "ssh timed out"
        if clock.monotonic() >= deadline:
            raise TartError(f"VM {guest.name} did not accept SSH within {timeout:.0f}s: {last}")
        clock.sleep(10)
