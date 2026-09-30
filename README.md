# trybox

`trybox "my idea"` — instant, sandboxed AI coding experiments on a Mac.

One command turns a string into a dated try directory and a fresh [OpenShell](https://github.com/nvidia/openshell) sandbox backed by [Apple Container](https://github.com/apple/container). Exit and the directory stays on your Mac; the sandbox can be resumed or deleted.

trybox builds on three projects it couldn't exist without:

- **[tobi/try](https://github.com/tobi/try)** by [Tobias Lütke](https://github.com/tobi) — the `try` command that creates dated experiment directories. trybox mirrors its directory naming and uses it as the entry point.
- **[OpenShell](https://github.com/nvidia/openshell)** by NVIDIA — the policy-gated agent sandbox runtime. trybox uses stock upstream OpenShell unmodified.
- **[openshell-driver-apple-container](https://github.com/potable-anarchy/openshell-driver-apple-container)** — an out-of-tree UDS compute driver that plugs Apple Container into OpenShell. Derived from NVIDIA's OpenShell [PR #1888](https://github.com/nvidia/openshell/pull/1888) by [Shiju](https://github.com/mshiju) at NVIDIA, Apache-2.0 licensed.

## Quick start

```sh
trybox init          # generate PKI + gateway config
trybox driver start  # start the Apple Container compute driver
trybox gateway start # start the OpenShell gateway
trybox my big idea   # create try dir + sandbox + connect
```

`trybox doctor` checks everything is wired up. `trybox list` shows your tryboxes and sandbox state. `trybox stop <name>` stops a sandbox; `trybox <name>` resumes it.

## How it works

```
trybox "my idea"
  │
  ├─ try dir         ~/code/tries/2026-09-30-my-big-idea   (via tobi/try)
  ├─ OpenShell       policy-gated agent sandbox            (via nvidia/openshell)
  └─ Apple Container one lightweight VM per sandbox        (via apple/container)
                        │
                        └─ driver: openshell-driver-apple-container
                           out-of-tree UDS driver — no fork of OpenShell needed
```

## Requirements

- Apple Silicon Mac, macOS 26+
- `brew install container try` ([apple/container](https://github.com/apple/container), [tobi/try](https://github.com/tobi/try))
- [OpenShell](https://github.com/nvidia/openshell): `brew install nvidia/openshell/openshell`
- [openshell-driver-apple-container](https://github.com/potable-anarchy/openshell-driver-apple-container): clone, build, put in `PATH`

Or just run `bash install.sh` — it auto-installs all of the above.

## License

MIT
