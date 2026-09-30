#!/bin/bash
# Keep all execution inside main: a truncated curl/gh download must not run.
set -euo pipefail

say() { printf '%s\n' "$*"; }
fail() { say "ERROR: $*" >&2; return 1; }
have() { command -v "$1" >/dev/null 2>&1; }

preflight() {
    local failures=0 version major available ancestor tool repo
    say 'Checking this Mac before installing anything…'
    if [[ "$(uname -s)" != Darwin ]]; then
        fail 'trybox requires macOS 26 or later.' || return 1
    fi
    if [[ "$(uname -m)" != arm64 ]]; then
        say '[FAIL] Use a native Apple Silicon terminal (not Rosetta).'
        failures=$((failures + 1))
    else say '[OK] Apple Silicon'; fi
    version=$(sw_vers -productVersion)
    major=${version%%.*}
    if [[ "$major" =~ ^[0-9]+$ ]] && (( major >= 26 )); then
        say "[OK] macOS $version"
    else
        say "[FAIL] macOS 26+ required; found $version."
        failures=$((failures + 1))
    fi
    if [[ "$(sysctl -n kern.hv_support 2>/dev/null || true)" == 1 ]]; then
        say '[OK] Hardware virtualization'
    else
        say '[FAIL] Hardware virtualization is unavailable.'
        failures=$((failures + 1))
    fi
    if xcode-select -p >/dev/null 2>&1 && xcrun --find clang >/dev/null 2>&1; then
        say '[OK] Apple Command Line Tools'
    else
        say '[FAIL] Install Apple Command Line Tools: xcode-select --install'
        failures=$((failures + 1))
    fi
    if have brew; then say '[OK] Homebrew'; else
        say '[FAIL] Install Homebrew first: https://brew.sh'
        failures=$((failures + 1))
    fi
    if have container; then say '[OK] container CLI'; else
        say '[INSTALL] container CLI (brew install container)'
    fi
    if have rustup; then say '[OK] rustup'; else
        say '[FAIL] Install Rust: curl --proto =https --tlsv1.2 -sSf https://sh.rustup.rs | sh'
        failures=$((failures + 1))
    fi
    if have gh && gh auth status >/dev/null 2>&1; then
        for repo in potable-anarchy/trybox potable-anarchy/openshell-driver-apple-container; do
            if gh api "repos/$repo" --silent >/dev/null 2>&1; then
                say "[OK] GitHub access: $repo"
            else
                say "[FAIL] Cannot access $repo. Check GitHub permissions and network access."
                failures=$((failures + 1))
            fi
        done
    else
        say '[FAIL] These repos are private. Install gh and sign in: brew install gh && gh auth login'
        failures=$((failures + 1))
    fi
    if (( failures )); then
        fail "$failures prerequisite check(s) failed. No installation changes made."
        return 1
    fi
    say 'System checks passed.'
}

main() {
    local check_only=0 source_dir=''
    INSTALL_ROOT=${TRYBOX_INSTALL_ROOT:-"$HOME/.local/share/trybox"}
    export INSTALL_ROOT
    export PATH="$PATH:$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:/opt/homebrew/opt/rustup/bin"
    while (( $# )); do
        case "$1" in
            --check) check_only=1; shift ;;
            --source)
                [[ $# -ge 2 ]] || { fail '--source needs a directory'; return 1; }
                source_dir=$2; shift 2 ;;
            --help|-h)
                say 'Usage: bash install.sh [--check] [--source PATH]'
                say '  --check        Run read-only system/access checks; install nothing.'
                say '  --source PATH  Install from a local trybox checkout.'
                return 0 ;;
            *) fail "Unknown argument: $1"; return 1 ;;
        esac
    done
    [[ "$INSTALL_ROOT" == /* ]] || { fail 'TRYBOX_INSTALL_ROOT must be absolute'; return 1; }
    [[ "$(id -u)" != 0 ]] || { fail 'Run as your normal user, without sudo.'; return 1; }
    if [[ -n "$source_dir" && ! -f "$source_dir/Cargo.toml" ]]; then
        fail "Not a trybox source directory: $source_dir"
        return 1
    fi
    preflight
    (( check_only )) && return 0
    mkdir -p "$INSTALL_ROOT" "$HOME/.local/bin"
    if [[ -z "$source_dir" ]]; then
        source_dir="$INSTALL_ROOT/src/trybox"
        if [[ ! -e "$source_dir" ]]; then
            gh repo clone potable-anarchy/trybox "$source_dir"
        else
            [[ -z "$(git -C "$source_dir" status --porcelain)" ]] || {
                fail "Local edits in $source_dir; use --source or save them before updating."; return 1;
            }
            git -C "$source_dir" pull --ff-only
        fi
    fi
    # Build and install the Rust CLI
    cargo install --path "$source_dir" --root "$HOME/.local" --locked
    # Build and install the driver
    driver_dir="$INSTALL_ROOT/src/openshell-driver-apple-container"
    if [[ ! -e "$driver_dir" ]]; then
        gh repo clone potable-anarchy/openshell-driver-apple-container "$driver_dir"
    else
        git -C "$driver_dir" pull --ff-only 2>/dev/null || true
    fi
    cargo install --path "$driver_dir" --root "$HOME/.local" --locked
    say ''
    say 'trybox installed. Next:'
    say '  trybox init'
    say '  trybox driver start'
    say '  trybox gateway start'
    say '  trybox my first idea'
}

main "$@"
