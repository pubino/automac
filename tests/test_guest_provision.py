"""The guest provisioning template's text processing (runs anywhere zsh does)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "examples/guest/provision.sh"


def run(
    *args: str, stdin: str = "", env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["zsh", str(SCRIPT), *args], input=stdin, capture_output=True, text=True,
        timeout=30, check=False, env=env,
    )  # fmt: skip


def test_syntax() -> None:
    subprocess.run(["zsh", "-n", str(SCRIPT)], check=True)


@pytest.mark.parametrize(
    ("listing", "expected"),
    [
        (
            "* Label: Command Line Tools for Xcode-15.4\n* Label: Command Line Tools for Xcode-16.3\n",
            "Command Line Tools for Xcode-16.3",
        ),
        (
            "* Label: Command Line Tools for Xcode 27.2-27.2\n* Label: Command Line Tools for Xcode 27.0-27.0\n",
            "Command Line Tools for Xcode 27.2-27.2",
        ),
        (  # numeric, not lexical: 16.10 > 16.9
            "* Label: Command Line Tools for Xcode-16.9\n* Label: Command Line Tools for Xcode-16.10\n",
            "Command Line Tools for Xcode-16.10",
        ),
        (
            "* Label: macOS Tahoe 26.1-25B78\n* Label: Command Line Tools for Xcode-16.3\n",
            "Command Line Tools for Xcode-16.3",
        ),
    ],
)
def test_select_clt_label(listing: str, expected: str) -> None:
    res = run("select-clt-label", stdin=listing)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == expected


def test_select_clt_label_reports_what_was_listed() -> None:
    res = run("select-clt-label", stdin="* Label: macOS Tahoe 26.1-25B78\n")
    assert res.returncode == 1
    assert "does not offer the Command Line Tools" in res.stderr
    assert "macOS Tahoe 26.1-25B78" in res.stderr


def test_wait_clt_label_retries_empty_catalog(tmp_path: Path) -> None:
    counter = tmp_path / "n"
    fake = tmp_path / "softwareupdate"
    fake.write_text(
        f"#!/bin/sh\nn=$(cat {counter} 2>/dev/null || echo 0); n=$((n+1)); echo $n > {counter}\n"
        'if [ "$n" -lt 3 ]; then echo "No new software available."; exit 0; fi\n'
        'echo "* Label: Command Line Tools for Xcode-16.3"\n'
    )
    fake.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "TEST_SOFTWAREUPDATE": str(fake)}
    res = run("wait-clt-label", "5", "0", env=env)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "Command Line Tools for Xcode-16.3"
    assert counter.read_text().strip() == "3"


def test_wait_clt_label_gives_up_with_output(tmp_path: Path) -> None:
    fake = tmp_path / "softwareupdate"
    fake.write_text('#!/bin/sh\necho "No new software available."\n')
    fake.chmod(0o755)
    res = run(
        "wait-clt-label", "2", "0", env={"PATH": "/usr/bin:/bin", "TEST_SOFTWAREUPDATE": str(fake)}
    )
    assert res.returncode == 1
    assert "after 2 attempts" in res.stderr
    assert "No new software available." in res.stderr


def test_refuses_to_run_outside_vm() -> None:
    # On a CI container or a physical Mac, kern.hv_vmm_present is absent or 0.
    res = run("clt")
    assert res.returncode == 1
    assert "refusing to run outside a VM" in res.stderr
