#!/bin/bash
# trybox installer — checks, installs, and builds everything needed.
set -euo pipefail

say() { printf '%s\n' "$*"; }
fail() { say "ERROR: $*" >&2; return 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# install_missing: install a brew formula if not already in PATH
# ---------------------------------------------------------------------------
brew_install() {
    local formula=$1 tap=${2:-}
    if have "$formula"; then
        say "[OK] $formula"
        return 0
    fi
    if [[ -n "$tap" ]]; then
        brew tap "$tap" 2>/dev/null || true
    fi
    say "[INSTALL] brew install $formula ..."
    brew install "$formula"
}

# ---------------------------------------------------------------------------
# preflight — hard requirements (can't auto-fix these)
# ---------------------------------------------------------------------------
preflight_hard() {
    local failures=0 version major
    say 'Checking system requirements…'
    if [[ "$(uname -s)" != Darwin ]]; then
        fail 'trybox requires macOS.'; return 1
    fi
    if [[ "$(uname -m)" != arm64 ]]; then
        say '[FAIL] Apple Silicon required (not Rosetta).'
        say '       Run this installer from a native arm64 terminal, not a Rosetta shell.'
        say '       In Terminal.app: Settings > General > Shell opens with: /bin/bash (arm64)'
        failures=$((failures + 1))
    else say '[OK] Apple Silicon'; fi
    version=$(sw_vers -productVersion)
    major=${version%%.*}
    if [[ "$major" =~ ^[0-9]+$ ]] && (( major >= 26 )); then
        say "[OK] macOS $version"
    else
        say "[FAIL] macOS 26+ required; found $version."
        say "       Update: System Settings > General > Software Update"
        failures=$((failures + 1))
    fi
    if [[ "$(sysctl -n kern.hv_support 2>/dev/null || true)" == 1 ]]; then
        say '[OK] Hardware virtualization'
    else
        say '[FAIL] Hardware virtualization is unavailable.'
        say '       If running in a VM, nested virtualization may not be supported.'
        say '       If on bare metal, check for restricted mode:'
        say '         nvram boot-args  (look for "csr-active-config" or "amfi_get_out_of_my_way")'
        say '       Clearing restricted boot args requires sudo + reboot:'
        say '         sudo nvram boot-args=""'
        say '       Or skip this check if you know your hardware supports it:'
        say '         SKIP_HV_CHECK=1 bash install.sh'
        if [[ -n "${SKIP_HV_CHECK:-}" ]]; then
            say '  [SKIP] Skipping per SKIP_HV_CHECK=1'
        else
            failures=$((failures + 1))
        fi
    fi
    if (( failures )); then
        fail "$failures hard requirement(s) failed. Cannot continue."
        return 1
    fi
}

# ---------------------------------------------------------------------------
# install_deps — auto-install everything that can be installed
# ---------------------------------------------------------------------------
install_deps() {
    say ''
    say 'Installing dependencies…'

    # Homebrew (bootstrap if missing)
    if ! have brew; then
        say '[INSTALL] Homebrew …'
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv)"
    else
        say '[OK] Homebrew'
    fi

    # Apple Command Line Tools (needed by rustc/container builds)
    if ! xcode-select -p >/dev/null 2>&1; then
        say '[INSTALL] xcode-select --install …'
        xcode-select --install
        say '  Re-run this installer after the Command Line Tools finish installing.'
        return 1
    else
        say '[OK] Apple Command Line Tools'
    fi

    # container CLI
    brew_install container

    # try CLI (tobi/try)
    if have try; then
        say '[OK] try'
    else
        say '[INSTALL] brew install try …'
        brew install try
    fi

    # OpenShell
    if have openshell; then
        say '[OK] openshell'
    else
        say '[INSTALL] brew install nvidia/openshell/openshell …'
        brew tap nvidia/openshell 2>/dev/null || true
        brew install nvidia/openshell/openshell
    fi

    # openshell-gateway (comes with the openshell tap)
    if have openshell-gateway; then
        say '[OK] openshell-gateway'
    else
        say '[INSTALL] brew install nvidia/openshell/openshell-gateway …'
        brew install nvidia/openshell/openshell-gateway
    fi

    # Rust toolchain
    if have rustup; then
        say '[OK] rustup'
    else
        say '[INSTALL] rustup …'
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
        source "$HOME/.cargo/env"
    fi

    # gh CLI (needed to clone private repos)
    brew_install gh

    # musl cross-compiler (for guest binaries — needed by driver build)
    if have aarch64-linux-musl-gcc; then
        say '[OK] musl-cross'
    else
        say '[INSTALL] brew install FiloSottile/musl-cross/musl-cross …'
        brew install FiloSottile/musl-cross/musl-cross
    fi
}

# ---------------------------------------------------------------------------
# check_gh_access — verify GitHub repo access
# ---------------------------------------------------------------------------
check_gh_access() {
    say ''
    say 'Checking GitHub access…'
    if ! gh auth status >/dev/null 2>&1; then
        say '[FAIL] Not signed in to gh. Run: gh auth login'
        say '        The repos are private — you need access to potable-anarchy/trybox'
        say '        and potable-anarchy/openshell-driver-apple-container.'
        return 1
    fi
    local repo ok=0
    for repo in potable-anarchy/trybox potable-anarchy/openshell-driver-apple-container; do
        if gh api "repos/$repo" --silent >/dev/null 2>&1; then
            say "[OK] $repo"
            ok=$((ok + 1))
        else
            say "[FAIL] Cannot access $repo"
        fi
    done
    (( ok == 2 )) || return 1
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
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
                say '  --check        Run read-only checks; install nothing.'
                say '  --source PATH  Install from a local trybox checkout.'
                return 0 ;;
            *) fail "Unknown argument: $1"; return 1 ;;
        esac
    done
    [[ "$(id -u)" != 0 ]] || { fail 'Run as your normal user, without sudo.'; return 1; }

    # Hard requirements first
    preflight_hard || return 1

    if (( check_only )); then
        # In check mode, just report what's missing
        say ''
        say 'Check mode — reporting only, not installing.'
        for cmd in brew container try openshell openshell-gateway rustup gh aarch64-linux-musl-gcc; do
            if have "$cmd"; then say "[OK] $cmd"; else say "[MISSING] $cmd"; fi
        done
        return 0
    fi

    # Auto-install dependencies
    install_deps || return 1

    # Verify GitHub access
    check_gh_access || return 1

    # Clone and build
    say ''
    say 'Building trybox…'
    mkdir -p "$INSTALL_ROOT" "$HOME/.local/bin"
    if [[ -z "$source_dir" ]]; then
        source_dir="$INSTALL_ROOT/src/trybox"
        if [[ ! -e "$source_dir" ]]; then
            gh repo clone potable-anarchy/trybox "$source_dir"
        else
            [[ -z "$(git -C "$source_dir" status --porcelain)" ]] || {
                fail "Local edits in $source_dir; use --source or save them."; return 1;
            }
            git -C "$source_dir" pull --ff-only
        fi
    fi
    cargo install --path "$source_dir" --root "$HOME/.local" --locked

    say ''
    say 'Building openshell-driver-apple-container…'
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
