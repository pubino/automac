# Prompt: add a VM smoke test to a project with a macOS target

Paste into an agent session at the root of the target project. Replace `<AUTOMAC>` with
the path to this repository.

---

This project has a macOS target. Add an automated smoke test that runs the built `.app`
in a disposable Tart VM, following `<AUTOMAC>/skills/macos-vm-testing/SKILL.md` and the
docs it points to. Read `<AUTOMAC>/docs/gotchas.md` before writing code.

1. Find how the project builds its `.app` (Xcode scheme, SwiftPM, Makefile, script) and
   where the product lands. Tell me before changing the build.
2. Copy `<AUTOMAC>/examples/zsh/tartvm` to `scripts/vm-test` (or the Python modules if
   this project's tooling is Python) and its tests and fakes. Keep the name prefix
   specific to this project.
3. Add `TARTVM_*` settings to `example.env` (gitignore `.env*`), with
   `TARTVM_HOME` outside the repo. Add a pinned Tart release (URL, SHA-256, Team ID) to
   the project's lock file, with a script step that downloads and verifies it.
4. Wire a `scripts/test.sh --vm` (or equivalent) that builds the app and runs
   `vm-test test <App>.app --report build/vm-report.json`.
5. Make the harness tests run in the existing Docker / CI test job (zsh must be installed
   in the image). They must not need a VM.
6. Do not build an image or boot a VM without asking me first. When I say go, run
   `doctor`, build the image, run the test, and show me the report.

Keep commits small: harness + tests first, then build wiring, then CI.
