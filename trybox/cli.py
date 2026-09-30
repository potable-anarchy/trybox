"""trybox: turn a string into a dated try dir + a fresh openshell sandbox.

MIT License. Copyright (c) 2026 Brad Dougherty.

A thin wrapper around the OpenShell CLI that:

1.  Generates a local PKI (TLS CA + server/client certs + Ed25519 JWT keys) on
    ``trybox init``.
2.  Manages the three long-running processes needed for an Apple-Container
    backed sandbox: the compute driver, the gateway, and (via the openshell
    CLI) the registered gateway endpoint.
3.  Creates a dated try directory and a fresh sandbox, then connects to it.

Python 3.10+.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

VERSION = "0.2.0"

# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #

HOME = Path.home()
SHARE_DIR = HOME / ".local" / "share" / "trybox"
STATE_DIR = HOME / ".local" / "state" / "trybox"

TLS_DIR = SHARE_DIR / "tls"
CA_CRT = TLS_DIR / "ca.crt"
CA_KEY = TLS_DIR / "ca.key"
SERVER_DIR = TLS_DIR / "server"
SERVER_CRT = SERVER_DIR / "tls.crt"
SERVER_KEY = SERVER_DIR / "tls.key"
CLIENT_DIR = TLS_DIR / "client"
CLIENT_CRT = CLIENT_DIR / "tls.crt"
CLIENT_KEY = CLIENT_DIR / "tls.key"
JWT_DIR = TLS_DIR / "jwt"
JWT_SIGNING = JWT_DIR / "signing.pem"
JWT_PUBLIC = JWT_DIR / "public.pem"
JWT_KID = JWT_DIR / "kid"

GATEWAY_TOML = SHARE_DIR / "gateway.toml"
GATEWAY_PIDFILE = STATE_DIR / "gateway.pid"
GATEWAY_LOG = STATE_DIR / "gateway.log"

DRIVER_SOCK = STATE_DIR / "driver.sock"
DRIVER_PIDFILE = STATE_DIR / "driver.pid"
DRIVER_LOG = STATE_DIR / "driver.log"
DRIVER_SUPERVISOR_BIN = SHARE_DIR / "supervisor-bin"

DB_URL = "sqlite:////tmp/trybox-test.db"
GATEWAY_BIND = "127.0.0.1:17671"
GATEWAY_PORT = 17671
GATEWAY_NAME = "trybox-test"
GATEWAY_ENDPOINT = f"https://127.0.0.1:{GATEWAY_PORT}"
SANDBOX_IMAGE = "local/trybox-sandbox:latest"

DEFAULT_TRY_PATH = Path(
    os.environ.get("TRY_PATH", HOME / "code" / "tries")
).expanduser()
DEFAULT_POLICY_NAME = "trybox-default-ro-github"
DEFAULT_AGENT = os.environ.get("TRYBOX_AGENT", "opencode")


@dataclass
class Trybox:
    """One trybox instance."""

    name: str            # slug, e.g. "my-big-new-project"
    dir: Path            # ~/code/tries/2026-09-29-my-big-new-project
    sandbox_name: str    # trybox-my-big-new-project
    date_prefix: str     # YYYY-MM-DD


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def slugify(text: str) -> str:
    """Mirror try's behavior: whitespace -> '-'."""
    return re.sub(r"\s+", "-", text.strip()).lower()


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """subprocess.run wrapper that never raises; returns CompletedProcess."""
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)


def _which(name: str) -> str | None:
    """Find a binary, falling back to the dev release dir."""
    bin_path = shutil.which(name)
    if bin_path:
        return bin_path
    dev = HOME / "code" / "tries" / "2026-09-29-trybox" / "OpenShell-upstream" / "target" / "release" / name
    if dev.exists() and os.access(dev, os.X_OK):
        return str(dev)
    return None


# --------------------------------------------------------------------------- #
# try dir discovery / creation
# --------------------------------------------------------------------------- #

def find_trybox(name: str, base: Path = DEFAULT_TRY_PATH) -> Trybox | None:
    """Locate an existing trybox by slug (any date prefix)."""
    if not name or not base.exists():
        return None
    for entry in sorted(base.iterdir(), reverse=True):
        if entry.is_dir() and entry.name.endswith(f"-{name}"):
            parts = entry.name.split("-", 3)
            if len(parts) >= 4:
                date_prefix = "-".join(parts[:3])
                if re.match(r"\d{4}-\d{2}-\d{2}$", date_prefix):
                    return Trybox(
                        name=name,
                        dir=entry,
                        sandbox_name=f"trybox-{name}",
                        date_prefix=date_prefix,
                    )
    return None


