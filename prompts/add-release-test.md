# Prompt: add a customer-realistic release test

Use after the project produces a signed, notarized DMG. Replace `<AUTOMAC>`.

---

Add a release test that installs the notarized DMG the way a customer would, in a clean
Tart VM, following "Release test" in `<AUTOMAC>/docs/test-recipes.md`. Use the existing
VM harness in this project if there is one; otherwise start from
`<AUTOMAC>/examples/python/tartvm/app_test.py::release_test` or the zsh example.

Requirements:

- A **clean** image (test account and SSH only; no Command Line Tools, no Homebrew),
  separate from any toolchain image, named by a hash of its inputs.
- Quarantine the DMG like Safari, then require `spctl` to report `accepted` **and**
  `source=Notarized Developer ID` for both the DMG and the installed app.
- Install from the mounted image to `/Applications`, re-apply quarantine if `cp` dropped it.
- Launch-and-survive with a 180 s start window, then crash-report check.
- Optional manual questions while I use the VM window; without them the report is marked
  incomplete and cannot satisfy the release gate.
- JSON report with the DMG's SHA-256, guest macOS version, and whether developer tools
  were present.
- Tests against fakes for every failure path, including "accepted" with a non-notarized
  source.

Ask before booting a VM.
