"""Settings from the environment. Fails fast: a missing or invalid value is an error at
startup, never a silent default that points somewhere surprising."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    tart: Path  # pinned tart binary (not whatever is first on PATH)
    home: Path  # TART_HOME for this project only; never the operator's own VMs
    ssh_dir: Path  # VM-only key, known_hosts, guest password
    prefix: str  # every VM this tool manages starts with it
    cpus: int
    memory_gb: int


def _int(env: Mapping[str, str], key: str, default: int, lo: int, hi: int) -> int:
    raw = env.get(key, str(default))
    if not re.fullmatch(r"[0-9]+", raw) or not lo <= int(raw) <= hi:
        raise ConfigError(f"{key} must be an integer in [{lo}, {hi}], got {raw!r}")
    return int(raw)


def load(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    missing = [k for k in ("TARTVM_TART", "TARTVM_HOME") if not env.get(k)]
    if missing:
        raise ConfigError(f"missing required settings: {', '.join(missing)} (see example.env)")
    tart = Path(env["TARTVM_TART"])
    home = Path(env["TARTVM_HOME"])
    if not tart.is_absolute() or not home.is_absolute():
        raise ConfigError("TARTVM_TART and TARTVM_HOME must be absolute paths")
    prefix = env.get("TARTVM_PREFIX", "tartvm")
    if not re.fullmatch(r"[a-z][a-z0-9]{1,15}", prefix):
        raise ConfigError(f"TARTVM_PREFIX must be 2-16 lowercase letters/digits, got {prefix!r}")
    return Settings(
        tart=tart,
        home=home / "tart",
        ssh_dir=home / "ssh",
        prefix=prefix,
        cpus=_int(env, "TARTVM_CPUS", 4, 1, 64),
        memory_gb=_int(env, "TARTVM_MEMORY_GB", 8, 2, 256),
    )