def create_try_dir(name: str, base: Path = DEFAULT_TRY_PATH) -> Trybox:
    """Create a fresh dated try dir (try's exact layout)."""
    date_prefix = today()
    dirname = f"{date_prefix}-{name}"
    target = base / dirname
    # Mirror try's uniqueness: if exists, append -2, -3, ...
    if target.exists():
        n = 2
        while (base / f"{dirname}-{n}").exists():
            n += 1
        target = base / f"{dirname}-{n}"
    target.mkdir(parents=True, exist_ok=False)
    (target / ".git").mkdir(exist_ok=False)
    subprocess.run(
        ["git", "-C", str(target), "init", "-q"], capture_output=True, check=False
    )
    return Trybox(
        name=name,
        dir=target,
        sandbox_name=f"trybox-{name}",
        date_prefix=date_prefix,
    )


# --------------------------------------------------------------------------- #
# PKI generation  (trybox init)
# --------------------------------------------------------------------------- #

def _openssl(*args: str) -> None:
    """Run openssl, raising SystemExit on failure."""
    proc = subprocess.run(["openssl", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(
            f"openssl {' '.join(args[:2])} ... failed (exit {proc.returncode}):\n"
            f"{proc.stderr.strip()}"
        )


def _openssl_ed() -> str:
    """Return an openssl binary that supports Ed25519.

    macOS ships LibreSSL which lacks Ed25519 in `genpkey`, so prefer the
    Homebrew openssl@3 when available.
    """
    for candidate in (
        "/opt/homebrew/opt/openssl@3/bin/openssl",
        "/usr/local/opt/openssl@3/bin/openssl",
    ):
        if Path(candidate).exists():
            return candidate
    return shutil.which("openssl") or "openssl"


def _ensure_dirs() -> None:
    for d in (SHARE_DIR, STATE_DIR, TLS_DIR, SERVER_DIR, CLIENT_DIR, JWT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _pki_exists() -> bool:
    return all(p.exists() for p in (
        CA_CRT, SERVER_CRT, SERVER_KEY, CLIENT_CRT, CLIENT_KEY,
        JWT_SIGNING, JWT_PUBLIC, JWT_KID,
    ))


def generate_pki() -> None:
    """Generate TLS CA + server/client certs and Ed25519 JWT keys."""
    _ensure_dirs()

    # --- CA (ECDSA P-256) ---
    _openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout",
             "-out", str(CA_KEY))
    _openssl("req", "-x509", "-new", "-key", str(CA_KEY),
             "-subj", "/CN=trybox-ca/O=trybox",
             "-days", "3650", "-out", str(CA_CRT))

    # --- Server cert (SAN IP:127.0.0.1) ---
    serial_file = TLS_DIR / "ca.srl"
    server_ext = TLS_DIR / "server.ext"
    server_ext.write_text(
        "subjectAltName=IP:127.0.0.1,DNS:localhost\n"
        "extendedKeyUsage=serverAuth\n"
    )
    _openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout",
             "-out", str(SERVER_KEY))
    _openssl("req", "-new", "-key", str(SERVER_KEY),
             "-subj", "/CN=trybox-server/O=trybox",
             "-out", str(TLS_DIR / "server.csr"))
    _openssl("x509", "-req", "-in", str(TLS_DIR / "server.csr"),
             "-CA", str(CA_CRT), "-CAkey", str(CA_KEY),
             "-CAserial", str(serial_file), "-CAcreateserial",
             "-days", "3650", "-extfile", str(server_ext), "-out", str(SERVER_CRT))
    (TLS_DIR / "server.csr").unlink(missing_ok=True)
    server_ext.unlink(missing_ok=True)

    # --- Client cert (for mTLS) ---
    _openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout",
             "-out", str(CLIENT_KEY))
    _openssl("req", "-new", "-key", str(CLIENT_KEY),
             "-subj", "/CN=trybox-client/O=trybox",
             "-out", str(TLS_DIR / "client.csr"))
    client_ext = TLS_DIR / "client.ext"
    client_ext.write_text("extendedKeyUsage=clientAuth\n")
    _openssl("x509", "-req", "-in", str(TLS_DIR / "client.csr"),
             "-CA", str(CA_CRT), "-CAkey", str(CA_KEY),
             "-CAserial", str(serial_file), "-CAcreateserial",
             "-days", "3650", "-extfile", str(client_ext), "-out", str(CLIENT_CRT))
    (TLS_DIR / "client.csr").unlink(missing_ok=True)
    client_ext.unlink(missing_ok=True)

    # --- JWT keys (Ed25519) ---
    # macOS LibreSSL lacks Ed25519 genpkey; use Homebrew openssl@3 if present.
    ed_openssl = _openssl_ed()
    # Rust expects PKCS8 PEM; LibreSSL on macOS may not parse Ed25519 but the
    # gateway (Rust) handles it fine.
    _ed_run = lambda *a: subprocess.run([ed_openssl, *a], capture_output=True,
                                        text=True, check=False)
    proc = _ed_run("genpkey", "-algorithm", "Ed25519", "-out", str(JWT_SIGNING))
    if proc.returncode != 0:
        raise SystemExit(
            f"Ed25519 keygen failed (exit {proc.returncode}):\n{proc.stderr.strip()}\n"
            "Install Homebrew openssl@3: brew install openssl@3"
        )
    proc = _ed_run("pkey", "-in", str(JWT_SIGNING), "-pubout", "-out", str(JWT_PUBLIC))
    if proc.returncode != 0:
        raise SystemExit(
            f"Ed25519 pubkey extraction failed (exit {proc.returncode}):\n{proc.stderr.strip()}"
        )
    kid = hashlib.sha256(JWT_PUBLIC.read_bytes()).hexdigest()[:32]
    JWT_KID.write_text(kid)

    # Lock down private material.
    for key in (CA_KEY, SERVER_KEY, CLIENT_KEY, JWT_SIGNING):
        try:
            key.chmod(0o600)
        except OSError:
            pass


