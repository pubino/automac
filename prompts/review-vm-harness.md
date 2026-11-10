# Prompt: review a project's VM harness

Replace `<AUTOMAC>`.

---

Review this project's Tart VM test harness against `<AUTOMAC>/docs/isolation.md`,
`<AUTOMAC>/docs/guest-access.md`, and the non-negotiables in
`<AUTOMAC>/skills/macos-vm-testing/SKILL.md`. For each item report pass / fail with
file:line evidence:

- `tart run` argv can never contain `--dir`, `--disk`, `--net-bridged` (asserted in code).
- Private `TART_HOME`, `TART_NO_AUTO_PRUNE=1`, prefix check before every mutating call.
- SSH: `-F /dev/null`, no agent, VM-only key, `HostKeyAlias`, `StrictHostKeyChecking=yes`
  after bootstrap, `-n` by default, remote command quoted from an argv.
- Passwords never in logged argv or remote strings.
- Images sealed by in-guest shutdown; host waits for power-off; seal verified in a clone.
- Every check fails closed; empty output fails; skipped tests fail the run.
- Clones deleted on every exit path; `--keep` is opt-in.
- Inputs pinned and hash-verified; image names derived from inputs.
- Files crossing the boundary are hashed on both sides; archives from the guest are
  extracted with strict checks.
- Harness tests run against fakes in CI, covering failure paths.

Then list the gotchas from `<AUTOMAC>/docs/gotchas.md` the harness is still exposed to.
