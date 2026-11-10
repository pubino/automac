from __future__ import annotations

from pathlib import Path

import pytest

from tartvm import config
from tartvm.lifecycle import Host
from tartvm.tart import Clock, Tart
from tests.fakes.world import FakeClock, FakeLauncher, World


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def host(tmp_path: Path, world: World) -> Host:
    fake_clock = FakeClock()
    settings = config.load({"TARTVM_TART": "/opt/tart/tart", "TARTVM_HOME": str(tmp_path / "vm")})
    return Host(
        runner=world,
        tart=Tart(world, settings),
        settings=settings,
        guest_user="tester",
        logs=tmp_path / "logs",
        launcher=FakeLauncher(world),
        clock=Clock(sleep=fake_clock.sleep, monotonic=fake_clock.monotonic),
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """A skipped test is not a passed test: fail the run if anything was skipped."""
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None and reporter.stats.get("skipped"):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