def write_gateway_toml() -> None:
    """Write the gateway config TOML, pointing at the PKI dir."""
    tls = str(TLS_DIR)
    toml = f"""\
[openshell]
version = 2

[openshell.gateway]
name = "{GATEWAY_NAME}"
compute_driver = "apple-container"
bind_address = "{GATEWAY_BIND}"
log_level = "debug,openshell_driver_apple_container=trace"
guest_tls_ca = "{tls}/ca.crt"
guest_tls_cert = "{tls}/client/tls.crt"
guest_tls_key = "{tls}/client/tls.key"

[openshell.gateway.auth]
allow_unauthenticated_users = true

[openshell.gateway.tls]
cert_path = "{tls}/server/tls.crt"
key_path = "{tls}/server/tls.key"
client_ca_path = "{tls}/ca.crt"

[openshell.gateway.gateway_jwt]
signing_key_path = "{tls}/jwt/signing.pem"
public_key_path = "{tls}/jwt/public.pem"
kid_path = "{tls}/jwt/kid"

[openshell.drivers.apple-container]
default_image = "{SANDBOX_IMAGE}"
supervisor_bin_dir = "{DRIVER_SUPERVISOR_BIN}"
"""
    GATEWAY_TOML.parent.mkdir(parents=True, exist_ok=True)
    GATEWAY_TOML.write_text(toml)


# --------------------------------------------------------------------------- #
# process management (driver + gateway)
# --------------------------------------------------------------------------- #

def _pid_running(pid: int) -> bool:
    return subprocess.run(["kill", "-0", str(pid)],
                          capture_output=True, check=False).returncode == 0


def _read_pidfile(pidfile: Path) -> int | None:
    if not pidfile.exists():
        return None
    try:
        pid = int(pidfile.read_text().strip())
    except ValueError:
        return None
    return pid if _pid_running(pid) else None


# --- driver --- #

def driver_running() -> int | None:
    return _read_pidfile(DRIVER_PIDFILE)


def ensure_driver() -> bool:
    """Start the driver if not running; return True if it's up."""
    if driver_running():
        return True
    ns = argparse.Namespace(action="start", supervisor_bin_dir=None)
    return cmd_driver(ns) == 0


# --- gateway --- #

def gateway_running() -> int | None:
    return _read_pidfile(GATEWAY_PIDFILE)


