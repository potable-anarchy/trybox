#!/bin/bash
set -euo pipefail
umask 077

SOURCE=$(cd "$1" && pwd)
ROOT=${INSTALL_ROOT:?Run install.sh first}
export TRYBOX_INSTALL_ROOT="$ROOT"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
export HOMEBREW_NO_AUTO_UPDATE=1
source "$SOURCE/scripts/versions.env"

trap 'printf "Installation stopped. Fix the error above, then rerun install.sh.\n" >&2' ERR

# Refuse to reuse an unrelated directory or replace someone else's executable.
[[ -f "$ROOT/.trybox-install" ]] || { printf 'Missing installer ownership marker.\n' >&2; exit 1; }
LAUNCHER="$HOME/.local/bin/trybox"
if [[ -e "$LAUNCHER" || -L "$LAUNCHER" ]]; then
    if [[ ! -L "$LAUNCHER" || "$(readlink "$LAUNCHER")" != "$ROOT/bin/trybox" ]]; then
        printf 'An existing trybox command occupies %s; refusing to overwrite it.\n' "$LAUNCHER" >&2
        exit 1
    fi
fi

command -v uv >/dev/null || brew install uv
command -v container >/dev/null || brew install container
if ! command -v openshell >/dev/null || ! command -v openshell-gateway >/dev/null; then
    brew tap nvidia/openshell
    brew install nvidia/openshell/openshell
fi
if ! command -v rustup >/dev/null; then
    brew install rustup
    export PATH="/opt/homebrew/opt/rustup/bin:$PATH"
fi
if ! rustup run stable rustc --version >/dev/null 2>&1; then
    rustup toolchain install stable --profile minimal
fi
if ! rustup target list --installed --toolchain stable | grep -qx aarch64-unknown-linux-musl; then
    rustup target add aarch64-unknown-linux-musl --toolchain stable
fi
if ! command -v aarch64-linux-musl-gcc >/dev/null; then
    brew tap filosottile/musl-cross
    brew install filosottile/musl-cross/musl-cross
fi

mkdir -p "$ROOT" "$ROOT/src" "$ROOT/bin" "$ROOT/host-bin" "$ROOT/supervisor-bin" "$ROOT/assets" "$HOME/.local/bin"
chmod 700 "$ROOT"
uv venv --python 3.12 --allow-existing "$ROOT/venv"
uv pip install --python "$ROOT/venv/bin/python" "$SOURCE"
PYTHON="$ROOT/venv/bin/python"
"$PYTHON" - "$ROOT" "$LAUNCHER" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
(root / 'install.json').write_text(json.dumps({'app': 'trybox', 'root': str(root), 'launcher': sys.argv[2]}) + '\n')
PY

checkout() {
    local repo=$1 ref=$2 dest=$3
    if [[ ! -d "$dest/.git" ]]; then gh repo clone "$repo" "$dest"; fi
    if [[ -n "$(git -C "$dest" status --porcelain)" ]]; then
        printf 'Local edits in %s; refusing to overwrite them.\n' "$dest" >&2; return 1
    fi
    git -C "$dest" fetch origin "$ref"
    git -C "$dest" checkout --detach "$ref"
}
checkout NVIDIA/OpenShell "$OPENSHELL_REF" "$ROOT/src/openshell"
checkout potable-anarchy/openshell-driver-apple-container "$DRIVER_REF" "$ROOT/src/driver"

export CARGO_TARGET_DIR="$ROOT/build"
export CARGO_PROFILE_RELEASE_LTO=false
export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=aarch64-linux-musl-gcc
export CC_aarch64_unknown_linux_musl=aarch64-linux-musl-gcc
printf 'Building the macOS supervisor and ARM Linux runtime (first install takes several minutes)…\n'
(cd "$ROOT/src/openshell" && cargo +stable build --release --locked -p openshell-supervisor)
install -m 0755 "$ROOT/build/release/openshell-supervisor" "$ROOT/host-bin/"
(cd "$ROOT/src/openshell" && cargo +stable build --release --locked -p openshell-sandbox --target aarch64-unknown-linux-musl)
install -m 0755 "$ROOT/build/aarch64-unknown-linux-musl/release/openshell-sandbox" "$ROOT/supervisor-bin/"
(cd "$ROOT/src/driver" && cargo +stable build --release --locked --bin openshell-driver-apple-container)
install -m 0755 "$ROOT/build/release/openshell-driver-apple-container" "$ROOT/bin/"
(cd "$ROOT/src/driver" && cargo +stable build --release --locked --bin trybox-entrypoint --target aarch64-unknown-linux-musl)
install -m 0755 "$ROOT/build/aarch64-unknown-linux-musl/release/trybox-entrypoint" "$ROOT/supervisor-bin/"
cp -R "$SOURCE/images" "$SOURCE/policies" "$ROOT/assets/"

"$PYTHON" - "$ROOT" <<'PY'
import pathlib, shlex, sys
root = pathlib.Path(sys.argv[1])
launcher = root / 'bin/trybox'
launcher.write_text('#!/bin/sh\nexport TRYBOX_INSTALL_ROOT=' + shlex.quote(str(root)) + '\nexec ' + shlex.quote(str(root / 'venv/bin/trybox')) + ' "$@"\n')
launcher.chmod(0o755)
PY
ln -sfn "$ROOT/bin/trybox" "$LAUNCHER"
container system start
bash "$ROOT/assets/images/build.sh"
"$PYTHON" -m trybox.runtime start
"$LAUNCHER" doctor
printf '\nInstalled. Run: %s my-first-idea\n' "$LAUNCHER"
printf 'Uninstall preview: %s uninstall\n' "$LAUNCHER"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) printf 'Add ~/.local/bin to your shell PATH.\n' ;; esac
