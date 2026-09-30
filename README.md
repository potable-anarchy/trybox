# trybox

Create a dated experiment directory and an OpenShell sandbox on an Apple Silicon
Mac. Each sandbox runs in its own Apple Container Linux VM. Docker is not required.

## Install

The repositories are currently private, so use your authenticated GitHub CLI:

```sh
gh api repos/potable-anarchy/trybox/contents/install.sh -H 'Accept: application/vnd.github.raw' | bash
```

Run **only the system checks**, without installing anything:

```sh
gh api repos/potable-anarchy/trybox/contents/install.sh -H 'Accept: application/vnd.github.raw' | bash -s -- --check
```

Requirements checked before installation:

- Apple Silicon, running natively rather than through Rosetta.
- macOS 26 or later, with hardware virtualization available.
- Apple Command Line Tools (`xcode-select --install`).
- Homebrew and an authenticated `gh` with access to both trybox repositories
  (`brew install gh`, then `gh auth login`).
- A writable installation directory and at least 12 GiB free for source builds,
  dependencies, and the guest image.

The installer adds missing `uv`, Apple Container, OpenShell, Rust, and the ARM
Linux cross-compiler. It builds the pinned driver, macOS supervisor, and Linux
runtime; installs the CLI and image; creates private TLS certificates; and starts
two user launchd services. The first installation takes several minutes.

Installation lives in `~/.local/share/trybox`, with a launcher at
`~/.local/bin/trybox`. Add `~/.local/bin` to your shell's PATH if needed. Existing
OpenShell gateways and shared tools are kept separate from trybox's gateway on
`https://127.0.0.1:17691`.

From a local checkout:

```sh
bash install.sh --check
bash install.sh --source "$PWD"
```

`TRYBOX_INSTALL_ROOT` can override the installation directory. Rerun the installer
to retry a failed installation. It refuses to overwrite an unrelated command,
unowned nonempty directory, or edited managed checkout.

## Use

```sh
trybox doctor
trybox my first idea
trybox list
trybox --agent /usr/bin/my-agent another idea
trybox rm my-first-idea --keep-dir
```

The supplied image opens Bash. An agent must be installed in your chosen guest
image and permitted by its policy before selecting it with `--agent`.

The default policy permits read-only HTTPS to GitHub, PyPI, and npm for explicitly
listed binaries. Other network access is denied. The driver enforces an IPv4/IPv6
network firewall before dropping all capabilities; OpenShell mediates workload
network requests through its authenticated supervisor connection.

Use `trybox services start` or `trybox services stop` to manage the local services.
Logs are under `~/.local/share/trybox/logs`. `trybox openshell ...` runs an OpenShell
command against trybox's private gateway, for example:

```sh
trybox openshell sandbox download SANDBOX_NAME /sandbox ./export
```

**Current limits:** the dated host directories are project records; sandbox files
live in Apple Container volumes, without automatic host-directory synchronization.
Export files before deleting a sandbox. Fresh sandbox creation, execution, HTTPS
policy enforcement, and deletion are tested. Recovery of existing sandboxes after
a driver restart and credential refresh on stop/start are not yet supported
reliably; do not rely on them for preserving a running session.

## Uninstall

Preview what will be removed:

```sh
trybox uninstall
```

Perform the uninstall:

```sh
trybox uninstall --yes
```

If `trybox` is not on PATH:

```sh
gh api repos/potable-anarchy/trybox/contents/uninstall.sh -H 'Accept: application/vnd.github.raw' | bash -s -- --yes
```

Uninstall stops trybox's containers and removes its two launchd services, launcher,
virtual environment, binaries, assets, source checkouts, and build files. It keeps
your project directories, sandbox containers/volumes/images, TLS certificates, and
runtime state. It does not uninstall Homebrew, Rust, OpenShell, `uv`, or Apple
Container, and does not stop unrelated containers. Reinstall can reuse retained
state; existing sandbox recovery remains subject to the lifecycle limits above.

## Development checks

```sh
python3 -m unittest discover -s tests -v
bash -n install.sh uninstall.sh scripts/install-runtime.sh
python3 scripts/smoke-test.py
```

The smoke test requires an installed, running runtime. It creates and deletes its
own uniquely named sandbox and checks uid/capabilities, file writes, approved
HTTPS, blocked direct-IP egress, and blocked unlisted hosts.

MIT license.
