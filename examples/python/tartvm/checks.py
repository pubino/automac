"""Checks that produce positive evidence. Every check fails closed: unparsed output, a
missing result, or an error running the probe is a failure, never a pass."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tartvm.guest import Guest
from tartvm.runner import Runner
from tartvm.tart import FORBIDDEN_RUN_FLAGS

SHARED_FOLDERS = "/Volumes/My Shared Files"
QUARANTINE = "com.apple.quarantine"
CREDENTIAL_PROBE = (
    'for p in "$HOME/.config/gh" "$HOME/.appstoreconnect" "$HOME/.netrc" '
    '"$HOME/.git-credentials"; do [ ! -e "$p" ] || echo "$p"; done; '
    '/bin/ls -A "$HOME/.ssh" 2>/dev/null; true'
)


@dataclass(frozen=True)
class Check:
    name: str
    result: Literal["pass", "fail"]
    detail: str


def _probe(runner: Runner, guest: Guest, argv: list[str]) -> tuple[int, str, str]:
    res = runner.run(guest.command(argv), check=False, timeout=120)
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def boundary(runner: Runner, guest: Guest, run_argv: Sequence[str]) -> list[Check]:
    """Evidence that the guest is a VM that cannot reach the operator's Mac or secrets."""
    checks: list[Check] = []
    shares = [a for a in run_argv if a.startswith(FORBIDDEN_RUN_FLAGS)]
    checks.append(
        Check(
            "no_host_shares",
            "fail" if shares else "pass",
            ", ".join(shares) or "tart run without --dir/--disk/bridged",
        )
    )
    rc, out, _ = _probe(runner, guest, ["/usr/sbin/sysctl", "-n", "kern.hv_vmm_present"])
    checks.append(
        Check(
            "virtual_machine",
            "pass" if rc == 0 and out == "1" else "fail",
            f"kern.hv_vmm_present={out!r}",
        )
    )
    rc, out, _ = _probe(runner, guest, ["/usr/bin/id", "-un"])
    checks.append(
        Check(
            "guest_account", "pass" if rc == 0 and out == guest.user else "fail", out or "id failed"
        )
    )
    rc, _, err = _probe(runner, guest, ["/bin/ls", "-d", SHARED_FOLDERS])
    ok = rc != 0 and "No such file" in err
    checks.append(
        Check(
            "no_shared_folders",
            "pass" if ok else "fail",
            "no shared folder mount" if ok else f"{SHARED_FOLDERS}: {err or 'exists'}",
        )
    )
    rc, out, _ = _probe(
        runner, guest, ["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"]
    )
    m = re.search(r"(\d+) valid identities found", out)
    ok = m is not None and m.group(1) == "0"
    checks.append(
        Check(
            "no_signing_identities",
            "pass" if ok else "fail",
            "0 valid identities" if ok else "identities visible or output unparsed",
        )
    )
    rc, _, _ = _probe(runner, guest, ["/usr/bin/sudo", "-n", "/usr/bin/true"])
    checks.append(
        Check(
            "no_passwordless_sudo",
            "pass" if rc != 0 else "fail",
            "sudo -n denied" if rc != 0 else "test account has passwordless sudo",
        )
    )
    rc, out, _ = _probe(runner, guest, ["/bin/sh", "-c", CREDENTIAL_PROBE])
    found = [line for line in out.splitlines() if line and line != "authorized_keys"]
    ok = rc == 0 and not found
    checks.append(
        Check(
            "no_credentials",
            "pass" if ok else "fail",
            "no credential files" if ok else ", ".join(found) or f"probe failed ({rc})",
        )
    )
    return checks


def require(checks: Sequence[Check]) -> None:
    failed = [c for c in checks if c.result != "pass"]
    if failed or not checks:
        raise AssertionError(
            "checks failed: " + ("; ".join(f"{c.name}: {c.detail}" for c in failed) or "none ran")
        )


