"""A scripted Tart + guest for the Python library tests. No VM, no network.

Any command the world does not recognise fails the test: silence is never success.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tartvm.runner import CommandError, Result

IP = "192.168.64.7"
GuestHandler = Callable[[list[str]], tuple[int, str, str]]


@dataclass
class FakeProcess:
    world: World
    exit_immediately: bool = False
    terminated: bool = False

    def poll(self) -> int | None:
        return 0 if (self.exit_immediately or self.world.powered_off) else None

    def terminate(self) -> None:
        self.terminated = True
        self.world.powered_off = True

    def wait(self, timeout: float | None = None) -> int:
        self.world.powered_off = True
        return 0


@dataclass
class FakeLauncher:
    world: World
    started: list[list[str]] = field(default_factory=list)
    exit_immediately: bool = False

    def start(self, argv: Sequence[str], env: Mapping[str, str], log_path: Path) -> FakeProcess:
        assert env["TART_HOME"].endswith("/tart")
        assert env["TART_NO_AUTO_PRUNE"] == "1"
        self.started.append(list(argv))
        self.world.powered_off = False
        return FakeProcess(self.world, exit_immediately=self.exit_immediately)


@dataclass
class FakeClock:
    now: float = 0.0

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


@dataclass
class World:
    vms: dict[str, dict[str, Any]] = field(default_factory=dict)
    tart_calls: list[list[str]] = field(default_factory=list)
    remote: list[list[str]] = field(default_factory=list)
    ssh_argv: list[list[str]] = field(default_factory=list)
    guest_files: dict[str, bytes] = field(default_factory=dict)
    handlers: dict[str, GuestHandler] = field(default_factory=dict)
    ssh_failures: int = 0
    powered_off: bool = True
    shutdown_on_seal: bool = True

    # ------------------------------------------------------------------ runner protocol
    def run(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        check: bool = True,
        timeout: float | None = None,
        stdin_path: Path | None = None,
    ) -> Result:
        argv = [str(a) for a in args]
        if argv[0].endswith("/tart"):
            rc, out, err = self.tart(argv[1:])
        elif "/usr/bin/ssh" in argv:
            rc, out, err = self.ssh(argv)
        elif "/usr/bin/scp" in argv:
            rc, out, err = self.scp(argv)
        elif argv[0] == "/usr/bin/ssh-keygen":
            rc, out, err = self.keygen(argv)
        else:
            raise AssertionError(f"unexpected host command: {argv}")
        if check and rc != 0:
            raise CommandError(argv, rc, err)
        return Result(argv, rc, out, err)

    # ------------------------------------------------------------------ tart
    def tart(self, args: list[str]) -> tuple[int, str, str]:
        self.tart_calls.append(args)
        cmd = args[0]
        if cmd == "list":
            items = [{"Name": n, "Running": False, **v} for n, v in self.vms.items()]
            return 0, json.dumps(items), ""
        if cmd == "create":
            self.vms[args[-1]] = {}
        elif cmd == "clone":
            assert args[1] in self.vms, f"clone of missing VM {args[1]}"
            self.vms[args[2]] = {}
        elif cmd == "delete":
            self.vms.pop(args[1])
        elif cmd == "rename":
            self.vms[args[2]] = self.vms.pop(args[1])
        elif cmd == "ip":
            return 0, IP + "\n", ""
        elif cmd in ("set", "stop"):
            pass
        else:
            raise AssertionError(f"unexpected tart command: {args}")
        return 0, "", ""

    # ------------------------------------------------------------------ ssh / scp
    def ssh(self, argv: list[str]) -> tuple[int, str, str]:
        self.ssh_argv.append(argv)
        remote = shlex.split(argv[-1])
        assert remote[:2] == ["/usr/bin/env", "-i"], remote
        cmd = [a for a in remote[2:] if not ("=" in a and a.split("=", 1)[0].isupper())]
        self.remote.append(cmd)
        if cmd == ["/usr/bin/true"]:
            if self.ssh_failures:
                self.ssh_failures -= 1
                return 255, "", "Connection refused"
            return 0, "", ""
        for key, handler in self.handlers.items():
            if key in " ".join(cmd):
                return handler(cmd)
        return self.default_guest(cmd)

    def default_guest(self, cmd: list[str]) -> tuple[int, str, str]:
        joined = " ".join(cmd)
        if cmd[:2] == ["/usr/sbin/sysctl", "-n"]:
            return 0, "1\n", ""
        if cmd == ["/usr/bin/id", "-un"]:
            return 0, "tester\n", ""
        if cmd[:2] == ["/bin/ls", "-d"]:
            return 1, "", f"ls: {cmd[2]}: No such file or directory"
        if cmd[:2] == ["/usr/bin/sudo", "-n"]:
            return 1, "", "sudo: a password is required"
        if cmd[0] == "/bin/sh" and "credentials" in cmd[2]:
            return 0, "authorized_keys\n", ""
        if cmd[0] == "/usr/bin/security":
            return 0, "\n     0 valid identities found\n", ""
        if cmd[0] == "/usr/bin/shasum":
            data = self.guest_files.get(cmd[-1])
            if data is None:
                return 1, "", "no such file"
            return 0, f"{hashlib.sha256(data).hexdigest()}  {cmd[-1]}\n", ""
        if "/sbin/shutdown" in joined:
            if self.shutdown_on_seal:
                self.powered_off = True
            return 255, "", "Connection closed"
        if cmd[0] == "/bin/sh" and "open -n" in cmd[2]:
            return 0, "running 4242\n", ""
        if cmd[0] == "/usr/bin/find":
            return 0, "", ""
        if cmd[:2] == ["/usr/bin/xattr", "-p"]:
            return 0, "0083;00000000;Safari;\n", ""
        if cmd[0] == "/usr/sbin/spctl":
            return 0, "", f"{cmd[-1]}: accepted\nsource=Notarized Developer ID\n"
        if cmd[0] in ("/bin/mkdir", "/usr/bin/tar", "/usr/bin/touch", "/usr/bin/pkill",
                      "/usr/bin/xattr", "/usr/bin/hdiutil", "/bin/cp", "/bin/sh"):  # fmt: skip
            return 0, "", ""
        raise AssertionError(f"unexpected guest command: {cmd}")

    def scp(self, argv: list[str]) -> tuple[int, str, str]:
        src, dst = argv[-2], argv[-1]
        if "@" in dst:
            self.guest_files[dst.split(":", 1)[1]] = Path(src).read_bytes()
        else:
            Path(dst).write_bytes(self.guest_files[src.split(":", 1)[1]])
        return 0, "", ""

    def keygen(self, argv: list[str]) -> tuple[int, str, str]:
        if "-R" in argv:
            return 0, "", ""
        key = Path(argv[argv.index("-f") + 1])
        key.write_text("PRIVATE\n")
        key.with_suffix(".pub").write_text("ssh-ed25519 AAAAC3Nza tartvm-vm\n")
        return 0, "", ""
