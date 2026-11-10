# Talking to the guest

Everything goes over SSH with a key used for nothing else. The operator's SSH setup must
not leak in, and nothing the guest says is trusted without parsing.

## SSH options

```zsh
/usr/bin/env -u SSH_AUTH_SOCK /usr/bin/ssh -n -F /dev/null \
  -i "$STATE/ssh/id_ed25519" \
  -o UserKnownHostsFile="$STATE/ssh/known_hosts" -o GlobalKnownHostsFile=/dev/null \
  -o HostKeyAlias="$IMAGE" -o StrictHostKeyChecking=yes \
  -o BatchMode=yes -o IdentitiesOnly=yes \
  -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no \
  -o ForwardAgent=no -o ForwardX11=no -o ClearAllForwardings=yes -o PermitLocalCommand=no \
  -o ConnectTimeout=10 -o ServerAliveInterval=30 -o LogLevel=ERROR \
  tester@"$IP" -- "$REMOTE"
```

| Option | Why |
| --- | --- |
| `env -u SSH_AUTH_SOCK`, `ForwardAgent=no` | The guest must never reach your agent (and so your GitHub keys). |
| `-F /dev/null` | Your `~/.ssh/config` (ProxyJump, ControlMaster, IdentityFile) is ignored. |
| `HostKeyAlias=<image>` | Clones get new IPs but share the image's host key; pin it once. Forget it (`ssh-keygen -R`) when the image is rebuilt. |
| `-n` | stdin is `/dev/null`, so a guest command can never read your terminal. **Consequence:** data you pipe in is silently discarded. Pass small values as argv; copy files with `scp`. Only `sudo -S` gets stdin, deliberately. |

## Build the remote command safely

ssh sends **one string** to the guest's login shell (zsh on macOS). Build it from an
argument list and quote each element; never interpolate values into a shell snippet.

```python
remote = shlex.join(
    [
        "/usr/bin/env",
        "-i",
        "HOME=/Users/tester",
        "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG=C",
        "LC_ALL=C",
        *argv,
    ]
)
```

```zsh
local -a remote=(/usr/bin/env -i HOME=/Users/tester PATH=/usr/bin:/bin:/usr/sbin:/sbin "$@")
"$SSH" -n "${opts[@]}" tester@$IP -- "${(j: :)${(@q)remote}}"
```

Note the `@` in `${(@q)remote}`: inside double quotes, `${(q)remote}` joins the array
first and quotes the result as **one word**, so the guest runs a "command" whose name
contains spaces. The test suite here caught exactly that bug.

When you need shell logic in the guest, keep the script constant and pass values as
positional parameters:

```python
[
    "/bin/sh",
    "-c",
    'umask 077 && mkdir -p "$HOME/.ssh" && printf "%s\\n" "$1" > "$HOME/.ssh/authorized_keys"',
    "sh",
    pubkey,
]
```

`env -i` gives every guest command the same minimal environment (`LANG=C` keeps tool
output parseable), independent of shell profiles.

## Moving files

- Upload: `tar` on the host (zero uid/gid, `COPYFILE_DISABLE=1` to skip `._` files),
  hash, `scp`, then `shasum -a 256` in the guest and compare. Mismatch is a failure.
- Download: create the archive and hash it **in the guest**, `scp` it back, verify the
  hash, then extract with strict checks: no symlinks or hardlinks pointing outside, no
  device files, no absolute paths, no `..`. Treat everything from the guest as untrusted.

## Waiting

- `tart ip --wait N` returns once DHCP has a lease; sshd may not be up yet. Poll
  `ssh … /usr/bin/true` every few seconds with a deadline, and report the last SSH error
  when it expires.
- Check that the `tart run` process is still alive a few seconds after starting it;
  "exited immediately" (bad name, no disk space, VM already running) is a clear error.
- Parse `tart ip` output against an IPv4 regex before using it anywhere.

## Passwords

The guest password exists only for first boot and `sudo`. It lives in a `0600` file and
is delivered by:

- an `SSH_ASKPASS` helper (`#!/bin/sh\nexec cat -- "$PASSWORD_FILE"`) with
  `SSH_ASKPASS_REQUIRE=force` for password-auth SSH;
- stdin for `sudo -S -p ''` (that ssh call alone omits `-n`).

It never appears in an argv you log or in a remote command string.
