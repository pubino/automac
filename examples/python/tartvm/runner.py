"""The single place where external commands run.

Commands are always argument lists, never shell strings. stdin is /dev/null unless a
file is named, so no command can read the operator's terminal and secrets never need to
appear in argv. Tests replace the runner with a scripted fake.
"""

from __future__ import annotations

import contextlib
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class CommandError(RuntimeError):
    def __init__(self, args: Sequence[str], returncode: int, detail: str) -> None:
        super().__init__(f"{args[0]} exited {returncode}: {detail.strip()[-400:]}")
        self.argv = list(args)
        self.returncode = returncode


@dataclass(frozen=True)
class Result:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        check: bool = True,
        timeout: float | None = None,
        stdin_path: Path | None = None,
    ) -> Result: ...


class SubprocessRunner:
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
        with contextlib.ExitStack() as stack:
            stdin = (
                stack.enter_context(stdin_path.open("rb"))
                if stdin_path is not None
                else subprocess.DEVNULL
            )
            proc = subprocess.run(
                argv,
                env=dict(env) if env is not None else None,
                stdin=stdin,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        result = Result(argv, proc.returncode, proc.stdout, proc.stderr)
        if check and proc.returncode != 0:
            raise CommandError(argv, proc.returncode, proc.stderr)
        return result
