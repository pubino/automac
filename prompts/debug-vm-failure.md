# Prompt: debug a failing VM test

Replace `<AUTOMAC>`.

---

A Tart VM test in this project is failing. Before changing code:

1. Read `<AUTOMAC>/docs/gotchas.md` and say which entries could match the symptom.
2. Show me the failing check(s) from the JSON report and the tail of the `tart run` log
   (in the harness state directory's `logs/`).
3. If it's not obvious, re-run with `--keep`, then SSH into the kept clone using exactly
   the options the harness uses (see `<AUTOMAC>/docs/guest-access.md`) and inspect:
   `~/Library/Logs/DiagnosticReports`, `log show --last 5m --predicate 'process == "<exe>"'`,
   the extracted bundle, quarantine attributes, `spctl` output.
4. Fix by first writing a harness test (against fakes) that reproduces the failure.
5. Delete the kept clone when done (`clean`).

Never "fix" a failing check by loosening it to pass on empty or unparsed output.
