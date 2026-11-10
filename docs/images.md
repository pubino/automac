# Building images

## Choose a source

| Source | Pros | Cons |
| --- | --- | --- |
| **Apple IPSW** (`tart create --from-ipsw`) | Provenance you can verify (hash from Apple's IPSW catalog); no third-party account or agent inside. | ~20 GB download; you provision everything. |
| **Prebuilt OCI image** (`tart clone ghcr.io/cirruslabs/macos-...`) | Minutes to start; Xcode variants exist; Tart guest agent installed (`tart exec` works). | Well-known default credentials (change or remove them); you trust a third-party build; larger. |

For release or security-sensitive testing prefer the IPSW. For a quick local loop an OCI
image is fine, provided the test account's password and SSH keys are rotated in your
provisioning step.

## Pin everything

Keep a lock file (JSON is fine) with, for each input: version, HTTPS URL, and a hash.

- **Tart**: release tarball URL + SHA-256, plus the expected Developer ID Team ID. After
  extraction run `codesign --verify --strict`, check `TeamIdentifier=` in `codesign -dv`,
  and require `spctl --assess --type execute` to accept it. Install it under your
  project's state directory, not via Homebrew, so upgrades are deliberate.
- **IPSW**: URL and the SHA-1 Apple publishes in its IPSW catalog
  (`https://mesu.apple.com/assets/macos/com_apple_macOSIPSW/com_apple_macOSIPSW.xml`).
  Download with HTTP Range resume; verify before use; reuse a verified file.
- **Everything installed in the guest** (Homebrew `.pkg`, compilers, SDK versions): URL +
  hash, and for `.pkg` files `pkgutil --check-signature` must report Developer ID **and**
  "Notarization: trusted by the Apple notary service".

## Name images by their inputs

```python
inputs = {
    "ipsw": [url, sha1],
    "disk_gb": 80,
    "provision_sh": sha256(script),
    "tools": lock["guest"],
    "revision": 3,
}  # bump revision when the flow changes
name = f"{prefix}-image-{sha256(json.dumps(inputs, sort_keys=True))[:16]}"
```

Change any input and the next run builds a new image automatically; old ones are removed
by an explicit `clean --images`. Store a small JSON record next to each image (name,
detected tool versions, creation time) and treat "VM exists but record missing" as
incomplete: delete and rebuild.

## First boot without Setup Assistant (macOS 27+)

```zsh
tart create --from-ipsw "$IPSW" --disk-size 80 --disk-format asif "$TMP"
tart set "$TMP" --cpu 4 --memory 8192
tart run --no-graphics --no-audio \
  --provisioning-opts="fullName=Test User,username=tester,password=$PW,logsInAutomatically=true,enablesRemoteLogin=true" \
  "$TMP" &
```

- `logsInAutomatically=true` gives a GUI session, so `open App.app` over SSH works.
- `enablesRemoteLogin=true` turns on sshd.
- The options are comma-separated: validate the values (alphanumeric password of 16–64
  characters) or a comma will silently split them.
- The password is in `tart run`'s argv on that first boot. Never log that argv; keep the
  password in a `0600` file; use it only via `SSH_ASKPASS` and `sudo -S` on stdin.
- `--disk-format asif` needs a macOS 26+ host; drop it on older hosts.

## Provisioning steps

1. Wait for `tart ip --wait`, then poll `ssh … /usr/bin/true` until sshd answers.
2. Over password auth (`SSH_ASKPASS_REQUIRE=force`, `StrictHostKeyChecking=accept-new`,
   `HostKeyAlias=<image name>`), install a **dedicated** ed25519 public key. From then on
   use key auth with `StrictHostKeyChecking=yes`. Every clone shares the image's host
   key, so the pinned alias keeps working.
3. If you need root, install a temporary `NOPASSWD` sudoers drop-in, writing the password
   to `sudo -S` on stdin (validate with `visudo -cf` first).
4. Copy a guest-side script in with `scp` and run it. Make it idempotent and make it
   refuse to run outside a VM: `[ "$(sysctl -n kern.hv_vmm_present)" = 1 ] || exit 1`.
   See [`examples/guest/provision.sh`](../examples/guest/provision.sh).
5. **Seal from inside**: in one root command remove the sudoers drop-in, `sync`, and
   `shutdown -h now`. On the host, wait for the `tart run` process to exit by itself
   within a timeout; a timeout is a failure.
6. `tart rename` the provisioning VM to the image name.
7. **Verify the seal**: clone, boot, run the boundary checks (including "`sudo -n` is
   denied"). If anything fails, delete the image.

On failure delete the partial VM unless `--keep-failed` was given, and keep the log.

## Command Line Tools without a GUI

```zsh
touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
softwareupdate --list         # retry: the catalog is often empty right after first boot
softwareupdate --install "<label>" --verbose
```

The label format changed between releases ("Command Line Tools for Xcode-16.3" vs
"Command Line Tools for Xcode 27.2-27.2"): parse the version after the **last** hyphen,
sort numerically, take the newest, and when nothing matches print what *was* listed.
The example guest script does this and has a fake-`softwareupdate` hook for tests.
