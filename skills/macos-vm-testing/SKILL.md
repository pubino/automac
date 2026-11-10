---
name: macos-vm-testing
description: Test a project's macOS target (.app, DMG, installer, or untrusted build) in disposable Tart VMs on Apple Silicon. Use when adding or debugging VM-based smoke tests, first-launch / Gatekeeper / notarization release tests, upgrade-path tests, or contained builds; when writing code that drives `tart`; or when the user mentions tart, tart.run, macOS VMs, golden images, or testing a Mac app on a clean machine.
---

# Testing macOS targets in Tart VMs

The reference material lives in the automac repository this skill came from. Resolve
`AUTOMAC` to that checkout (the directory two levels above this file, following
symlinks) and read files from there as needed:

| Need | Read |
| --- | --- |
| Mental model, limits (Apple Silicon, 2 VMs, macOS 27 provisioning) | `$AUTOMAC/docs/concepts.md` |
| Build a sealed image from an IPSW | `$AUTOMAC/docs/images.md`, `$AUTOMAC/examples/guest/provision.sh` |
| SSH options, quoting, file transfer | `$AUTOMAC/docs/guest-access.md` |
| Which test to write and how | `$AUTOMAC/docs/test-recipes.md` |
| Boundary checks | `$AUTOMAC/docs/isolation.md` |
| Something hangs or behaves oddly | `$AUTOMAC/docs/gotchas.md` (read this before debugging) |
| CI / self-hosted runner | `$AUTOMAC/docs/ci.md` |
| Testing the harness with fakes | `$AUTOMAC/docs/testing-the-harness.md` |
| Working code to copy | `$AUTOMAC/examples/zsh/tartvm` (standalone script), `$AUTOMAC/examples/python/tartvm/` (library), `$AUTOMAC/tests/` (fakes) |

## Workflow

1. **Decide the shape.** Most projects: build on the host, test in a clone of a *clean*
   image (`examples/zsh/tartvm test App.app`). Build in the VM only when build scripts
   are untrusted. Add the release test once there is a notarized DMG.
2. **Pick an implementation.** Small project or shell-based tooling: copy
   `examples/zsh/tartvm` into `scripts/` and adapt. Python tooling: copy the modules
   from `examples/python/tartvm/` you need. Either way copy the matching tests and fakes.
3. **Pin inputs** (Tart release + hash + Team ID, IPSW + Apple's SHA-1, guest packages)
   in a lock file and name images by a hash of their inputs.
4. **Write the harness tests first**, against fakes, including failure paths: boundary
   check fails, app exits, crash report present, transfer corrupted, guest never powers
   off. They must run in Docker / CI without a VM.
5. **Run once for real** on the user's Mac (`tartvm doctor`, `tartvm image --ipsw …`,
   `tartvm test …`) and read the JSON report. Ask before building an image: it downloads
   ~20 GB and takes a while.

## Non-negotiables

- Never pass `--dir`, `--disk`, or `--net-bridged` to `tart run`; assert it in code.
- Project-private `TART_HOME`, `TART_NO_AUTO_PRUNE=1`, and a name prefix checked before
  every mutating `tart` call. Never touch VMs outside the prefix.
- SSH with `-F /dev/null`, no agent, a VM-only key, pinned `HostKeyAlias=<image>`, `-n`
  unless stdin is deliberate. Remote commands built from argument lists and quoted.
- Seal images by shutting down from inside the guest; a guest that does not power
  itself off is a failure. Verify the seal in a fresh clone.
- Every check fails closed. Empty or unparsed output is a failure. A skipped test fails
  the run. Clones are deleted on every exit path unless `--keep` was requested.
- Passwords only in `0600` files, delivered via `SSH_ASKPASS` or `sudo -S` stdin; never
  in logged argv.
- Gatekeeper passes only with `accepted` **and** `source=Notarized Developer ID`.

## When things go wrong

Check `docs/gotchas.md` first; most failures there have been seen before. Then look at
the `tart run` log in the state directory's `logs/`, re-run with `--keep`, and SSH into
the kept clone with the same options the harness uses.
