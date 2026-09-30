"""Private runtime, launchd services, and conservative uninstallation."""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("TRYBOX_INSTALL_ROOT", Path.home() / ".local/share/trybox")).expanduser()
LABEL_PREFIX = "com.trybox."
PORT = 17691


def environment() -> dict[str, str]:
    env = dict(os.environ)
    # Keep trybox's gateway, certificates and defaults separate from other gateways.
    for key in tuple(env):
        if key.startswith("OPENSHELL_"):
            env.pop(key)
    env.update({
        "PATH": f"{ROOT}/bin:{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "XDG_CONFIG_HOME": str(ROOT / "config"),
        "XDG_STATE_HOME": str(ROOT / "state"),
        "XDG_CACHE_HOME": str(ROOT / "cache"),
        "OPENSHELL_LOCAL_TLS_DIR": str(ROOT / "tls"),
        "OPENSHELL_GATEWAY": "trybox",
        "TRYBOX_INSTALL_ROOT": str(ROOT),
    })
    return env


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, env=environment(), check=True, **kwargs)


def service_path(name: str) -> Path:
    return Path.home() / "Library/LaunchAgents" / f"{LABEL_PREFIX}{name}.plist"


def service_owned(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open("rb") as stream:
        config = plistlib.load(stream)
    return config.get("EnvironmentVariables", {}).get("TRYBOX_INSTALL_ROOT") == str(ROOT)


def stop_services() -> None:
    for name in ("gateway", "driver"):
        path = service_path(name)
        if service_owned(path):
            service = f"gui/{os.getuid()}/{LABEL_PREFIX}{name}"
            present = subprocess.run(["launchctl", "print", service], capture_output=True)
            if present.returncode == 0:
                subprocess.run(["launchctl", "bootout", service], check=True)


def load_service(name: str, command: list[str]) -> None:
    path = service_path(name)
    if path.exists() and not service_owned(path):
        raise RuntimeError(f"Refusing to replace an unrelated service: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    env = environment()
    # launchd needs a bounded, explicit environment; do not persist shell secrets.
    env = {k: env[k] for k in ("PATH", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME",
                              "OPENSHELL_LOCAL_TLS_DIR", "TRYBOX_INSTALL_ROOT")}
    env["HOME"] = str(Path.home())
    config = {"Label": LABEL_PREFIX + name, "ProgramArguments": command,
              "EnvironmentVariables": env, "RunAtLoad": True, "KeepAlive": True,
              "ThrottleInterval": 10,
              "StandardOutPath": str(ROOT / "logs" / f"{name}.log"),
              "StandardErrorPath": str(ROOT / "logs" / f"{name}.log")}
    with path.open("wb") as stream:
        plistlib.dump(config, stream)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], check=True)


def start() -> None:
    for name in ("state", "config", "cache", "logs", "tls"):
        (ROOT / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    run(["container", "system", "start"])
    gateway = shutil.which("openshell-gateway", path=environment()["PATH"])
    if not gateway:
        raise RuntimeError("openshell-gateway is missing")
    run([gateway, "generate-certs", "--output-dir", str(ROOT / "tls"),
         "--server-san", "127.0.0.1", "--server-san", "localhost"])
    stop_services()
    sock = ROOT / "state/driver.sock"
    tls = ROOT / "tls"
    load_service("driver", [str(ROOT / "bin/openshell-driver-apple-container"),
        "--allow-same-uid-peer",
        "--bind-socket", str(sock), "--sandbox-namespace", "trybox",
        "--supervisor-bin-dir", str(ROOT / "supervisor-bin"),
        "--host-supervisor-bin", str(ROOT / "host-bin/openshell-supervisor"),
        "--grpc-endpoint", f"https://127.0.0.1:{PORT}",
        "--default-image", "local/trybox-sandbox:latest",
        "--guest-tls-ca", str(tls / "ca.crt"),
        "--guest-tls-cert", str(tls / "client/tls.crt"),
        "--guest-tls-key", str(tls / "client/tls.key")])
    for _ in range(60):
        if sock.exists():
            break
        time.sleep(1)
    else:
        raise RuntimeError(f"Driver failed to start; see {ROOT}/logs/driver.log")
    load_service("gateway", [gateway, "--name", "trybox", "--port", str(PORT),
        "--bind-address", "127.0.0.1", "--compute-driver", "apple-container",
        "--compute-driver-socket", str(sock), "--enable-mtls-auth", "true"])
    registration = ROOT / "config/openshell/gateways/trybox/metadata.json"
    if not registration.exists():
        run(["openshell", "gateway", "add", f"https://127.0.0.1:{PORT}", "--local", "--name", "trybox"])
    for _ in range(60):
        result = subprocess.run(["openshell", "status", "-o", "json"], env=environment(),
                                capture_output=True, timeout=10)
        if result.returncode == 0:
            print("trybox services are ready.")
            return
        time.sleep(1)
    raise RuntimeError(f"Gateway did not become ready; see {ROOT}/logs/gateway.log")


def uninstall(yes: bool = False) -> None:
    root = ROOT.resolve()
    marker = root / "install.json"
    if root in (Path("/"), Path.home(), Path.home() / ".local", Path.home() / ".local/share"):
        raise RuntimeError(f"Unsafe installation directory: {root}")
    manifest = json.loads(marker.read_text())
    if manifest.get("app") != "trybox" or Path(manifest["root"]).resolve() != root:
        raise RuntimeError("Installation manifest does not match this directory")
    directories = ("bin", "host-bin", "supervisor-bin", "venv", "assets", "src", "build")
    print(f"Remove trybox's services, CLI, and installed code from {root}.")
    print("Keep project directories, sandbox volumes/images, runtime state, and shared dependencies.")
    if not yes:
        print("Preview only. Run `trybox uninstall --yes` to uninstall.")
        return
    # Stop only this driver's containers; never delete their data.
    containers = run(["container", "list", "--all", "--format", "json"], capture_output=True, text=True)
    for item in json.loads(containers.stdout):
        config = item.get("configuration", {})
        labels = config.get("labels", {})
        if (labels.get("openshell.ai/sandbox-namespace") == "trybox"
                and labels.get("openshell.ai/managed-by") == "openshell"):
            status = item.get("status", {})
            state = status if isinstance(status, str) else status.get("state")
            if state == "running":
                run(["container", "stop", config["id"]])
    stop_services()
    for name in ("gateway", "driver"):
        path = service_path(name)
        if service_owned(path):
            path.unlink()
    launcher = Path(manifest["launcher"])
    if launcher.is_symlink() and launcher.resolve() == root / "bin/trybox":
        launcher.unlink()
    for name in directories:
        path = root / name
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
    print(f"Uninstalled. Preserved sandbox state and certificates in {root}.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "uninstall"])
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "start":
            start()
        elif args.action == "stop":
            stop_services()
        else:
            uninstall(args.yes)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"trybox: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
