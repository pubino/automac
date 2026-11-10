# For agents

You were pointed here because a project has a macOS target to test. This repository is
reference material: read it, then make changes **in the target project**, not here.

1. Read `../skills/macos-vm-testing/SKILL.md`: it is the index and the list of rules that
   are not up for negotiation.
2. Read `gotchas.md` before writing or debugging VM code.
3. Copy from `../examples/` rather than writing from scratch, and copy the matching tests
   and fakes from `tests/`.
4. Ask the user before downloading an IPSW, building an image, or booting a VM: these
   take tens of GB and several minutes.

When changing this repository itself:

- Keep docs generic: no personal names, usernames, home paths, hostnames, emails, team
  IDs, or project names from wherever a lesson was learned.
- Every example change needs a test against the fakes; run `./scripts/test.sh --local`.
- Fix bugs by first adding a failing test. Keep refactors and behaviour changes in
  separate commits.
