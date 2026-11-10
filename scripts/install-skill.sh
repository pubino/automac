#!/bin/zsh
# Symlink the macos-vm-testing skill into a Claude Code skills directory.
#   scripts/install-skill.sh [SKILLS_DIR] [--dry-run]   default SKILLS_DIR: ~/.claude/skills
# A symlink (not a copy) keeps every project on the current version of this repo, and lets
# the skill find docs/ and examples/ two directories above its SKILL.md. Safe to re-run.
set -euo pipefail

dest="$HOME/.claude/skills"; dry=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry=1 ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    -*) print -u2 "unknown option: $arg"; exit 2 ;;
    *) dest="$arg" ;;
  esac
done

src="${0:A:h:h}/skills/macos-vm-testing"
link="$dest/macos-vm-testing"
[[ -f "$src/SKILL.md" ]] || { print -u2 "missing $src/SKILL.md"; exit 1; }

if [[ -L "$link" && "${link:A}" == "$src" ]]; then
  print "already installed: $link -> $src"; exit 0
fi
[[ -e "$link" || -L "$link" ]] && { print -u2 "$link exists and is not this skill; remove it first"; exit 1; }

if (( dry )); then print "+ mkdir -p $dest"; print "+ ln -s $src $link"; exit 0; fi
mkdir -p "$dest"
ln -s "$src" "$link"
print "installed: $link -> $src"
