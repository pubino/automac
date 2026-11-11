#!/bin/zsh
# Set up, or restore after a wipe, this repository's local environment on an Apple Silicon Mac.
#
#   scripts/bootstrap.sh [--home DIR] [--ipsw] [--dry-run]
#
#   --home DIR   state directory for Tart, VMs, the VM-only SSH key and logs
#                (default: TARTVM_HOME from .env, else ~/tartvm-state)
#   --ipsw       also download the pinned macOS IPSW (~25 GB, resumable) and check its SHA-1
#   --dry-run    print what would change; change nothing
#
# Safe to re-run: each step checks whether it is already done. It never deletes anything,
# never edits an existing .env, and never replaces an existing git identity. Steps:
#   1. check the host and tools
#   2. install the Tart release pinned in tartvm.lock.json; verify SHA-256, Team ID, Gatekeeper
#   3. with --ipsw, fetch and verify the pinned IPSW
#   4. create .env from example.env if it is missing
#   5. set this clone's git identity to your GitHub noreply address if it has none
#   6. create .venv (uv sync --frozen) and install the agent skill
# Anything it cannot do is listed under "TO DO" at the end; failures exit non-zero.
set -euo pipefail
setopt extended_glob

ROOT="${AUTOMAC_ROOT:-${0:A:h:h}}"
LOCK="$ROOT/tartvm.lock.json"
ENV_FILE="$ROOT/.env"
DRY_RUN=0; WANT_IPSW=0; HOME_ARG=""
typeset -a DONE TODO

die()  { print -ru2 -- "bootstrap: $*"; exit 1; }
say()  { print -r -- "== $*"; }
done_() { DONE+=("$*"); print -r -- "   ok    $*"; }
todo() { TODO+=("$*"); print -r -- "   TODO  $*"; }
plan() { print -r -- "   +     $*"; }

