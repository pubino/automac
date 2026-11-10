# CI

GitHub-hosted macOS runners are themselves VMs and cannot run nested macOS guests, so
VM tests run on **your** Apple Silicon Mac, either locally or as a self-hosted runner.
Split the suite in two:

| Job | Where | What |
| --- | --- | --- |
| Unit / harness tests | Any runner, in Docker | The orchestration code against fakes (this repo's `tests/`). Fast, required on every PR. |
| VM tests | Self-hosted Apple Silicon runner (labels `self-hosted, macOS, ARM64, tart`) | Build image if missing, smoke test, release test. |

## Self-hosted runner notes

- Run the runner as a dedicated macOS user with no signing identities or personal
  credentials. Give it its own `TART_HOME`.
- Use a job `concurrency` group so at most two VM jobs run at once on one Mac (the
  macOS-guest limit); one is safer if jobs boot two VMs each.
- Cache the verified IPSW and the image across jobs: they live under the runner's
  state directory, keyed by their input hash, so a changed input rebuilds automatically.
- Clean up leftover clones at job start (`tartvm clean`) as well as at the end.
- Upload the JSON report and the `tart run` log as artifacts; they are your evidence.
- Do not run VM jobs for pull requests from forks: the runner executes their code.

See [`examples/github-actions/macos-vm-test.yml`](../examples/github-actions/macos-vm-test.yml).

## Local equivalent

```zsh
./scripts/test.sh            # unit tests in Docker (docker-compose), same as CI
./scripts/test.sh --local    # same checks in .venv
examples/zsh/tartvm test build/MyApp.app --report build/vm-report.json
```
