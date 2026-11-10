# Gotchas (learned the hard way)

Each of these cost a debugging session. Most now have a regression test in this repo.

1. **`tart stop` can lose the guest's last writes.** It presses the virtual power button;
   macOS may answer with a dialog, and Tart cuts power after its timeout. A sealing step
   that removed passwordless sudo was lost this way. Seal by running
   `rm … && sync && shutdown -h now` **as one root command in the guest**, then wait for
   `tart run` to exit on its own. Then verify the seal in a fresh clone.

2. **The software update catalog is empty right after first boot.** `softwareupdate
   --list` may not offer the Command Line Tools for several minutes. Retry (e.g. 20 × 30 s)
   and include softwareupdate's own output in the error.

3. **The Command Line Tools label format changes.** It went from
   `Command Line Tools for Xcode-16.3` to `Command Line Tools for Xcode 27.2-27.2`. Parse the
   version after the last hyphen; don't match a fixed pattern.

4. **`ssh -n` discards stdin.** A step that piped a file into `tee` in the guest wrote an
   empty file and the build carried on. Pass values as argv (or `scp` a file) and verify
   what was written.

5. **zsh `${(q)array}` inside double quotes quotes the joined string.** Use
   `"${(j: :)${(@q)array}}"`.

6. **`tart ip` succeeding ≠ SSH ready.** Poll a no-op command.

7. **`open` over SSH needs a logged-in GUI session.** Provision with
   `logsInAutomatically=true` and boot the clone with graphics.

8. **Clones share a MAC address unless you ask otherwise.** `tart set --random-mac` on
   every clone, or two concurrent clones fight over one DHCP lease.

9. **Every clone has the image's SSH host key.** Pin it under `HostKeyAlias=<image>`;
   when the image is rebuilt, `ssh-keygen -R <image>` before first contact.

10. **Two macOS VMs at most.** A third `tart run` fails. Serialize, or queue in CI.

11. **`spctl` says "accepted" for more than notarized builds.** Require
    `source=Notarized Developer ID` as well.

12. **`cp` out of a mounted DMG may drop quarantine.** Finder would propagate it;
    re-apply it before assessing the installed app.

13. **`tr -dc … </dev/urandom | head -c N` fails under `set -o pipefail`** (SIGPIPE in
    `tr`). Use `od -An -N<bytes> -tx1 /dev/urandom`.

14. **`$0` inside a zsh function is the function's name.** Capture `${0:A}` at top level.

15. **Under `env -i`, your test doubles see no test environment.** Design fakes to find
    their state from something the code passes on purpose (here: `TART_HOME`).

16. **Ctrl-C can kill `tart run` mid-write.** Start it in its own session
    (`start_new_session=True`) and stop it from your cleanup handler.

17. **Fetched toolchain refs move.** Pin by commit hash; a maintenance branch name is
    not a pin.