while (( $# )); do
  case "$1" in
    --home) [[ $# -ge 2 ]] || die "--home needs a directory"; HOME_ARG="$2"; shift 2 ;;
    --ipsw) WANT_IPSW=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,20p' "${0:A}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

# ----------------------------------------------------------------------------- helpers
JQ=/usr/bin/jq; [[ -x "$JQ" ]] || JQ="$(command -v jq || true)"
[[ -n "$JQ" ]] || die "jq is required (ships with macOS 15+ as /usr/bin/jq)"
[[ -f "$LOCK" ]] || die "missing $LOCK"
lock() {
  local v; v="$("$JQ" -er "$1" "$LOCK")" || die "tartvm.lock.json has no $1"
  print -r -- "$v"
}
digest() {  # digest 1|256 FILE
  if command -v shasum >/dev/null; then shasum -a "$1" "$2" | cut -d' ' -f1
  else "sha${1}sum" "$2" | cut -d' ' -f1; fi
}
safe_path() { [[ "$1" == /[A-Za-z0-9/._\ -]## && "$1" != *..* ]]; }

# ----------------------------------------------------------------------------- 1. host
say "host and tools"
[[ "$(uname -m)" == arm64 ]] || die "Apple Silicon (arm64) is required; this is $(uname -m)"
macos="$(sw_vers -productVersion 2>/dev/null || echo 0)"
if (( ${macos%%.*} >= 27 )); then done_ "macOS $macos"
else todo "macOS $macos: first-boot provisioning (tartvm image) needs macOS 27+; see docs/images.md"; fi
for c in curl tar codesign spctl git; do
  command -v "$c" >/dev/null || die "required command missing: $c"
done
done_ "curl, tar, codesign, spctl, git, jq present"
for c in uv docker docker-compose gh; do
  command -v "$c" >/dev/null && continue
  case "$c" in
    uv|gh) todo "install $c: brew install $c" ;;
    *) todo "install $c (Docker Desktop provides docker and docker-compose); needed for scripts/test.sh" ;;
  esac
done

# ----------------------------------------------------------------------------- state dir
env_home=""
[[ -f "$ENV_FILE" ]] && env_home="$(sed -n 's/^TARTVM_HOME=//p' "$ENV_FILE" | tail -n 1)"
if [[ -n "$env_home" ]]; then
  [[ -z "$HOME_ARG" || "$HOME_ARG" == "$env_home" ]] \
    || die "--home $HOME_ARG conflicts with TARTVM_HOME=$env_home in .env; edit .env or drop --home"
  TH="$env_home"
else
  TH="${HOME_ARG:-$HOME/tartvm-state}"
fi
[[ "$TH" != *OPERATOR* ]] || die "TARTVM_HOME in .env still has the example placeholder; edit it"
safe_path "$TH" || die "state directory must be an absolute path of letters, digits, / . _ - and spaces: $TH"
say "state directory: $TH"

# ----------------------------------------------------------------------------- 2. tart
say "Tart"
ver="$(lock .tart.version)"; url="$(lock .tart.url)"
sha="$(lock .tart.sha256)"; team="$(lock .tart.team_id)"
[[ "$ver" == [0-9]##.[0-9]##.[0-9]## ]] || die "unexpected Tart version in lock: $ver"
[[ "$url" == https://* ]] || die "Tart URL must be HTTPS"
[[ "$sha" == [0-9a-f](#c64) && "$team" == [A-Z0-9](#c10) ]] || die "malformed Tart sha256 or team_id in lock"
app="$TH/tools/tart-$ver/tart.app"
TART_BIN="$app/Contents/MacOS/tart"

if [[ ! -d "$app" ]]; then
  tarball="$TH/cache/tart-$ver.tar.gz"
  if (( DRY_RUN )); then
    plan "download $url -> $tarball (SHA-256 $sha)"
    plan "extract to $TH/tools/tart-$ver; verify signature, Team ID $team, Gatekeeper"
  else
    mkdir -p "$TH/cache" "$TH/tools"
    if [[ ! -f "$tarball" || "$(digest 256 "$tarball")" != "$sha" ]]; then
      curl -fL --proto '=https' --retry 3 -o "$tarball.partial" "$url" || die "download failed: $url"
      got="$(digest 256 "$tarball.partial")"
      if [[ "$got" != "$sha" ]]; then
        rm -f "$tarball.partial"
        die "SHA-256 mismatch for $url: expected $sha, got $got"
      fi
      mv "$tarball.partial" "$tarball"
    fi
    tar -tzf "$tarball" | while IFS= read -r entry; do
      [[ "$entry" == /* || "$entry" == (..|../*|*/../*|*/..) ]] && die "unsafe path in Tart archive: $entry"
    done
    staging="$TH/tools/tart-$ver.partial"
    [[ ! -e "$staging" ]] || die "$staging exists from an interrupted run; inspect and remove it"
    mkdir "$staging"
    tar -xzf "$tarball" -C "$staging" --no-same-owner
    [[ -d "$staging/tart.app" ]] || die "Tart archive does not contain tart.app (left in $staging)"
    mv "$staging" "$TH/tools/tart-$ver"
  fi
fi
if [[ -d "$app" ]]; then
  codesign --verify --strict "$app" 2>/dev/null || die "codesign rejects $app"
  got_team="$(codesign -dv --verbose=2 "$app" 2>&1 | sed -n 's/^TeamIdentifier=//p')"
  [[ "$got_team" == "$team" ]] || die "$app is signed by Team '$got_team', expected $team"
  gk="$(spctl --assess --type execute -vv "$app" 2>&1)" || die "Gatekeeper rejects $app: $gk"
  [[ "$gk" == *": accepted"* && "$gk" == *"source=Notarized Developer ID"* ]] \
    || die "Gatekeeper did not report a notarized Developer ID app: $gk"
  got_ver="$("$TART_BIN" --version 2>/dev/null || true)"
  [[ "$got_ver" == "$ver" ]] || die "$TART_BIN reports version '$got_ver', expected $ver"
  done_ "Tart $ver at $TART_BIN (Team $team, notarized)"
fi

# ----------------------------------------------------------------------------- 3. ipsw
say "macOS IPSW"
ipsw_url="$(lock .ipsw.url)"; ipsw_sha="$(lock .ipsw.sha1)"
[[ "$ipsw_url" == https://*.ipsw && "$ipsw_sha" == [0-9a-f](#c40) ]] || die "malformed IPSW entry in lock"
ipsw="$TH/cache/${ipsw_url:t}"
if [[ -f "$ipsw" ]]; then
  if (( WANT_IPSW )); then
    [[ "$(digest 1 "$ipsw")" == "$ipsw_sha" ]] || die "$ipsw does not match the locked SHA-1; move it aside"
    done_ "IPSW verified at $ipsw"
  else
    done_ "IPSW present at $ipsw (verify with --ipsw)"
  fi
elif (( WANT_IPSW )); then
  if (( DRY_RUN )); then
    plan "download $ipsw_url -> $ipsw (resumable; SHA-1 $ipsw_sha)"
  else
    mkdir -p "$TH/cache"
    curl -fL --proto '=https' --retry 5 -C - -o "$ipsw.partial" "$ipsw_url" \
      || print -ru2 -- "bootstrap: curl reported an error; checking what was downloaded"
    got="$(digest 1 "$ipsw.partial")"
    [[ "$got" == "$ipsw_sha" ]] || die "IPSW incomplete or wrong (SHA-1 $got); re-run to resume"
    mv "$ipsw.partial" "$ipsw"
    done_ "IPSW downloaded and verified at $ipsw"
  fi
else
  todo "fetch the macOS IPSW (~25 GB): scripts/bootstrap.sh --ipsw"
fi

# ----------------------------------------------------------------------------- 4. .env
say ".env"
if [[ -f "$ENV_FILE" ]]; then
  env_tart="$(sed -n 's/^TARTVM_TART=//p' "$ENV_FILE" | tail -n 1)"
  if [[ "$env_tart" == "$TART_BIN" ]]; then done_ ".env kept (TARTVM_TART matches the pinned Tart)"
  else todo "set TARTVM_TART=$TART_BIN in .env (it says '$env_tart'); .env is never edited for you"; fi
elif (( DRY_RUN )); then
  plan "create .env from example.env with TARTVM_HOME=$TH and TARTVM_TART=$TART_BIN"
else
  ( umask 077
    sed -e "s|^TARTVM_TART=.*|TARTVM_TART=$TART_BIN|" -e "s|^TARTVM_HOME=.*|TARTVM_HOME=$TH|" \
      "$ROOT/example.env" >"$ENV_FILE" )
  done_ "created .env (review the optional settings)"
fi

# ----------------------------------------------------------------------------- 5. git identity
say "git identity for this clone"
if ! git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  todo "not a git clone; skipped git identity"
elif local_email="$(git -C "$ROOT" config --local user.email)"; then
  done_ "git identity kept ($local_email)"
elif command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  login="$(gh api user --jq .login)"; uid="$(gh api user --jq .id)"
  [[ "$login" == [A-Za-z0-9-]## && "$uid" == <-> ]] || die "unexpected GitHub user data: $login $uid"
  email="$uid+$login@users.noreply.github.com"
  if (( DRY_RUN )); then plan "git config --local user.name $login; user.email $email"
  else
    git -C "$ROOT" config --local user.name "$login"
    git -C "$ROOT" config --local user.email "$email"
    done_ "git identity set to $login <$email>"
  fi
else
  todo "run 'gh auth login' and re-run, or set git config --local user.email yourself; until then commits here use your global identity"
fi

# ----------------------------------------------------------------------------- 6. dev env, skill
say "Python dev environment and agent skill"
if command -v uv >/dev/null; then
  if (( DRY_RUN )); then plan "uv sync --frozen (creates .venv)"
  else (cd "$ROOT" && uv sync --frozen --quiet) && done_ ".venv synced from uv.lock"; fi
else
  todo "install uv, then run: uv sync --frozen"
fi
if (( DRY_RUN )); then "$ROOT/scripts/install-skill.sh" --dry-run | sed 's/^/   /'
else "$ROOT/scripts/install-skill.sh" | sed 's/^/   /'; DONE+=("agent skill installed"); fi

# ----------------------------------------------------------------------------- summary
print
if (( DRY_RUN )); then say "dry run: nothing was changed"; fi
if (( ${#TODO} )); then
  say "TO DO (${#TODO})"
  print -rl -- "   - "${^TODO}
else
  say "nothing left to do"
fi
print -r -- "
Next:
  set -a; source .env; set +a
  examples/zsh/tartvm doctor
  examples/zsh/tartvm image --ipsw \"$ipsw\"     # builds the base image (~30 min)
  examples/zsh/tartvm test path/to/MyApp.app"
