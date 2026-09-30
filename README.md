# trybox

`trybox "my idea"` — instant, sandboxed AI coding experiments on a Mac.

One command turns a string into:
1. a dated `try` directory (`~/src/tries/2026-09-29-my-idea`) — via [tobi/try](https://github.com/tobi/try),
2. a fresh NVIDIA `openshell` sandbox (policy-gated agent runtime),
3. backed by Apple Container ([apple/container](https://github.com/apple/container)), one lightweight VM per sandbox,
4. all plumbed through [openshell-driver-apple-container](https://github.com/potable-anarchy/openshell-driver-apple-container) — the out-of-tree UDS driver — without forking OpenShell.

Exit and the directory stays on your Mac; the sandbox can be resumed or deleted.

## Architecture

```
you@Mac $ trybox my idea
            │
            ▼
 try (creates ~/src/tries/2026-09-29-my-idea)
            │
            ▼
 openshell sandbox create --name trybox-my-idea \
                          --dir ~/src/tries/2026-09-29-my-idea \
                          --policy ~/.trybox/policies/default.yaml
            │
            ▼
 openshell-gateway (stock upstream brew/binary)
            │  --compute-driver apple-container
            │  --compute-driver-socket ~/.local/state/trybox/driver.sock
            ▼
 openshell-driver-apple-container (this repo, UDS)
            │  shells out to: container run …
            ▼
 Apple Container lightweight VM
            │  openshell-supervisor + openshell-sandbox (BoundaryArgs)
            ▼
 your agent (opencode / claude / codex) inside
```

## Requirements

- Apple Silicon Mac, macOS 26+
- `brew install container try uv` ([apple/container](https://github.com/apple/container), tobi/try, astral uv)
- OpenShell: `brew install nvidia/openshell/openshell` (or `cargo install --path` from a source build)
- The driver: `cargo install --path <path-to-openshell-driver-apple-container>`
  - In development, that path is `../openshell-driver-apple-container`

## Install

```sh
# 1) Base tooling
brew install container try uv
brew install nvidia/openshell/openshell
brew install FiloSottile/musl-cross/musl-cross   # for aarch64-linux-musl cross of trybox-entrypoint

# 2) the trybox CLI itself
git clone https://github.com/potable-anarchy/trybox ~/code/trybox
uv tool install ~/code/trybox

# 3) the apple-container driver — clone, build, install
git clone https://github.com/potable-anarchy/openshell-driver-apple-container ~/code/openshell-driver-apple-container
cd ~/code/openshell-driver-apple-container
# host supervisor (`openshell-supervisor` for macOS arm64) goes into ~/.local/share/trybox/host-bin/
# guest boundary (`openshell-sandbox` + `trybox-entrypoint`, musl static)
# goes into ~/.local/share/trybox/supervisor-bin/
make install

# 4) start everything
trybox driver start
openshell-gateway generate-certs --output-dir ~/.local/state/trybox/tls
openshell-gateway --compute-driver apple-container \
  --compute-driver-socket ~/.local/state/trybox/driver.sock \
  --name trybox

# 5) register + verify
openshell gateway add https://127.0.0.1:17671 --local --name trybox
trybox doctor
```

A Makefile (`make install`) and `trybox doctor` cover the setup once — see below.

## Usage

```sh
trybox doctor                 # preflight: deps, driver, gateway, socket, sandbox image
trybox my big new project     # create try dir + sandbox + connect (idempotent)
trybox list                   # list tryboxes with sandbox state
trybox stop my-big-project    # stop the sandbox, keep the try dir
trybox my-big-project         # resume: sandbox starts, reconnects
trybox rm my-big-project      # delete sandbox; asks before removing try dir
```

## Default policy

`trybox-default-ro-github` ships in `policies/`:
- read-only HTTPS to github.com, api.github.com, raw.githubusercontent.com, codeload, objects.githubusercontent.com
- read-only HTTPS to pypi.org + files.pythonhosted.org + registry.npmjs.org
- everything else denied

Override per-project with `.trybox/policy.yaml` in any try dir.

## License

MIT
