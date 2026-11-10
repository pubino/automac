# Test recipes

Each recipe runs in a fresh clone (`--random-mac`, so parallel clones don't share a DHCP
lease) that is deleted afterwards, even on failure. Every recipe starts with the
[boundary checks](isolation.md) and refuses to run the app if any fails.

## 1. Launch and survive (smoke test)

The highest-value test for any macOS target: does the bundle launch on a clean Mac and
stay up?

1. `tar` the `.app`, copy it in, verify the hash, extract to `~/inbox/`.
2. `touch ~/inbox/.started` (crash-report marker).
3. Run this in the guest via `/bin/sh -c SCRIPT sh APP PROCESS SECONDS START_WITHIN`:

   ```sh
   /usr/bin/open -n "$1" || exit 2; i=0
   while ! /usr/bin/pgrep -x "$2" >/dev/null; do /bin/sleep 2; i=$((i + 2))
     [ "$i" -lt "$4" ] || { echo "did not start within $4s"; exit 1; }; done; i=0
   while [ "$i" -lt "$3" ]; do /bin/sleep 2; i=$((i + 2))
     /usr/bin/pgrep -x "$2" >/dev/null || { echo exited; exit 1; }; done
   echo "running $(/usr/bin/pgrep -nx "$2")"
   ```

   Pass only on exit 0 **and** output exactly `running <pid>`. Empty output is a failure.
4. `pkill -x PROCESS`, then list `~/Library/Logs/DiagnosticReports` for files newer than
   the marker whose names start with your process names. Any match fails. "Directory does
   not exist" passes; any other listing error fails.

`open` needs a GUI session: the image must log the test user in automatically, and the
clone must be booted **with graphics** (omit `--no-graphics`; the window may stay
unattended). The process name is `CFBundleExecutable` from `Info.plist`.

**Extras that are cheap once this works**

- `lsof -p PID -Fn` lists dylibs actually loaded from inside the bundle: proof that your
  embedded frameworks, not stray system copies, were used.
- Read a log or trace the app writes on startup and assert the build's version/commit is
  in it, so you know you tested the binary you think you tested.

## 2. Upgrade path (existing profile)

Install the **previous release** in a clone, launch it so it creates its real profile
(databases, preferences), quit it, optionally delete the specific file a bug report
mentions, then launch the candidate against that profile with the same survive check.
No profile fixture from your own machine is copied in: the old version makes it.

## 3. Release test (as a customer gets it)

Use a **clean** image (no developer tools) and the final notarized DMG:

1. Copy the DMG to `~/Downloads`, verify its hash.
2. Quarantine it like Safari: `xattr -w com.apple.quarantine "0083;$(printf %08x $(date +%s));Safari;" X.dmg`.
3. `spctl --assess --type open --context context:primary-signature -vv X.dmg` must exit 0
   and say both `accepted` and `source=Notarized Developer ID`. "accepted" with any other
   source (e.g. Apple Development) is a **failure**.
4. `hdiutil attach -nobrowse -readonly -noautoopen -mountpoint ~/dmg X.dmg`, `cp -R` the
   app to `/Applications`, detach. Finder propagates quarantine from a quarantined image;
   `cp` may not, so re-apply it to the installed app.
5. `spctl --assess --type execute -vv /Applications/X.app`, same pass rule.
6. Launch-and-survive with a longer `START_WITHIN` (e.g. 180 s): a quarantined first
   launch can show "downloaded from the internet", which a person clicks through in the
   VM window. Unattended, that check fails loudly rather than passing.
7. Crash reports as above. Record whether developer tools are present in the guest
   (`/Library/Developer/CommandLineTools`, `brew`) in the report.

## 4. Manual checks with evidence

Some behaviour needs a human (rendering, dialogs, hardware). Boot with graphics, launch
the app, then ask y/n questions in the host terminal while the operator uses the VM
window. Record each answer and note in the same JSON report as the automated checks. A
run with questions skipped (`--automated-only`) produces a report marked incomplete; it
never satisfies a release gate.

## 5. Building in the guest

When build scripts are untrusted, build inside a clone of the toolchain image instead of
on the host: copy the prepared source tarball in (hash-checked), build, archive the
output in the guest, hash it there, copy it out, verify, extract strictly. Re-check the
guest toolchain versions against your lock and against the image's record before building.

## Reports

Write one JSON report per run: subject hash, macOS version (`sw_vers -productVersion`),
architecture, image name, and a list of `{name, kind, result, detail}`. A gate passes only
if the list is non-empty and every entry is `pass`.
