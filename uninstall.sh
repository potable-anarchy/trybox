#!/bin/bash
set -euo pipefail
main() {
    local root=${TRYBOX_INSTALL_ROOT:-"$HOME/.local/share/trybox"}
    local bin="$HOME/.local/bin/trybox"
    if [[ ! -x "$bin" ]]; then
        printf 'No trybox binary found at %s\n' "$bin"
        return 0
    fi
    "$bin" driver stop 2>/dev/null || true
    "$bin" gateway stop 2>/dev/null || true
    rm -f "$bin"
    rm -f "$HOME/.local/bin/openshell-driver-apple-container"
    printf 'trybox uninstalled. Kept try dirs and state in %s and %s\n' \
        "$HOME/code/tries" "$root"
}
main "$@"