# Runs in the guest via /bin/sh -c. $1 app, $2 process name, $3 seconds alive, $4 start-within.
LAUNCH_SCRIPT = (
    '/usr/bin/open -n "$1" || exit 2; i=0; '
    'while ! /usr/bin/pgrep -x "$2" >/dev/null; do /bin/sleep 2; i=$((i + 2)); '
    '[ "$i" -lt "$4" ] || { echo "did not start within $4s"; exit 1; }; done; i=0; '
    'while [ "$i" -lt "$3" ]; do /bin/sleep 2; i=$((i + 2)); '
    '/usr/bin/pgrep -x "$2" >/dev/null || { echo exited; exit 1; }; done; '
    'echo "running $(/usr/bin/pgrep -nx "$2")"'
)


def launch_and_survive(
    runner: Runner,
    guest: Guest,
    app: Path,
    process: str,
    *,
    seconds: int = 20,
    start_within: int = 30,
) -> tuple[Check, str | None]:
    """`open` the app in the guest's GUI session (needs auto-login); it must appear within
    start_within seconds and stay alive for `seconds`. Returns the check and the pid."""
    res = runner.run(
        guest.command(
            [
                "/bin/sh",
                "-c",
                LAUNCH_SCRIPT,
                "sh",
                str(app),
                process,
                str(seconds),
                str(start_within),
            ]
        ),
        check=False,
        timeout=seconds + start_within + 120,
    )
    out = res.stdout.strip()
    match = re.fullmatch(r"running ([0-9]+)", out)
    if res.returncode == 0 and match:
        return Check(f"launch.{process}", "pass", f"running after {seconds}s"), match.group(1)
    detail = out or res.stderr.strip()[-200:] or f"exit {res.returncode}"
    return Check(f"launch.{process}", "fail", detail), None


def crash_reports(runner: Runner, guest: Guest, marker: Path, prefixes: Sequence[str]) -> Check:
    """Crash reports newer than `marker` (touch it before launching) for our processes."""
    reports = guest.home / "Library/Logs/DiagnosticReports"
    res = runner.run(
        guest.command(["/usr/bin/find", str(reports), "-newer", str(marker), "-type", "f"]),
        check=False,
    )
    if res.returncode != 0 and "No such file" not in res.stderr:
        return Check("no_crash_report", "fail", f"cannot list crash reports: {res.stderr[-160:]}")
    crashes = sorted(
        Path(line).name
        for line in res.stdout.splitlines()
        if Path(line).name.startswith(tuple(prefixes))
    )
    return Check("no_crash_report", "fail" if crashes else "pass", ", ".join(crashes) or "none")


def gatekeeper(name: str, returncode: int, text: str) -> Check:
    """Pass only on explicit acceptance as notarized Developer ID. `spctl` saying
    'accepted' with source=Apple Development or a missing source is NOT a pass."""
    if returncode == 0 and ": accepted" in text and "source=Notarized Developer ID" in text:
        return Check(name, "pass", "accepted, Notarized Developer ID")
    return Check(name, "fail", text.strip()[-200:] or f"spctl exit {returncode}")


def spctl_args(kind: Literal["execute", "open"]) -> list[str]:
    args = ["/usr/sbin/spctl", "--assess", "--type", kind, "-vv"]
    if kind == "open":  # disk images
        args += ["--context", "context:primary-signature"]
    return args


def quarantine_like_safari(runner: Runner, guest: Guest, path: Path) -> Check:
    """Mark a file as a browser download so Gatekeeper treats it like a customer's copy."""
    stamp = f"0083;{int(time.time()):08x};Safari;"
    runner.run(guest.command(["/usr/bin/xattr", "-w", QUARANTINE, stamp, str(path)]))
    rc, out, _ = _probe(runner, guest, ["/usr/bin/xattr", "-p", QUARANTINE, str(path)])
    return Check("quarantine.present", "pass" if rc == 0 and out else "fail", out or "missing")
