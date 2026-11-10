# Isolation and boundary checks

Treat the guest as hostile once it has run the code under test. The goal is that nothing
there can reach your keychain, tokens, keys, or files, and that you have **evidence** of
that for every run, not just a configuration you believe in.

## Configuration rules

- `tart run` never gets `--dir` (host shares), `--disk` (extra disks), or `--net-bridged`.
  Assert this on the argv you build, before starting the VM.
- Default NAT networking. Consider `--net-softnet` (with `--net-softnet-block` /
  `--net-softnet-allow`) when the guest should not reach your LAN; test that your app
  still gets what it needs.
- `--no-clipboard`, `--no-audio`.
- `TART_HOME` points at a project-private directory; `TART_NO_AUTO_PRUNE=1` stops Tart
  from deleting other cached images to make room.
- Every VM name your tooling touches matches `^<prefix>-[a-z]+-[A-Za-z0-9_.-]+$`;
  anything else is refused before `tart delete` can run.
- The guest account owns no signing certificate, no Apple Account, no `gh`/git
  credentials, and, after sealing, no passwordless `sudo`.

## Checks to run in every clone

| Check | Command | Pass when |
| --- | --- | --- |
| no host shares | (host) inspect `tart run` argv | no `--dir`, `--disk`, `--net-bridged` |
| is a VM | `sysctl -n kern.hv_vmm_present` | exit 0 and output `1` |
| right account | `id -un` | the test user |
| no shared folder | `ls -d "/Volumes/My Shared Files"` | fails with "No such file" (any other error fails the check) |
| no passwordless sudo | `sudo -n /usr/bin/true` | non-zero exit |
| no signing identities | `security find-identity -v -p codesigning` | parses and reports `0 valid identities found` |
| no credential files | test for `~/.config/gh`, `~/.netrc`, `~/.git-credentials`, `~/.appstoreconnect`, `~/.ssh/*` other than `authorized_keys` | none exist |
| no notary profile | `xcrun notarytool history --keychain-profile <yours>` | non-zero exit |

Fail closed: unparsed output, a timeout, or a probe that errors is a **fail**, never a
pass. Store the check list in the run's report.

## The host side

- Run every external command as an argument list through one runner module; no
  `shell=True`, no string interpolation into shells.
- stdin is `/dev/null` by default; secrets go through files or stdin, never argv.
- Logs never contain the `tart run` argv on first boot (it carries the password), the
  password file, or tokens.
- Guest-side scripts refuse to run outside a VM (`kern.hv_vmm_present`), so an accidental
  host invocation cannot install things on your Mac.
