"""scripts/bootstrap.sh against fake curl/codesign/spctl/gh/uv in a throwaway repo copy."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
FAKES = ROOT / "tests/fakes/bootstrap-bin"
VERSION = "2.41.1"
TEAM = "ABCDE12345"
TART_URL = f"https://example.invalid/tart/releases/download/{VERSION}/tart.tar.gz"
IPSW_URL = "https://example.invalid/ipsw/UniversalMac_27.2_TEST_Restore.ipsw"


def tart_tarball(extra: list[tuple[str, bytes]] | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data, mode in [
            ("tart.app/Contents/Info.plist", b"<plist/>", 0o644),
            ("tart.app/Contents/MacOS/tart", f"#!/bin/sh\necho {VERSION}\n".encode(), 0o755),
            *[(n, d, 0o644) for n, d in (extra or [])],
        ]:
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class Box:
    """A copy of the repo bits bootstrap needs, a fake HOME, and fake downloads."""

    def __init__(self, tmp: Path, tarball: bytes | None = None) -> None:
        self.root = tmp / "repo"
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy(ROOT / "scripts/bootstrap.sh", self.root / "scripts")
        shutil.copy(ROOT / "scripts/install-skill.sh", self.root / "scripts")
        shutil.copytree(ROOT / "skills", self.root / "skills")
        shutil.copy(ROOT / "example.env", self.root)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.home = tmp / "home"
        self.home.mkdir()
        self.downloads = tmp / "downloads"
        self.downloads.mkdir()
        self.log = tmp / "calls.log"
        self.log.touch()
        data = tarball if tarball is not None else tart_tarball()
        (self.downloads / "tart.tar.gz").write_bytes(data)
        ipsw = b"fake ipsw"
        (self.downloads / IPSW_URL.rsplit("/", 1)[-1]).write_bytes(ipsw)
        self.lock: dict[str, Any] = {
            "schema_version": 1,
            "tart": {"version": VERSION, "url": TART_URL, "team_id": TEAM,
                     "sha256": hashlib.sha256(data).hexdigest()},
            "ipsw": {"url": IPSW_URL, "sha1": hashlib.sha1(ipsw).hexdigest()},  # noqa: S324
        }  # fmt: skip
        self.write_lock()
        self.state = self.home / "tartvm-state"

    def write_lock(self) -> None:
        (self.root / "tartvm.lock.json").write_text(json.dumps(self.lock))

    def run(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{FAKES}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(self.home),
            "AUTOMAC_ROOT": str(self.root),
            "FAKE_DOWNLOADS": str(self.downloads),
            "FAKE_LOG": str(self.log),
            "FAKE_TEAM": TEAM,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            **extra,
        }
        return subprocess.run(
            ["zsh", str(self.root / "scripts/bootstrap.sh"), *args], env=env,
            capture_output=True, text=True, timeout=60, check=False,
        )  # fmt: skip

    def git(self, key: str) -> str:
        res = subprocess.run(
            ["git", "-C", str(self.root), "config", "--local", key],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        return res.stdout.strip()

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines()


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(tmp_path)


def test_syntax() -> None:
    subprocess.run(["zsh", "-n", str(ROOT / "scripts/bootstrap.sh")], check=True)


def test_repo_lock_is_well_formed() -> None:
    lock = json.loads((ROOT / "tartvm.lock.json").read_text())
    assert lock["tart"]["url"].startswith("https://")
    assert len(lock["tart"]["sha256"]) == 64
    assert len(lock["tart"]["team_id"]) == 10
    assert lock["ipsw"]["url"].startswith("https://") and lock["ipsw"]["url"].endswith(".ipsw")
    assert len(lock["ipsw"]["sha1"]) == 40


def test_fresh_machine(box: Box) -> None:
    res = box.run()
    assert res.returncode == 0, res.stderr + res.stdout
    tart = box.state / f"tools/tart-{VERSION}/tart.app/Contents/MacOS/tart"
    assert tart.is_file()
    env = (box.root / ".env").read_text()
    assert f"TARTVM_TART={tart}\n" in env
    assert f"TARTVM_HOME={box.state}\n" in env
    assert (box.root / ".env").stat().st_mode & 0o777 == 0o600
    assert box.git("user.email") == "4242+testuser@users.noreply.github.com"
    assert box.git("user.name") == "testuser"
    link = box.home / ".claude/skills/macos-vm-testing"
    assert link.is_symlink()
    assert any(c.startswith("uv sync --frozen") for c in box.calls())
    # Without --ipsw the IPSW is a visible to-do, not a silent skip.
    assert "TO DO (1)" in res.stdout
    assert "scripts/bootstrap.sh --ipsw" in res.stdout


def test_rerun_is_idempotent(box: Box) -> None:
    assert box.run().returncode == 0
    env_before = (box.root / ".env").read_text()
    downloads = [c for c in box.calls() if c.startswith("curl")]
    res = box.run()
    assert res.returncode == 0, res.stderr
    assert (box.root / ".env").read_text() == env_before
    assert [c for c in box.calls() if c.startswith("curl")] == downloads, "no second download"
    assert ".env kept" in res.stdout
    assert "git identity kept" in res.stdout
    assert "already installed" in res.stdout


def test_dry_run_changes_nothing(box: Box) -> None:
    res = box.run("--dry-run", "--ipsw")
    assert res.returncode == 0, res.stderr
    assert "dry run: nothing was changed" in res.stdout
    assert "+     download https://example.invalid/tart" in res.stdout
    assert not box.state.exists()
    assert not (box.root / ".env").exists()
    assert box.git("user.email") == ""
    assert not (box.home / ".claude").exists()
    assert box.calls() == [c for c in box.calls() if c.startswith("gh ")]


def test_existing_env_and_identity_are_never_changed(box: Box) -> None:
    custom = box.home / "elsewhere"
    (box.root / ".env").write_text(f"TARTVM_HOME={custom}\nTARTVM_TART=/old/tart\n")
    subprocess.run(
        ["git", "-C", str(box.root), "config", "user.email", "me@example.org"], check=True
    )
    res = box.run()
    assert res.returncode == 0, res.stderr
    assert (custom / f"tools/tart-{VERSION}/tart.app").is_dir()
    assert (box.root / ".env").read_text() == f"TARTVM_HOME={custom}\nTARTVM_TART=/old/tart\n"
    assert "set TARTVM_TART=" in res.stdout
    assert box.git("user.email") == "me@example.org"


def test_home_conflicting_with_env(box: Box, tmp_path: Path) -> None:
    (box.root / ".env").write_text(f"TARTVM_HOME={tmp_path}/a\n")
    res = box.run("--home", str(tmp_path / "b"))
    assert res.returncode == 1
    assert "conflicts with TARTVM_HOME" in res.stderr


def test_placeholder_env_rejected(box: Box) -> None:
    shutil.copy(box.root / "example.env", box.root / ".env")
    res = box.run()
    assert res.returncode == 1
    assert "placeholder" in res.stderr


@pytest.mark.parametrize("home", ["relative/dir", "/tmp/a;rm -rf x", "/tmp/../etc"])
def test_rejects_unsafe_home(box: Box, home: str) -> None:
    res = box.run("--home", home)
    assert res.returncode == 1
    assert "absolute path" in res.stderr


def test_ipsw_download_and_verify(box: Box) -> None:
    res = box.run("--ipsw")
    assert res.returncode == 0, res.stderr
    ipsw = box.state / "cache" / IPSW_URL.rsplit("/", 1)[-1]
    assert ipsw.read_bytes() == b"fake ipsw"
    assert "nothing left to do" in res.stdout
    assert any("-C -" in c and IPSW_URL in c for c in box.calls())


def test_ipsw_hash_mismatch(box: Box) -> None:
    box.lock["ipsw"]["sha1"] = "0" * 40
    box.write_lock()
    res = box.run("--ipsw")
    assert res.returncode == 1
    assert "IPSW incomplete or wrong" in res.stderr
    assert not (box.state / "cache" / IPSW_URL.rsplit("/", 1)[-1]).exists()


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"FAKE_TEAM": "ZZZZZ99999"}, "signed by Team 'ZZZZZ99999'"),
        ({"FAKE_SPCTL_REJECT": "1"}, "Gatekeeper rejects"),
        ({"FAKE_CODESIGN_RC": "1"}, "codesign rejects"),
        ({"FAKE_CURL_FAIL": "1"}, "download failed"),
        ({"FAKE_ARCH": "x86_64"}, "Apple Silicon"),
    ],
)
def test_verification_failures(box: Box, extra: dict[str, str], message: str) -> None:
    res = box.run(**extra)
    assert res.returncode == 1
    assert message in res.stderr
    assert not (box.root / ".env").exists(), "must stop before later steps"


def test_tart_hash_mismatch_leaves_nothing(box: Box) -> None:
    box.lock["tart"]["sha256"] = "f" * 64
    box.write_lock()
    res = box.run()
    assert res.returncode == 1
    assert "SHA-256 mismatch" in res.stderr
    assert not list((box.state / "cache").iterdir())
    assert not (box.state / "tools" / f"tart-{VERSION}").exists()


def test_unsafe_archive_rejected(tmp_path: Path) -> None:
    box = Box(tmp_path, tart_tarball(extra=[("../escape", b"x")]))
    res = box.run()
    assert res.returncode == 1
    assert "unsafe path in Tart archive" in res.stderr
    assert not (tmp_path / "escape").exists()
    assert not (box.state / "tools" / f"tart-{VERSION}").exists()


def test_without_gh_auth_identity_is_a_todo(box: Box) -> None:
    res = box.run(FAKE_GH_AUTH_RC="1")
    assert res.returncode == 0, res.stderr
    assert box.git("user.email") == ""
    assert "commits here use your global identity" in res.stdout


def test_old_macos_is_a_todo(box: Box) -> None:
    res = box.run(FAKE_MACOS="26.4")
    assert res.returncode == 0, res.stderr
    assert "needs macOS 27+" in res.stdout


def test_missing_optional_tools_are_todos(box: Box, tmp_path: Path) -> None:
    bare = tmp_path / "bare-bin"
    bare.mkdir()
    for name in ("curl", "codesign", "spctl", "uname", "sw_vers", "gh"):
        (bare / name).symlink_to(FAKES / name)
    res = subprocess.run(
        ["zsh", str(box.root / "scripts/bootstrap.sh"), "--dry-run"],
        env={"PATH": f"{bare}:/usr/bin:/bin", "HOME": str(box.home), "AUTOMAC_ROOT": str(box.root),
             "FAKE_LOG": str(box.log), "FAKE_TEAM": TEAM, "GIT_CONFIG_GLOBAL": "/dev/null"},
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert "install uv" in res.stdout
    assert "Docker Desktop" in res.stdout
    assert res.returncode == 0, res.stderr
