from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/install-skill.sh"
SKILL = ROOT / "skills/macos-vm-testing"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["zsh", str(SCRIPT), *args], capture_output=True, text=True, timeout=30, check=False
    )


def test_skill_has_frontmatter() -> None:
    text = (SKILL / "SKILL.md").read_text()
    assert text.startswith("---\nname: macos-vm-testing\ndescription: ")


def test_skill_references_exist() -> None:
    text = (SKILL / "SKILL.md").read_text()
    for ref in [p for p in text.split("`") if p.startswith("$AUTOMAC/")]:
        assert (ROOT / ref.removeprefix("$AUTOMAC/")).exists(), ref


def test_install_is_idempotent(tmp_path: Path) -> None:
    dest = tmp_path / "skills"
    first = run(str(dest))
    assert first.returncode == 0, first.stderr
    link = dest / "macos-vm-testing"
    assert link.is_symlink()
    assert link.resolve() == SKILL.resolve()
    assert (link.resolve().parent.parent / "docs/gotchas.md").is_file()
    again = run(str(dest))
    assert again.returncode == 0
    assert "already installed" in again.stdout


def test_install_refuses_to_replace_other(tmp_path: Path) -> None:
    (tmp_path / "macos-vm-testing").mkdir()
    res = run(str(tmp_path))
    assert res.returncode == 1
    assert "not this skill" in res.stderr


def test_install_dry_run(tmp_path: Path) -> None:
    res = run(str(tmp_path / "skills"), "--dry-run")
    assert res.returncode == 0
    assert "+ ln -s" in res.stdout
    assert not (tmp_path / "skills").exists()