def ensure_gateway() -> bool:
    """Start the gateway if not running; return True if it's up."""
    if gateway_running():
        return True
    ns = argparse.Namespace(action="start")
    return cmd_gateway(ns) == 0


# --------------------------------------------------------------------------- #
# openshell CLI helpers
# --------------------------------------------------------------------------- #

def openshell_bin() -> str | None:
    return _which("openshell")


def gateway_list() -> list[dict]:
    """Return registered gateways as parsed from `openshell gateway list`."""
    osc = openshell_bin()
    if not osc:
        return []
    proc = _run([osc, "gateway", "list", "--json"])
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []


def gateway_registered(name: str = GATEWAY_NAME) -> bool:
    return any(g.get("name") == name for g in gateway_list())


def ensure_gateway_registered() -> int:
    """Register + select the trybox gateway if needed; returns exit code."""
    osc = openshell_bin()
    if not osc:
        print("openshell CLI not found in PATH (brew install nvidia/openshell/openshell)",
              file=sys.stderr)
        return 1

    if not gateway_registered():
        proc = _run([osc, "gateway", "add", "--local", "--name", GATEWAY_NAME,
                     GATEWAY_ENDPOINT])
        if proc.returncode != 0:
            print(f"openshell gateway add failed:\n{proc.stderr.strip() or proc.stdout.strip()}",
                  file=sys.stderr)
            return 1
        print(f"registered gateway: {GATEWAY_NAME}")

    proc = _run([osc, "gateway", "select", GATEWAY_NAME])
    if proc.returncode != 0:
        print(f"openshell gateway select failed:\n{proc.stderr.strip() or proc.stdout.strip()}",
              file=sys.stderr)
        return 1
    return 0


def sandbox_list() -> list[dict]:
    """Return list of openshell sandboxes as dicts."""
    osc = openshell_bin()
    if not osc:
        return []
    proc = _run([osc, "sandbox", "list", "--json"])
    if proc.returncode != 0:
        return []
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []


def sandbox_exists(name: str) -> bool:
    return any(s.get("name") == name for s in sandbox_list())


def sandbox_create(t: Trybox, agent: str, image: str, policy: str) -> None:
    """Create the openshell sandbox for this trybox."""
    osc = openshell_bin()
    if not osc:
        raise SystemExit("openshell CLI not found in PATH")

    cmd = [osc, "sandbox", "create", "--name", t.sandbox_name, "--from", image]
    if policy:
        cmd += ["--policy", policy]
    cmd += ["--", agent]
    print(f"creating sandbox: {' '.join(cmd)}")
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"openshell sandbox create failed (exit {proc.returncode})")


def sandbox_connect(t: Trybox) -> int:
    """Connect to an existing sandbox; replaces this process."""
    osc = openshell_bin()
    if not osc:
        raise SystemExit("openshell CLI not found in PATH")
    return subprocess.run([osc, "sandbox", "connect", t.sandbox_name],
                          check=False).returncode


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def cmd_init(args: argparse.Namespace) -> int:
    """trybox init — generate PKI + gateway config."""
    if _pki_exists() and not args.force:
        print(f"PKI already exists at {TLS_DIR} (use --force to regenerate)")
    else:
        print(f"generating PKI at {TLS_DIR} ...")
        generate_pki()
        print(f"  CA:              {CA_CRT}")
        print(f"  server cert:     {SERVER_CRT}")
        print(f"  client cert:     {CLIENT_CRT}")
        print(f"  JWT signing key: {JWT_SIGNING}")
        print(f"  JWT public key:  {JWT_PUBLIC}")
        print(f"  JWT kid:         {JWT_KID.read_text().strip()}")

    if GATEWAY_TOML.exists() and not args.force:
        print(f"gateway config already exists at {GATEWAY_TOML}")
    else:
        write_gateway_toml()
        print(f"wrote gateway config: {GATEWAY_TOML}")

    # Make sure the supervisor-bin dir exists so the driver can start.
    DRIVER_SUPERVISOR_BIN.mkdir(parents=True, exist_ok=True)
    print(f"supervisor bin dir:  {DRIVER_SUPERVISOR_BIN}")
    print("trybox init complete. Next: trybox driver start && trybox gateway start")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool]] = []
    checks.append(("macOS arm64", os.uname().machine == "arm64"))
    checks.append(("container CLI", shutil.which("container") is not None))
    checks.append(("try CLI", shutil.which("try") is not None))

    osc = openshell_bin()
    checks.append(("openshell CLI", osc is not None))
    gw_bin = _which("openshell-gateway")
    checks.append(("openshell-gateway binary", gw_bin is not None))
    driver_bin = _which("openshell-driver-apple-container")
    checks.append(("openshell-driver-apple-container binary", driver_bin is not None))

    checks.append((f"try path ({DEFAULT_TRY_PATH})", DEFAULT_TRY_PATH.exists()))
    checks.append((f"PKI dir ({TLS_DIR})", TLS_DIR.exists() and _pki_exists()))
    checks.append((f"gateway.toml ({GATEWAY_TOML})", GATEWAY_TOML.exists()))

    # Driver
    checks.append((f"driver socket ({DRIVER_SOCK})", DRIVER_SOCK.exists()))
    dpid = driver_running()
    checks.append((f"driver running (pid {dpid})" if dpid else "driver running", dpid is not None))
    if driver_bin:
        dv = _run([driver_bin, "--version"])
        checks.append((
            f"driver version: {dv.stdout.strip().splitlines()[0] if dv.returncode == 0 else 'unknown'}",
            dv.returncode == 0,
        ))

    # Gateway
    gpid = gateway_running()
    checks.append((f"gateway running (pid {gpid})" if gpid else "gateway running", gpid is not None))

    # openshell gateway registration
    if osc:
        checks.append((f"gateway registered ({GATEWAY_NAME})", gateway_registered()))

    all_ok = all(ok for _, ok in checks)
    for label, ok in checks:
        mark = "ok  " if ok else "FAIL"
        print(f"[{mark}] {label}")
    return 0 if all_ok else 1


