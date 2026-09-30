#!/bin/bash
set -euo pipefail
main() {
    local root=${TRYBOX_INSTALL_ROOT:-"$HOME/.local/share/trybox"}
    if [[ ! -x "$root/venv/bin/python" ]]; then
        printf 'No installed trybox found at %s\n' "$root"
        return 0
    fi
    export TRYBOX_INSTALL_ROOT="$root"
    "$root/venv/bin/python" -m trybox.runtime uninstall "$@"
}
main "$@"
