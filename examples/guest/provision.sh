#!/bin/zsh
# Runs INSIDE the VM (never on your Mac), copied in by the host during image provisioning.
#
#   provision.sh clt                      install the newest Command Line Tools, headless
#   provision.sh brew <Homebrew.pkg>      install a pinned, notarized Homebrew pkg
#   provision.sh finish <sudoers-name>    remove provisioning files and the temporary
#                                         sudoers drop-in, sync, power off (the seal)
#
# Idempotent: each step checks whether it is already done. Add your own steps the same way.
set -euo pipefail

die() { print -ru2 -- "FAILED: $*"; exit 1; }
step() { print -r -- ""; print -r -- "== $*"; }

# Newest "Command Line Tools" label from `softwareupdate --list` on stdin. Handles both
# "Command Line Tools for Xcode-16.3" and "Command Line Tools for Xcode 27.2-27.2".
select_clt_label() {
  local listing label
  listing="$(/bin/cat)"
  label="$(print -r -- "$listing" \
    | /usr/bin/sed -n 's/^\* Label: \(Command Line Tools for Xcode.*-[0-9][0-9.]*\)$/\1/p' \
    | /usr/bin/awk -F- '{ print $NF "\t" $0 }' \
    | /usr/bin/sort -t . -k 1,1n -k 2,2n -k 3,3n \
    | /usr/bin/tail -n 1 | /usr/bin/cut -f 2-)"
  [[ -n "$label" ]] || die "softwareupdate does not offer the Command Line Tools; it listed: $(print -r -- "$listing" | { /usr/bin/grep 'Label:' || true; } | /usr/bin/tr '\n' ';')"
  print -r -- "$label"
}

# Right after first boot the catalog can be empty: retry. TEST_SOFTWAREUPDATE exists only so
# the test suite can substitute a fake.
wait_clt_label() {
  local attempts="$1" delay="$2" i out="" label
  for i in $(/usr/bin/seq 1 "$attempts"); do
    out="$("${TEST_SOFTWAREUPDATE:-/usr/sbin/softwareupdate}" --list 2>&1 || true)"
    if label="$(print -r -- "$out" | select_clt_label 2>/dev/null)"; then
      print -r -- "$label"; return 0
    fi
    (( i < attempts )) && /bin/sleep "$delay"
  done
  die "no Command Line Tools after $attempts attempts; last output: $(print -r -- "$out" | /usr/bin/tail -n 5 | /usr/bin/tr '\n' ' ')"
}

# Pure text processing; safe anywhere (used by the test suite).
case "${1:-}" in
  select-clt-label) select_clt_label; exit 0 ;;
  wait-clt-label) wait_clt_label "$2" "$3"; exit 0 ;;
esac

[[ "$(/usr/sbin/sysctl -n kern.hv_vmm_present)" == 1 ]] || die "refusing to run outside a VM"

install_clt() {
  step "Command Line Tools"
  if /usr/bin/xcode-select -p >/dev/null 2>&1; then
    print -r -- "already installed at $(/usr/bin/xcode-select -p)"; return 0
  fi
  local marker=/tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress label
  /usr/bin/touch "$marker"   # makes softwareupdate list the CLT without a GUI prompt
  label="$(wait_clt_label 20 30)"
  print -r -- "installing $label"
  /usr/bin/sudo -n /usr/sbin/softwareupdate --install "$label" --verbose
  /bin/rm -f "$marker"
  /usr/bin/xcode-select -p >/dev/null || die "Command Line Tools did not install"
}

install_brew() {
  local pkg="$1" sig
  step "Homebrew"
  [[ -x /opt/homebrew/bin/brew ]] && { /opt/homebrew/bin/brew --version | head -n 1; return 0; }
  [[ -f "$pkg" ]] || die "missing $pkg"
  sig="$(/usr/sbin/pkgutil --check-signature "$pkg")"
  [[ "$sig" == *"signed by a developer certificate issued by Apple for distribution"* ]] \
    || die "Homebrew.pkg is not Developer ID signed"
  [[ "$sig" == *"Notarization: trusted by the Apple notary service"* ]] || die "Homebrew.pkg is not notarized"
  # Non-interactive installs read the owning user from this file.
  /usr/bin/sudo -n /usr/bin/defaults write /var/tmp/.homebrew_pkg_user HOMEBREW_PKG_USER "$(/usr/bin/id -un)"
  /usr/bin/sudo -n /usr/sbin/installer -pkg "$pkg" -target /
  [[ -x /opt/homebrew/bin/brew ]] || die "Homebrew did not install"
}

finish() {
  local dropin="$1"
  [[ "$dropin" == [a-z0-9-]## ]] || die "unexpected sudoers drop-in name"
  step "seal"
  /bin/rm -rf "$HOME/provision"
  /bin/sync
  # One root command removes passwordless sudo, flushes, and powers off. The host waits for
  # the VM to stop by itself; `tart stop` could cut power before these writes land.
  exec /usr/bin/sudo -n /bin/sh -c \
    "/bin/rm -f /etc/sudoers.d/$dropin && /bin/sync && exec /sbin/shutdown -h now"
}

setopt extended_glob
case "${1:-}" in
  clt) install_clt ;;
  brew) (( $# == 2 )) || die "usage: $0 brew <Homebrew.pkg>"; install_brew "$2" ;;
  finish) (( $# == 2 )) || die "usage: $0 finish <sudoers-name>"; finish "$2" ;;
  *) die "usage: $0 clt | brew <Homebrew.pkg> | finish <sudoers-name>" ;;
esac
