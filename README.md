# automac

Examples, guidance, and agent skills/prompts for **testing macOS targets in disposable
[Tart](https://tart.run) VMs** on Apple Silicon: launch-and-survive smoke tests on a clean
Mac, customer-realistic Gatekeeper/notarization release tests, upgrade-path tests, and
contained builds of untrusted code.

Point an agent at this repository when a project has a macOS target, or copy the
examples into the project.

## Layout

| Path | What |
| --- | --- |
| [`docs/setup.md`](docs/setup.md) | Set up a new Mac, or restore after a wipe: what is in git, what gets rebuilt. |
| [`docs/concepts.md`](docs/concepts.md) | Images, clones, sealing, limits. Start here. |
| [`docs/images.md`](docs/images.md) | Build a pinned, sealed image from an Apple IPSW with first-boot provisioning. |
| [`docs/guest-access.md`](docs/guest-access.md) | SSH options, safe remote-command quoting, file transfer, passwords. |
| [`docs/test-recipes.md`](docs/test-recipes.md) | Smoke, upgrade-path, release, manual, and in-guest build tests. |
| [`docs/isolation.md`](docs/isolation.md) | Boundary rules and the checks to run in every clone. |
| [`docs/gotchas.md`](docs/gotchas.md) | Failures already debugged once. Read before debugging. |
| [`docs/ci.md`](docs/ci.md) | Self-hosted runner setup and splitting harness vs VM tests. |
| [`docs/testing-the-harness.md`](docs/testing-the-harness.md) | Testing VM orchestration with fakes. |
| [`skills/macos-vm-testing/`](skills/macos-vm-testing/SKILL.md) | Agent skill that routes to the docs and examples. |
| [`prompts/`](prompts/) | Paste-ready prompts: add a smoke test, add a release test, debug, review. |
| [`examples/zsh/tartvm`](examples/zsh/tartvm) | Standalone zsh script: `doctor`, `image`, `test`, `status`, `clean`. |
| [`examples/python/tartvm/`](examples/python/tartvm/) | Small Python library: Tart wrapper, guest SSH, lifecycle, checks, image build, recipes. |
| [`examples/guest/provision.sh`](examples/guest/provision.sh) | In-guest provisioning template (headless CLT, pinned Homebrew pkg, seal). |
| [`examples/github-actions/`](examples/github-actions/) | Self-hosted runner workflow for VM tests. |
| [`tartvm.lock.json`](tartvm.lock.json) | Pinned Tart release (URL, SHA-256, Team ID) and macOS IPSW (URL, Apple's SHA-1). |
| [`scripts/bootstrap.sh`](scripts/bootstrap.sh) | Installs and verifies the pinned Tart, creates `.env`, sets git identity, `.venv`, skill. Safe to re-run. |
| [`tests/`](tests/) | Tests for all examples, run against fake `tart`/`ssh`/`scp`: no VM needed. |

## Quick start

Requirements: Apple Silicon Mac; macOS 27+ on host for first-boot provisioning; ~100 GB
free; `brew install uv gh`. On a new or wiped Mac, follow [docs/setup.md](docs/setup.md).

```zsh
scripts/bootstrap.sh --ipsw              # pinned Tart + macOS IPSW, .env, git identity, skill
set -a; source .env; set +a

examples/zsh/tartvm doctor
examples/zsh/tartvm image --ipsw "$TARTVM_HOME"/cache/UniversalMac_*_Restore.ipsw
examples/zsh/tartvm test path/to/MyApp.app --report build/vm-report.json
examples/zsh/tartvm clean
```

`test` clones the image, boots it with a window, verifies the boundary, copies the app in
(hash-checked), launches it in the guest's GUI session, requires it to stay alive, checks
for crash reports, writes a JSON report, and deletes the clone (`--keep` keeps it).

`tartvm image` does not download anything; `bootstrap.sh --ipsw` fetches the IPSW pinned
in `tartvm.lock.json` and checks it against Apple's SHA-1.

## Using it with an agent

- **Claude Code skill:** `scripts/install-skill.sh` (run by `bootstrap.sh`) symlinks
  `skills/macos-vm-testing` into `~/.claude/skills/` (or pass a project's
  `.claude/skills` directory). Updates to this repo then reach every project.
- **Any agent:** paste a file from [`prompts/`](prompts/), replacing `<AUTOMAC>` with the
  path to this checkout, or tell it to read [`docs/for-agents.md`](docs/for-agents.md).

## Developing this repo

```zsh
./scripts/test.sh            # lint, types, tests in Docker (docker-compose)
./scripts/test.sh --local    # same in .venv (uv sync)
```

Everything here is tested against fakes, so CI needs neither a Mac nor a VM. Skipped
tests fail the run.

## License

[MIT](LICENSE). Tart itself is licensed separately (Fair Source); check its terms for your use.
