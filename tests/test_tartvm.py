"""The reference Python library, driven entirely by the scripted World."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from tartvm import app_test, checks, config, image
from tartvm.guest import Guest
from tartvm.lifecycle import Host, ephemeral_clone, running
from tartvm.tart import TartError, provisioning_opts
from tests.fakes.world import IP, FakeLauncher, World

IMAGE = "tartvm-image-0123456789abcdef"

# --------------------------------------------------------------------------- config


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "missing required settings: TARTVM_TART, TARTVM_HOME"),
        ({"TARTVM_TART": "tart", "TARTVM_HOME": "/x"}, "absolute"),
        ({"TARTVM_TART": "/t", "TARTVM_HOME": "/x", "TARTVM_CPUS": "0"}, "TARTVM_CPUS"),
        ({"TARTVM_TART": "/t", "TARTVM_HOME": "/x", "TARTVM_MEMORY_GB": "8g"}, "TARTVM_MEMORY_GB"),
        ({"TARTVM_TART": "/t", "TARTVM_HOME": "/x", "TARTVM_PREFIX": "My-VMs"}, "TARTVM_PREFIX"),
    ],
)
def test_config_fails_fast(env: dict[str, str], message: str) -> None:
    with pytest.raises(config.ConfigError, match=message):
        config.load(env)


def test_config_separates_tart_home(tmp_path: Path) -> None:
    s = config.load({"TARTVM_TART": "/t", "TARTVM_HOME": str(tmp_path)})
    assert s.home == tmp_path / "tart"
    assert s.ssh_dir == tmp_path / "ssh"
    assert (s.cpus, s.memory_gb, s.prefix) == (4, 8, "tartvm")


# --------------------------------------------------------------------------- tart wrapper


@pytest.mark.parametrize("name", ["macos-sequoia", "tartvm", "tartvm-run-x;rm", "other-run-1"])
def test_refuses_names_outside_prefix(host: Host, name: str) -> None:
    with pytest.raises(config.ConfigError, match="unexpected name"):
        host.tart.delete(name)


def test_run_argv_never_shares_host(host: Host) -> None:
    argv = host.tart.run_argv("tartvm-run-1")
    assert "--no-graphics" in argv
    assert "--no-clipboard" in argv
    assert not [a for a in argv if a.startswith(("--dir", "--net-bridged", "--disk"))]
    assert "--no-graphics" not in host.tart.run_argv("tartvm-run-1", graphics=True)


def test_ip_must_be_ipv4(host: Host, world: World) -> None:
    world.run = lambda *a, **k: type("R", (), {"stdout": "not-an-ip\n"})()  # type: ignore[method-assign]
    with pytest.raises(TartError, match="unexpected address"):
        host.tart.ip("tartvm-run-1", wait=5)


def test_list_rejects_garbage(host: Host, world: World) -> None:
    world.run = lambda *a, **k: type("R", (), {"stdout": "oops"})()  # type: ignore[method-assign]
    with pytest.raises(TartError, match="cannot parse"):
        host.tart.vms()


@pytest.mark.parametrize(
    ("user", "password"), [("Tester", "a" * 20), ("tester", "short"), ("tester", "a,b" * 8)]
)
def test_provisioning_opts_rejects_unsafe_values(user: str, password: str) -> None:
    with pytest.raises(config.ConfigError):
        provisioning_opts(user, password)


def test_provisioning_opts_enables_login_and_ssh() -> None:
    opts = provisioning_opts("tester", "A" * 32).split(",")
    assert "logsInAutomatically=true" in opts
    assert "enablesRemoteLogin=true" in opts


# --------------------------------------------------------------------------- guest ssh


def guest(tmp_path: Path, password_auth: bool = False) -> Guest:
    return Guest(IP, "tester", tmp_path, IMAGE, "tartvm-run-1", password_auth=password_auth)


def test_guest_command_is_isolated_and_quoted(tmp_path: Path) -> None:
    argv = guest(tmp_path).command(["/bin/echo", "a b; rm -rf /"])
    assert argv[:3] == ["/usr/bin/env", "-u", "SSH_AUTH_SOCK"]
    assert "-n" in argv  # stdin is discarded unless asked for
    assert argv[argv.index("-F") + 1] == "/dev/null"
    assert "StrictHostKeyChecking=yes" in argv
    assert "ForwardAgent=no" in argv
    remote = shlex.split(argv[-1])
    assert remote[:2] == ["/usr/bin/env", "-i"]
    assert remote[-1] == "a b; rm -rf /"


def test_guest_command_stdin_opt_in(tmp_path: Path) -> None:
    assert "-n" not in guest(tmp_path).command(["/bin/cat"], stdin=True)


def test_password_mode_uses_askpass_not_argv(tmp_path: Path) -> None:
    argv = guest(tmp_path, password_auth=True).command(["/usr/bin/true"])
    assert "SSH_ASKPASS_REQUIRE=force" in argv
    assert "-i" not in argv
    assert not any("password=" in a.lower() for a in argv)


def test_invalid_guest_ip(tmp_path: Path) -> None:
    with pytest.raises(TartError):
        Guest("192.168.64.7; reboot", "tester", tmp_path, IMAGE, "x")


# --------------------------------------------------------------------------- lifecycle


def test_clone_deleted_after_failure(host: Host, world: World) -> None:
    world.vms[IMAGE] = {}
    with pytest.raises(RuntimeError, match="boom"), ephemeral_clone(host, IMAGE):
        raise RuntimeError("boom")
    assert list(world.vms) == [IMAGE]
    assert any(c[0] == "stop" for c in world.tart_calls)


def test_clone_kept_on_request(host: Host, world: World) -> None:
    world.vms[IMAGE] = {}
    with ephemeral_clone(host, IMAGE, keep=True) as g:
        name = g.name
    assert name in world.vms


def test_clone_gets_random_mac(host: Host, world: World) -> None:
    world.vms[IMAGE] = {}
    with ephemeral_clone(host, IMAGE):
        pass
    sets = [c for c in world.tart_calls if c[0] == "set"]
    assert sets and "--random-mac" in sets[0]


def test_tart_run_exiting_immediately_fails(host: Host, world: World) -> None:
    assert isinstance(host.launcher, FakeLauncher)
    host.launcher.exit_immediately = True
    with (
        pytest.raises(TartError, match="exited immediately"),
        running(host, "tartvm-run-1", alias=IMAGE),
    ):
        pass


def test_ssh_wait_retries_then_times_out(host: Host, world: World) -> None:
    world.ssh_failures = 2
    with running(host, "tartvm-run-1", alias=IMAGE) as g:
        assert g.ip == IP
    world.ssh_failures = 10_000
    with (
        pytest.raises(TartError, match="did not accept SSH"),
        running(host, "tartvm-run-1", alias=IMAGE, boot_timeout=30),
    ):
        pass


def test_expect_power_off_fails_if_guest_stays_up(host: Host, world: World) -> None:
    with (
        pytest.raises(TartError, match="did not shut itself down"),
        running(host, "tartvm-run-1", alias=IMAGE, expect_power_off=True),
    ):
        pass


# --------------------------------------------------------------------------- checks


def test_boundary_passes_on_clean_guest(host: Host, world: World, tmp_path: Path) -> None:
    result = checks.boundary(world, guest(tmp_path), host.tart.run_argv("tartvm-run-1"))
    assert [c.result for c in result] == ["pass"] * 7
    checks.require(result)


@pytest.mark.parametrize(
    ("needle", "reply", "failing"),
    [
        ("sysctl", (0, "0\n", ""), "virtual_machine"),
        ("/usr/bin/id", (0, "admin\n", ""), "guest_account"),
        ("/bin/ls", (0, "/Volumes/My Shared Files\n", ""), "no_shared_folders"),
        ("/bin/ls", (1, "", "Operation not permitted"), "no_shared_folders"),
        ("security", (0, "1 valid identities found", ""), "no_signing_identities"),
        ("security", (1, "", "error"), "no_signing_identities"),
        ("sudo", (0, "", ""), "no_passwordless_sudo"),
        ("credentials", (0, "/Users/tester/.netrc\nauthorized_keys\n", ""), "no_credentials"),
        ("credentials", (0, "authorized_keys\nid_ed25519\n", ""), "no_credentials"),
        ("credentials", (1, "", ""), "no_credentials"),
    ],
)
def test_boundary_fails_closed(
    host: Host, world: World, tmp_path: Path, needle: str, reply: tuple[int, str, str], failing: str
) -> None:
    world.handlers[needle] = lambda _cmd: reply
    result = {c.name: c.result for c in checks.boundary(world, guest(tmp_path), [])}
    assert result[failing] == "fail"
    with pytest.raises(AssertionError, match=failing):
        checks.require(checks.boundary(world, guest(tmp_path), []))


def test_boundary_flags_shared_dirs(world: World, tmp_path: Path) -> None:
    result = checks.boundary(world, guest(tmp_path), ["tart", "run", "--dir=~/src", "vm"])
    assert result[0].result == "fail"


def test_require_rejects_empty() -> None:
    with pytest.raises(AssertionError, match="none ran"):
        checks.require([])


@pytest.mark.parametrize(
    ("reply", "result", "pid"),
    [
        ((0, "running 77\n", ""), "pass", "77"),
        ((1, "exited\n", ""), "fail", None),
        ((1, "did not start within 30s\n", ""), "fail", None),
        ((0, "", ""), "fail", None),  # silence is not success
        ((0, "running\n", ""), "fail", None),
    ],
)
def test_launch_and_survive(
    world: World, tmp_path: Path, reply: tuple[int, str, str], result: str, pid: str | None
) -> None:
    world.handlers["open -n"] = lambda _cmd: reply
    check, got = checks.launch_and_survive(world, guest(tmp_path), Path("/x/My.app"), "My")
    assert (check.result, got) == (result, pid)


def test_crash_reports(world: World, tmp_path: Path) -> None:
    g, marker = guest(tmp_path), Path("/m")
    world.handlers["/usr/bin/find"] = lambda _c: (0, "/r/My-2026.ips\n/r/Other.ips\n", "")
    assert checks.crash_reports(world, g, marker, ["My"]).result == "fail"
    world.handlers["/usr/bin/find"] = lambda _c: (1, "", "Permission denied")
    assert checks.crash_reports(world, g, marker, ["My"]).result == "fail"
    world.handlers["/usr/bin/find"] = lambda _c: (1, "", "find: x: No such file or directory")
    assert checks.crash_reports(world, g, marker, ["My"]).result == "pass"


@pytest.mark.parametrize(
    ("rc", "text", "result"),
    [
        (0, "x: accepted\nsource=Notarized Developer ID", "pass"),
        (0, "x: accepted\nsource=Apple Development", "fail"),
        (0, "x: accepted", "fail"),
        (3, "x: rejected\nsource=Unnotarized Developer ID", "fail"),
        (0, "", "fail"),
    ],
)
def test_gatekeeper_requires_notarized_developer_id(rc: int, text: str, result: str) -> None:
    assert checks.gatekeeper("g", rc, text).result == result


# --------------------------------------------------------------------------- recipes


def make_app(tmp_path: Path) -> Path:
    app = tmp_path / "My.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    (app / "Contents/MacOS/My").write_bytes(b"\xcf\xfa\xed\xfe")
    return app


def test_smoke_test_passes_and_cleans_up(host: Host, world: World, tmp_path: Path) -> None:
    world.vms[IMAGE] = {}
    result = app_test.smoke_test(host, IMAGE, make_app(tmp_path), "My")
    assert [(c.name, c.result) for c in result] == [
        ("transfer", "pass"),
        ("launch.My", "pass"),
        ("no_crash_report", "pass"),
    ]
    assert list(world.vms) == [IMAGE]
    assert "--no-graphics" not in host.launcher.started[0]  # type: ignore[attr-defined]


def test_smoke_test_detects_corrupt_transfer(host: Host, world: World, tmp_path: Path) -> None:
    world.vms[IMAGE] = {}
    world.handlers["shasum"] = lambda c: (0, "0" * 64 + f"  {c[-1]}\n", "")
    result = app_test.smoke_test(host, IMAGE, make_app(tmp_path), "My")
    assert [(c.name, c.result) for c in result] == [("transfer", "fail")]
    assert list(world.vms) == [IMAGE]


def test_smoke_test_refuses_unbounded_guest(host: Host, world: World, tmp_path: Path) -> None:
    world.vms[IMAGE] = {}
    world.handlers["sysctl"] = lambda _c: (0, "0\n", "")
    with pytest.raises(AssertionError, match="virtual_machine"):
        app_test.smoke_test(host, IMAGE, make_app(tmp_path), "My")
    assert not any("open -n" in " ".join(c) for c in world.remote)
    assert list(world.vms) == [IMAGE]


def test_release_test(host: Host, world: World, tmp_path: Path) -> None:
    world.vms[IMAGE] = {}
    dmg = tmp_path / "My.dmg"
    dmg.write_bytes(b"dmg")
    result = app_test.release_test(host, IMAGE, dmg, "My.app", "My")
    assert all(c.result == "pass" for c in result), result
    assert [c.name for c in result] == [
        "quarantine.present",
        "gatekeeper.dmg",
        "quarantine.present",
        "gatekeeper.app",
        "launch.My",
        "no_crash_report",
    ]


# --------------------------------------------------------------------------- image


def test_image_name_tracks_inputs() -> None:
    a = image.image_name("tartvm", {"ipsw": "x", "script": "1"})
    assert a == image.image_name("tartvm", {"script": "1", "ipsw": "x"})
    assert a != image.image_name("tartvm", {"ipsw": "x", "script": "2"})
    assert a.startswith("tartvm-image-")


def test_create_image_seals_and_verifies(host: Host, world: World, tmp_path: Path) -> None:
    worked: list[str] = []
    image.create_image(host, IMAGE, tmp_path / "x.ipsw", work=lambda g: worked.append(g.name))
    assert list(world.vms) == [IMAGE]
    assert worked == ["tartvm-provision-0123456789abcdef"]
    first_boot = host.launcher.started[0]  # type: ignore[attr-defined]
    assert any(a.startswith("--provisioning-opts=") for a in first_boot)
    assert not any("--provisioning" in a for a in host.launcher.started[1])  # type: ignore[attr-defined]
    pw = (host.settings.ssh_dir / "guest-password").stat().st_mode & 0o777
    assert pw == 0o600


def test_create_image_deletes_partial_on_failure(host: Host, world: World, tmp_path: Path) -> None:
    def boom(_g: Guest) -> None:
        raise RuntimeError("provisioning failed")

    with pytest.raises(RuntimeError, match="provisioning failed"):
        image.create_image(host, IMAGE, tmp_path / "x.ipsw", work=boom)
    assert world.vms == {}


def test_create_image_requires_clean_power_off(host: Host, world: World, tmp_path: Path) -> None:
    world.shutdown_on_seal = False
    with pytest.raises(TartError, match="did not shut itself down"):
        image.create_image(host, IMAGE, tmp_path / "x.ipsw")
    assert world.vms == {}


def test_create_image_deletes_image_failing_seal_check(
    host: Host, world: World, tmp_path: Path
) -> None:
    world.handlers["/usr/bin/security"] = lambda _c: (0, "2 valid identities found", "")
    with pytest.raises(AssertionError, match="no_signing_identities"):
        image.create_image(host, IMAGE, tmp_path / "x.ipsw")
    assert world.vms == {}
