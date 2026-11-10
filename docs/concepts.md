# Concepts

[Tart](https://tart.run) drives Apple's Virtualization.framework from the command line.
On an Apple Silicon Mac it gives you real macOS guests that boot in seconds from APFS
copy-on-write clones. For testing a macOS app, that buys three things a host-only test
run cannot:

1. **A clean machine every time.** No leftover preferences, caches, keychain items, or
   developer tools from your own account. The first-launch path really is the first launch.
2. **Containment.** Untrusted or unsigned code (your candidate build, an upstream build
   script, a third-party installer) runs where it cannot see your keychain, SSH keys,
   `gh` token, or notarization credentials.
3. **Customer realism.** A notarized DMG, quarantined the way Safari quarantines a
   download, goes through Gatekeeper on a Mac without Xcode, just as it would for a user.

## The model

```
IPSW ──tart create──▶ provisioning VM ──first boot + setup + seal──▶ IMAGE (never booted again)
                                                                      │
                                         tart clone (APFS CoW, ~1 s)  ▼
                                                                  run clone ──▶ test ──▶ delete
```

| Term | Meaning |
| --- | --- |
| **Image** | A sealed, powered-off VM that is only ever cloned, never booted directly. Its name encodes a hash of every input that built it. |
| **Clone** | A throwaway copy of an image, named `<prefix>-<purpose>-<random>`, deleted after the test even on failure. |
| **Seal** | The last provisioning step: remove provisioning files and temporary privileges, `sync`, and power off **from inside the guest**. |
| **Boundary checks** | Positive evidence, gathered over SSH, that the guest is a VM with no host shares, no signing identities and no credentials. |
| **TART_HOME** | Where Tart keeps VMs. Point it at a project-private directory so your tooling can never touch the operator's own VMs. |

## Two kinds of image

| Image | Contents | Use it for |
| --- | --- | --- |
| **Clean** | macOS + one test account + SSH. Nothing else. | Smoke tests of a host-built `.app`; the final "as a customer gets it" release test. |
| **Toolchain** | Clean + Command Line Tools / Xcode / Homebrew / your compilers, pinned. | Building in the VM when build scripts are untrusted; running XCTest in the guest. |

Most projects with a macOS target need only the clean image: **build on the host, test
in the guest.** Add a toolchain image only when the build itself must be contained.

## Where the host ends

The host runs `tart`, `ssh`, `scp`, and your orchestration. The guest runs the app. Data
crosses the boundary only as files you copy explicitly, hash on both sides, and (when
coming back) extract with strict archive checks. There are no shared folders. See
[isolation.md](isolation.md).

## Hard limits worth knowing up front

- **Apple Silicon only.** Virtualization.framework runs arm64 macOS guests only.
- **Two macOS guests at once per host.** The macOS licence and the framework cap
  concurrently running macOS VMs at two. Plan CI parallelism around it.
- **Disk.** An IPSW is ~20 GB; an image allocates up to its `--disk-size` sparsely
  (30–80 GB used is typical with a toolchain). Clones only cost their changes.
- **First-boot provisioning** (`tart run --provisioning-opts`) needs macOS 27 or newer on
  **both** host and guest. On older versions use a prebuilt OCI image or click through
  Setup Assistant once (see [images.md](images.md)).
