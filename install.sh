#!/bin/bash
# Keep all execution inside main: a truncated curl/gh download must not run.
set -euo pipefail

say() { printf '%s\n' "$*"; }
fail() { say "ERROR: $*" >&2; return 1; }
have() { command -v "$1" >/dev/null 2>&1; }

preflight() {
    local failures=0 version major available ancestor tool repo
    say 'Checking this Mac before installing anything…'
    if [[ -d "$INSTALL_ROOT" && -n "$(ls -A "$INSTALL_ROOT")" && ! -f "$INSTALL_ROOT/.trybox-install" ]]; then
        say "[FAIL] Refusing to use a nonempty directory not owned by this installer: $INSTALL_ROOT"
        failures=$((failures + 1))
    fi
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
    ancestor=$INSTALL_ROOT
    while [[ ! -e "$ancestor" ]]; do ancestor=$(dirname "$ancestor"); done
    if [[ -d "$ancestor" && -w "$ancestor" ]]; then
        say "[OK] Install location: $INSTALL_ROOT"
    else
        say "[FAIL] Install location is not writable: $INSTALL_ROOT"
        failures=$((failures + 1))
    fi
    available=$(df -Pk "$ancestor" | awk 'NR==2 {print $4}')
    if [[ "$available" =~ ^[0-9]+$ ]] && (( available >= 12582912 )); then
        say '[OK] At least 12 GiB free for source builds and the guest image'
    else
        say '[FAIL] Free at least 12 GiB on the install volume for this source installer.'
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
    for tool in uv container cargo rustup aarch64-linux-musl-gcc; do
        if have "$tool"; then say "[OK] $tool"; else say "[INSTALL] $tool"; fi
    done
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
    export PATH="$PATH:$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin"
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
    if [[ -n "$source_dir" && ! -f "$source_dir/pyproject.toml" ]]; then
        fail "Not a trybox source directory: $source_dir"; return 1
    fi
    preflight
    (( check_only )) && return 0
    mkdir -p "$INSTALL_ROOT"
    printf 'trybox installer v1\n' > "$INSTALL_ROOT/.trybox-install"
    if [[ -z "$source_dir" ]]; then
        mkdir -p "$INSTALL_ROOT/src"
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
    bash "$source_dir/scripts/install-runtime.sh" "$source_dir"
}

main "$@"
