"""The standalone zsh script, run for real against fake tart/ssh/scp binaries."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "examples/zsh/tartvm"
FAKES = ROOT / "tests/fakes/bin"
IMAGE = "tartvm-image-base"

pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is required")


class Env:
    def __init__(self, tmp: Path) -> None:
        self.state = tmp / "state"
        self.state.mkdir()
        self.home = tmp / "vmhome"
        self.vars = {
            "PATH": os.environ["PATH"],
            "HOME": str(tmp),
            "TARTVM_TART": str(FAKES / "tart"),
            "TARTVM_HOME": str(self.home),
            "TARTVM_SSH": str(FAKES / "ssh"),
            "TARTVM_SCP": str(FAKES / "scp"),
            "TARTVM_POLL": "0.05",
            "FAKE_STATE": str(self.state),
        }

    def vms(self, *names: str) -> None:
        (self.state / "vms.json").write_text(json.dumps(list(names)))

    def listed(self) -> list[str]:
        f = self.state / "vms.json"
        return json.loads(f.read_text()) if f.exists() else []

    def run(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["zsh", str(SCRIPT), *args], env={**self.vars, **extra}, capture_output=True,
            text=True, timeout=60, check=False,
        )  # fmt: skip

    def tart_calls(self) -> list[list[str]]:
        f = self.state / "calls.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def ssh_calls(self) -> list[dict[str, object]]:
        f = self.state / "ssh.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


@pytest.fixture
def app(tmp_path: Path) -> Path:
    a = tmp_path / "Demo.app"
    (a / "Contents/MacOS").mkdir(parents=True)
    (a / "Contents/MacOS/Demo").write_bytes(b"\xcf\xfa\xed\xfe")
    return a


def test_syntax() -> None:
    subprocess.run(["zsh", "-n", str(SCRIPT)], check=True)


def test_usage_without_args(env: Env) -> None:
    res = env.run()
    assert res.returncode == 2
    assert "tartvm test APP.app" in res.stderr


@pytest.mark.parametrize(
    ("unset", "extra", "message"),
    [
        ("TARTVM_HOME", {}, "TARTVM_TART and TARTVM_HOME are required"),
        (None, {"TARTVM_HOME": "relative"}, "must be absolute"),
        (None, {"TARTVM_CPUS": "0"}, "TARTVM_CPUS"),
        (None, {"TARTVM_PREFIX": "Bad-Prefix"}, "TARTVM_PREFIX"),
        (None, {"TARTVM_IMAGE": "my-own-vm"}, "refusing to manage VM"),
    ],
)
def test_config_fails_fast(
    env: Env, unset: str | None, extra: dict[str, str], message: str
) -> None:
    if unset:
        del env.vars[unset]
    res = env.run("status", **extra)
    assert res.returncode == 1
    assert message in res.stderr
    assert env.tart_calls() == []


# --------------------------------------------------------------------------- test


def test_smoke_test_passes_and_deletes_clone(env: Env, app: Path, tmp_path: Path) -> None:
    env.vms(IMAGE)
    report = tmp_path / "report.json"
    res = env.run("test", str(app), "--process", "Demo", "--seconds", "5", "--report", str(report))
    assert res.returncode == 0, res.stderr
    assert "all checks passed" in res.stdout
    data = json.loads(report.read_text())
    assert data["passed"] == 1
    assert [c["name"] for c in data["checks"]] == [
        "virtual_machine", "guest_account", "no_shared_folders", "no_passwordless_sudo",
        "no_credentials", "no_signing_identities",
        "transfer", "launch.Demo", "no_crash_report",
    ]  # fmt: skip
    assert all(c["result"] == "pass" for c in data["checks"])
    assert env.listed() == [IMAGE]
    run = next(c for c in env.tart_calls() if c[0] == "run")
    assert "--no-graphics" not in run  # GUI session needed for `open`
    assert not [a for a in run if a.startswith(("--dir", "--net-bridged", "--disk"))]
    sets = next(c for c in env.tart_calls() if c[0] == "set")
    assert "--random-mac" in sets
    calls = env.ssh_calls()
    assert all(c["n"] and not c["agent"] and c["F"] == "/dev/null" for c in calls)


@pytest.mark.parametrize(
    ("extra", "failing"),
    [
        ({"FAKE_LAUNCH": "exited"}, "launch.Demo"),
        ({"FAKE_LAUNCH": "did not start within 30s"}, "launch.Demo"),
        ({"FAKE_CRASHES": "Demo-2026-11-09-120000.ips"}, "no_crash_report"),
        ({"FAKE_CORRUPT": "1"}, "transfer"),
    ],
)
def test_smoke_test_failures(
    env: Env, app: Path, tmp_path: Path, extra: dict[str, str], failing: str
) -> None:
    env.vms(IMAGE)
    report = tmp_path / "r.json"
    res = env.run("test", str(app), "--process", "Demo", "--report", str(report), **extra)
    assert res.returncode == 1
    assert "one or more checks failed" in res.stderr
    data = json.loads(report.read_text())
    assert data["passed"] == 0
    assert {c["name"]: c["result"] for c in data["checks"]}[failing] == "fail"
    assert env.listed() == [IMAGE], "clone must be deleted even on failure"


@pytest.mark.parametrize(
    "extra",
    [
        {"FAKE_VMM": "0"},
        {"FAKE_SHARED": "1"},
        {"FAKE_IDENTITIES": "3"},
        {"FAKE_USER": "admin"},
        {"FAKE_SUDO": "1"},
        {"FAKE_CREDS": "/Users/tester/.netrc"},
    ],
)
def test_refuses_to_run_app_outside_boundary(env: Env, app: Path, extra: dict[str, str]) -> None:
    env.vms(IMAGE)
    res = env.run("test", str(app), "--process", "Demo", **extra)
    assert res.returncode == 1
    assert "boundary not established" in res.stderr
    assert not any("open -n" in " ".join(c["cmd"]) for c in env.ssh_calls())  # type: ignore[arg-type]
    assert env.listed() == [IMAGE]


def test_keep_leaves_clone(env: Env, app: Path) -> None:
    env.vms(IMAGE)
    res = env.run("test", str(app), "--process", "Demo", "--keep")
    assert res.returncode == 0, res.stderr
    assert len(env.listed()) == 2
    assert "keeping tartvm-run-" in res.stderr


def test_missing_image(env: Env, app: Path) -> None:
    res = env.run("test", str(app), "--process", "Demo")
    assert res.returncode == 1
    assert "base image tartvm-image-base is missing" in res.stderr
    assert not [c for c in env.tart_calls() if c[0] == "clone"]


def test_tart_run_exits_immediately(env: Env, app: Path) -> None:
    env.vms(IMAGE)
    (env.state / "FAKE_RUN_EXIT").touch()
    res = env.run("test", str(app), "--process", "Demo")
    assert res.returncode == 1
    assert "exited immediately" in res.stderr or "exited during boot" in res.stderr
    assert env.listed() == [IMAGE]


def test_dry_run_changes_nothing(env: Env, app: Path) -> None:
    env.vms(IMAGE)
    res = env.run("test", str(app), "--process", "Demo", "--dry-run")
    assert res.returncode == 0, res.stderr
    assert "+ tart clone tartvm-image-base tartvm-run-" in res.stdout
    assert [c[0] for c in env.tart_calls()] == []
    assert env.listed() == [IMAGE]


def test_ssh_timeout_reports_last_error(env: Env, app: Path) -> None:
    env.vms(IMAGE)
    res = env.run("test", str(app), "--process", "Demo", FAKE_SSH_DOWN="1", TARTVM_BOOT_TIMEOUT="1")
    assert res.returncode == 1
    assert "did not accept SSH" in res.stderr
    assert env.listed() == [IMAGE]


def test_rejects_non_app(env: Env, tmp_path: Path) -> None:
    res = env.run("test", str(tmp_path))
    assert res.returncode == 1
    assert ".app bundle" in res.stderr


# --------------------------------------------------------------------------- image


def test_image_build_seals_and_verifies(env: Env, tmp_path: Path) -> None:
    ipsw = tmp_path / "x.ipsw"
    ipsw.write_bytes(b"ipsw")
    res = env.run("image", "--ipsw", str(ipsw))
    assert res.returncode == 0, res.stderr + res.stdout
    assert env.listed() == [IMAGE]
    cmds = [c[0] for c in env.tart_calls()]
    assert cmds.index("create") < cmds.index("rename") < cmds.index("clone")
    first = next(c for c in env.tart_calls() if c[0] == "run")
    assert any(a.startswith("--provisioning-opts=") for a in first)
    later = [c for c in env.tart_calls() if c[0] == "run"][1]
    assert not any("provisioning" in a for a in later)
    pw = env.home / "ssh/guest-password"
    assert pw.stat().st_mode & 0o777 == 0o600
    assert len(pw.read_text().strip()) == 48
    ssh = env.ssh_calls()
    assert ssh[0]["askpass"] and not ssh[-1]["askpass"]
    # The password never appears in a logged tart argv of later boots or in ssh argv.
    assert pw.read_text().strip() not in json.dumps(ssh)


def test_image_requires_clean_power_off(env: Env, tmp_path: Path) -> None:
    ipsw = tmp_path / "x.ipsw"
    ipsw.write_bytes(b"ipsw")
    # The guest ignores shutdown: the script must fail, not force-stop and keep the image.
    res = env.run("image", "--ipsw", str(ipsw), FAKE_NO_POWEROFF="1", TARTVM_SHUTDOWN_TIMEOUT="1")
    assert res.returncode == 1
    assert "did not shut itself down" in res.stderr
    assert env.listed() == []


def test_image_dry_run(env: Env, tmp_path: Path) -> None:
    ipsw = tmp_path / "x.ipsw"
    ipsw.write_bytes(b"ipsw")
    res = env.run("image", "--ipsw", str(ipsw), "--dry-run")
    assert res.returncode == 0, res.stderr
    assert "+ tart create --from-ipsw" in res.stdout
    assert env.tart_calls() == []
    assert not (env.home / "ssh").exists()


def test_image_refuses_existing(env: Env, tmp_path: Path) -> None:
    env.vms(IMAGE)
    ipsw = tmp_path / "x.ipsw"
    ipsw.write_bytes(b"ipsw")
    res = env.run("image", "--ipsw", str(ipsw))
    assert res.returncode == 1
    assert "already exists" in res.stderr
    assert env.listed() == [IMAGE]


def test_image_failing_seal_check_is_deleted(env: Env, tmp_path: Path) -> None:
    ipsw = tmp_path / "x.ipsw"
    ipsw.write_bytes(b"ipsw")
    res = env.run("image", "--ipsw", str(ipsw), FAKE_IDENTITIES="1")
    assert res.returncode == 1
    assert "failed its boundary checks" in res.stderr
    assert env.listed() == []


# --------------------------------------------------------------------------- clean


def test_clean_only_touches_stopped_disposable_vms(env: Env) -> None:
    env.vms(IMAGE, "tartvm-run-aa11", "tartvm-provision-base", "macos-mine", "tartvm-run-bb22")
    (env.state / "running-tartvm-run-bb22").touch()
    res = env.run("clean")
    assert res.returncode == 0, res.stderr
    assert env.listed() == [IMAGE, "macos-mine", "tartvm-run-bb22"]


def test_clean_dry_run(env: Env) -> None:
    env.vms(IMAGE, "tartvm-run-aa11")
    res = env.run("clean", "--dry-run")
    assert res.returncode == 0
    assert "+ tart delete tartvm-run-aa11" in res.stdout
    assert env.listed() == [IMAGE, "tartvm-run-aa11"]
