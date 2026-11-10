# Testing the VM harness without a VM

VM orchestration is code with many failure paths (boot hangs, SSH refuses, guest lies,
cleanup skipped). Test it on every commit against fakes; reserve real-VM runs for a
self-hosted job.

## Seams

Put each external dependency behind something a test can replace:

| Dependency | Seam | Fake |
| --- | --- | --- |
| Every short command (`tart list/clone/ip`, `ssh`, `scp`) | A `Runner` with `run(argv, env, check, timeout, stdin_path)` | A scripted "world" that tracks VMs, guest files, and answers guest commands |
| Long-running `tart run` | A `Launcher` returning a process with `poll/wait/terminate` | A fake process that "powers off" when the world says so |
| Time | A `Clock` with `sleep` and `monotonic` | A clock that advances instantly |
| Binaries in shell scripts | Env vars naming `tart`, `ssh`, `scp` | Small Python scripts in `tests/fakes/bin/` |

## Rules for the fakes

- **Unknown commands fail.** A fake that returns success for anything lets a broken
  harness pass. The fakes here exit 99 / raise on anything unrecognised.
- Model state, not replies: VMs appear on `create`/`clone`, vanish on `delete`; uploads
  land in a fake guest filesystem; `shasum` hashes what was uploaded.
- Make every guest answer overridable, so each boundary check can be failed in a test.

## What to test

- Config fails fast on missing / relative / out-of-range values; nothing touches Tart.
- Names outside the prefix are refused before any mutating call.
- The `tart run` argv never contains host shares; clones get `--random-mac`.
- SSH argv: `-F /dev/null`, no agent, `-n` unless stdin is requested, remote command
  quoted so hostile values stay one argument.
- Each boundary check fails on wrong output **and** on unparsed output / probe errors.
- Launch check fails on `exited`, on start timeout, and on empty output.
- Crash check fails on a matching report and on a listing error.
- Gatekeeper passes only with `source=Notarized Developer ID`.
- Clone is deleted after success, after a failed check, after an exception; kept with
  `--keep`.
- Image build: partial VM deleted on failure; guest that never powers off is a failure;
  image that fails the seal check is deleted; the password is never in later argv.
- `--dry-run` performs no mutating Tart call.
- Skipped tests fail the run (see `tests/conftest.py`): silence is not success.
