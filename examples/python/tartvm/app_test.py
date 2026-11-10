"""End-to-end recipes: smoke-test an .app, and the 'as a customer gets it' release test."""

from __future__ import annotations

import hashlib
import tarfile
import tempfile
from pathlib import Path

from tartvm import checks
from tartvm.checks import Check
from tartvm.lifecycle import Host, ephemeral_clone


def _tar(tree: Path, dest: Path) -> str:
    def reset(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        return info

    with tarfile.open(dest, "w") as tf:
        tf.add(tree, arcname=tree.name, filter=reset)
    return hashlib.sha256(dest.read_bytes()).hexdigest()


def smoke_test(
    host: Host, image: str, app: Path, process: str, *, seconds: int = 20, keep: bool = False
) -> list[Check]:
    """Copy `app` into a throwaway clone, launch it in the guest's GUI session, require it
    to stay alive, and require no new crash reports. The app never runs on the host."""
    runner = host.runner
    with tempfile.TemporaryDirectory() as tmp:
        tar = Path(tmp) / "app.tar"
        digest = _tar(app, tar)
        with ephemeral_clone(host, image, purpose="smoke", graphics=True, keep=keep) as guest:
            checks.require(checks.boundary(runner, guest, host.tart.run_argv(guest.name)))
            inbox = guest.home / "inbox"
            runner.run(guest.command(["/bin/mkdir", "-p", str(inbox)]))
            guest.put(runner, tar, inbox / "app.tar")
            if guest.sha256(runner, inbox / "app.tar") != digest:
                return [Check("transfer", "fail", "archive changed in transfer")]
            runner.run(
                guest.command(["/usr/bin/tar", "-xf", str(inbox / "app.tar"), "-C", str(inbox)])
            )
            marker = inbox / ".started"
            runner.run(guest.command(["/usr/bin/touch", str(marker)]))
            launch, _pid = checks.launch_and_survive(
                runner, guest, inbox / app.name, process, seconds=seconds
            )
            runner.run(guest.command(["/usr/bin/pkill", "-x", process]), check=False)
            crash = checks.crash_reports(runner, guest, marker, [process])
    return [Check("transfer", "pass", digest), launch, crash]


def release_test(
    host: Host, clean_image: str, dmg: Path, app_name: str, process: str
) -> list[Check]:
    """Notarized DMG, quarantined like a Safari download, in a clean image (no developer
    tools): Gatekeeper must accept the DMG and the installed app, and the app must run."""
    runner = host.runner
    digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
    with ephemeral_clone(host, clean_image, purpose="release", graphics=True) as guest:
        checks.require(checks.boundary(runner, guest, host.tart.run_argv(guest.name)))
        downloads, mount = guest.home / "Downloads", guest.home / "dmg"
        runner.run(guest.command(["/bin/mkdir", "-p", str(downloads), str(mount)]))
        gdmg = downloads / dmg.name
        guest.put(runner, dmg, gdmg)
        if guest.sha256(runner, gdmg) != digest:
            return [Check("transfer", "fail", "DMG changed in transfer")]
        result = [checks.quarantine_like_safari(runner, guest, gdmg)]
        res = runner.run(guest.command([*checks.spctl_args("open"), str(gdmg)]), check=False)
        result.append(checks.gatekeeper("gatekeeper.dmg", res.returncode, res.stdout + res.stderr))
        runner.run(
            guest.command(
                [
                    "/usr/bin/hdiutil",
                    "attach",
                    "-nobrowse",
                    "-readonly",
                    "-noautoopen",
                    "-mountpoint",
                    str(mount),
                    str(gdmg),
                ]
            )
        )
        installed = Path("/Applications") / app_name
        runner.run(guest.command(["/bin/cp", "-R", str(mount / app_name), str(installed)]))
        runner.run(guest.command(["/usr/bin/hdiutil", "detach", str(mount)]), check=False)
        # Finder propagates quarantine from a quarantined image; cp may not. Re-apply.
        result.append(checks.quarantine_like_safari(runner, guest, installed))
        res = runner.run(
            guest.command([*checks.spctl_args("execute"), str(installed)]), check=False
        )
        result.append(checks.gatekeeper("gatekeeper.app", res.returncode, res.stdout + res.stderr))
        marker = downloads / ".started"
        runner.run(guest.command(["/usr/bin/touch", str(marker)]))
        # A quarantined first launch may show "downloaded from the internet": allow time to
        # click Open in the VM window, or this check fails (it never silently passes).
        launch, _ = checks.launch_and_survive(runner, guest, installed, process, start_within=180)
        result.append(launch)
        runner.run(guest.command(["/usr/bin/pkill", "-x", process]), check=False)
        result.append(checks.crash_reports(runner, guest, marker, [process]))
    return result