def cmd_gateway(args: argparse.Namespace) -> int:
    if args.action == "status":
        pid = gateway_running()
        if pid:
            print(f"openshell-gateway running (pid {pid}, log {GATEWAY_LOG})")
            return 0
        print("openshell-gateway not running")
        return 1

    if args.action == "stop":
        pid = gateway_running()
        if not pid:
            print("no gateway running")
            return 0
        os.kill(pid, 15)
        try:
            GATEWAY_PIDFILE.unlink()
        except FileNotFoundError:
            pass
        print(f"stopped gateway (pid {pid})")
        return 0

    if args.action == "start":
        if gateway_running():
            print(f"gateway already running (pid {gateway_running()})")
            return 0
        gw_bin = _which("openshell-gateway")
        if not gw_bin:
            print("openshell-gateway not installed. See `trybox doctor`.", file=sys.stderr)
            return 1
        if not GATEWAY_TOML.exists():
            print(f"gateway config missing: {GATEWAY_TOML} — run `trybox init` first.",
                  file=sys.stderr)
            return 1
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log = open(GATEWAY_LOG, "a", buffering=1)
        cmd = [
            gw_bin,
            "--config", str(GATEWAY_TOML),
            "--compute-driver", "apple-container",
            "--compute-driver-socket", str(DRIVER_SOCK),
            "--db-url", DB_URL,
        ]
        print(f"starting gateway: {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd,
            stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        GATEWAY_PIDFILE.write_text(str(proc.pid))
        print(f"gateway started (pid {proc.pid}, log {GATEWAY_LOG})")
        return 0

    print(f"unknown gateway action: {args.action}", file=sys.stderr)
    return 1


def cmd_driver(args: argparse.Namespace) -> int:
    if args.action == "status":
        pid = driver_running()
        if pid:
            print(f"openshell-driver-apple-container running (pid {pid}, sock {DRIVER_SOCK})")
            return 0
        print("openshell-driver-apple-container not running")
        return 1

    if args.action == "stop":
        pid = driver_running()
        if not pid:
            print("no driver running")
            return 0
        os.kill(pid, 15)
        try:
            DRIVER_PIDFILE.unlink()
        except FileNotFoundError:
            pass
        print(f"stopped driver (pid {pid})")
        return 0

    if args.action == "start":
        if driver_running():
            print(f"driver already running (pid {driver_running()})")
            return 0
        driver_bin = _which("openshell-driver-apple-container")
        if not driver_bin:
            print("openshell-driver-apple-container not installed. See `trybox doctor`.",
                  file=sys.stderr)
            return 1
        supervisor_bin = args.supervisor_bin_dir or DRIVER_SUPERVISOR_BIN
        if not supervisor_bin.exists():
            print(f"supervisor_bin_dir missing: {supervisor_bin}", file=sys.stderr)
            return 1
        if not _pki_exists():
            print(f"PKI missing at {TLS_DIR} — run `trybox init` first.", file=sys.stderr)
            return 1
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log = open(DRIVER_LOG, "a", buffering=1)
        cmd = [
            driver_bin,
            "--bind-socket", str(DRIVER_SOCK),
            "--supervisor-bin-dir", str(supervisor_bin),
            "--allow-same-uid-peer",
            "--gateway-port", str(GATEWAY_PORT),
            "--host-tls-ca", str(CA_CRT),
            "--host-tls-cert", str(CLIENT_CRT),
            "--host-tls-key", str(CLIENT_KEY),
        ]
        print(f"starting driver: {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd,
            stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        DRIVER_PIDFILE.write_text(str(proc.pid))
        print(f"driver started (pid {proc.pid}, sock {DRIVER_SOCK}, log {DRIVER_LOG})")
        return 0

    print(f"unknown driver action: {args.action}", file=sys.stderr)
    return 1


def cmd_image(args: argparse.Namespace) -> int:
    script = Path(__file__).parent.parent / "images" / "build.sh"
    if not script.exists():
        # pip-installed case: look next to the venv
        here = Path(sys.executable).parent.parent.parent.parent / "share" / "trybox" / "images" / "build.sh"
        if here.exists():
            script = here
    env = dict(os.environ)
    env["TRYBOX_IMAGE_REF"] = args.tag
    return subprocess.run(["bash", str(script)], env=env, check=False).returncode


def cmd_new_or_resume(args: argparse.Namespace) -> int:
    name = slugify(" ".join(args.name))
    if not name:
        print("trybox needs a non-empty name", file=sys.stderr)
        return 1

    # --- ensure infrastructure is running ---
    print("ensuring driver ...")
    if not ensure_driver():
        print("failed to start driver — run `trybox driver start` manually", file=sys.stderr)
        return 1
    print("ensuring gateway ...")
    if not ensure_gateway():
        print("failed to start gateway — run `trybox gateway start` manually", file=sys.stderr)
        return 1
    print("ensuring gateway registered ...")
    if ensure_gateway_registered() != 0:
        print("failed to register/select gateway", file=sys.stderr)
        return 1

    existing = find_trybox(name)
    if existing:
        t = existing
        if not sandbox_exists(t.sandbox_name):
            print(f" resurrection: try dir {t.dir} exists, but sandbox {t.sandbox_name} is gone — recreating")
            sandbox_create(t, args.agent, args.image, args.policy)
        print(f"connecting: {t.dir}")
        return sandbox_connect(t)

    t = create_try_dir(name)
    print(f"created try dir: {t.dir}")
    sandbox_create(t, args.agent, args.image, args.policy)
    return sandbox_connect(t)


def cmd_list(args: argparse.Namespace) -> int:
    sandboxes = {s.get("name"): s for s in sandbox_list()}
    if not DEFAULT_TRY_PATH.exists():
        print("(no tries yet)")
        return 0
    rows = []
    for entry in sorted(DEFAULT_TRY_PATH.iterdir()):
        if not entry.is_dir():
            continue
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", entry.name)
        if not m:
            continue
        date_prefix, slug = m.group(1), m.group(2)
        sb_name = f"trybox-{slug}"
        state = sandboxes.get(sb_name, {}).get("state", "-")
        rows.append((date_prefix, slug, sb_name, state))
    if not rows:
        print("(no tryboxes yet)")
        return 0
    width = max(len(r[1]) for r in rows)
    for date_prefix, slug, sb_name, state in rows:
        print(f"{date_prefix}  {slug:<{width}}  {state:<10} {sb_name}")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    name = slugify(args.name)
    t = find_trybox(name)
    target = t.sandbox_name if t else f"trybox-{name}"
    osc = openshell_bin()
    if not osc:
        print("openshell CLI not found", file=sys.stderr)
        return 1
    return subprocess.run([osc, "sandbox", "stop", target], check=False).returncode


def cmd_rm(args: argparse.Namespace) -> int:
    name = slugify(args.name)
    t = find_trybox(name)
    target = t.sandbox_name if t else f"trybox-{name}"
    osc = openshell_bin()
    if not osc:
        print("openshell CLI not found", file=sys.stderr)
        return 1
    rc = subprocess.run([osc, "sandbox", "delete", target], check=False).returncode
    if rc != 0:
        return rc
    if t and not args.keep_dir:
        if args.yes or input(f"also delete {t.dir}? [y/N] ").strip().lower() in {"y", "yes"}:
            shutil.rmtree(t.dir)
            print(f"deleted {t.dir}")
    return 0


# --------------------------------------------------------------------------- #
# argument parsing helpers
# --------------------------------------------------------------------------- #

def _arg_init(subargv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="trybox init")
    p.add_argument("--force", action="store_true",
                   help="regenerate PKI + config even if they exist")
    return p.parse_args(subargv)


def _arg_gateway(subargv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="trybox gateway")
    p.add_argument("action", choices=["start", "stop", "status"])
    return p.parse_args(subargv)


def _arg_driver(subargv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="trybox driver")
    p.add_argument("action", choices=["start", "stop", "status"])
    p.add_argument("--supervisor-bin-dir", type=Path)
    return p.parse_args(subargv)


def _arg_image(subargv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="trybox image")
    p.add_argument("--tag", default=SANDBOX_IMAGE)
    return p.parse_args(subargv)


# --------------------------------------------------------------------------- #
# entry
# --------------------------------------------------------------------------- #

_SUBCOMMANDS = {"init", "doctor", "list", "stop", "rm", "driver", "gateway", "image"}


def main() -> int:
    argv = sys.argv[1:]

    # Custom dispatch BEFORE argparse to avoid the subparser-vs-name collision.
    if argv and argv[0] in _SUBCOMMANDS:
        subcmd = argv[0]
        subargv = argv[1:]
        if subcmd == "init":
            return cmd_init(_arg_init(subargv))
        if subcmd == "doctor":
            return cmd_doctor(argparse.ArgumentParser(prog="trybox doctor").parse_args(subargv))
        if subcmd == "list":
            return cmd_list(argparse.ArgumentParser(prog="trybox list").parse_args(subargv))
        if subcmd == "stop":
            p = argparse.ArgumentParser(prog="trybox stop")
            p.add_argument("name")
            return cmd_stop(p.parse_args(subargv))
        if subcmd == "rm":
            p = argparse.ArgumentParser(prog="trybox rm")
            p.add_argument("name")
            p.add_argument("--keep-dir", action="store_true")
            p.add_argument("-y", "--yes", action="store_true")
            return cmd_rm(p.parse_args(subargv))
        if subcmd == "driver":
            return cmd_driver(_arg_driver(subargv))
        if subcmd == "gateway":
            return cmd_gateway(_arg_gateway(subargv))
        if subcmd == "image":
            return cmd_image(_arg_image(subargv))

    # Bare name / flag form: trybox [opts] name...
    parser = argparse.ArgumentParser(
        prog="trybox",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  trybox init\n"
            "  trybox driver start\n"
            "  trybox gateway start\n"
            "  trybox my big new project\n"
            "  trybox list\n"
            "  trybox rm my-big-new-project\n"
            "\n"
            "the name is slugged with try's rules (whitespace -> '-').\n"
            "if a trybox by that name exists, `trybox <name>` resumes it; otherwise\n"
            "it creates the try dir and a fresh openshell sandbox in one motion.\n"
        ),
    )
    parser.add_argument("--agent", default=DEFAULT_AGENT,
                        help="agent CLI to run inside the sandbox (default: %(default)s; env TRYBOX_AGENT)")
    parser.add_argument("--image", default=os.environ.get("TRYBOX_IMAGE", SANDBOX_IMAGE),
                        help="override sandbox image (default: %(default)s)")
    parser.add_argument("--policy", default=os.environ.get("TRYBOX_POLICY", DEFAULT_POLICY_NAME),
                        help="openshell policy name (default: %(default)s)")
    parser.add_argument("--try-path", type=Path, default=DEFAULT_TRY_PATH,
                        help="root for try dirs (default: %(default)s; env TRY_PATH)")
    parser.add_argument("name", nargs="*",
                        help="name of the trybox to create or resume (free text)")
    args = parser.parse_args(argv)
    return cmd_new_or_resume(args)


if __name__ == "__main__":
    sys.exit(main())
