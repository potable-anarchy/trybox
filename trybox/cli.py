"""trybox: turn a string into a dated try dir + a fresh openshell sandbox."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

VERSION = "0.1.0"
DEFAULT_TRY_PATH = Path(os.environ.get("TRY_PATH", Path.home() / "src/tries")).expanduser()
DEFAULT_POLICY_NAME = "trybox-default-ro-github"


@dataclass
class Trybox:
    """One trybox instance."""

    name: str            # slug, e.g. "my-big-new-project"
    dir: Path            # /Users/<you>/src/tries/2026-09-29-my-big-new-project
    sandbox_name: str    # trybox-my-big-new-project
    date_prefix: str     # YYYY-MM-DD


# ---------------------------------------------------------------------------
# slug + discovery


def slugify(text: str) -> str:
    # mirror try's behavior: "\s+" -> "-"
    slug = re.sub(r"\s+", "-", text.strip()).lower()
    return slug


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def find_trybox(name: str, base: Path = DEFAULT_TRY_PATH) -> Trybox | None:
    """Locate an existing trybox by slug (any date prefix)."""
    if not name or not base.exists():
        return None
    for entry in sorted(base.iterdir(), reverse=True):
        if entry.is_dir() and entry.name.endswith(f"-{name}"):
            prefix = entry.name.split("-", 3)
            if len(prefix) >= 4:
                date_prefix = "-".join(prefix[:3])
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
    init_git = subprocess.run(
        ["git", "-C", str(target), "init", "-q"], capture_output=True, check=False
    )
    return Trybox(
        name=name,
        dir=target,
        sandbox_name=f"trybox-{name}",
        date_prefix=date_prefix,
    )


# ---------------------------------------------------------------------------
# openshell


def openshell_ok() -> tuple[bool, str]:
    """Check the openshell CLI is present and can reach a gateway."""
    if not shutil.which("openshell"):
        return False, "openshell CLI not found in PATH (brew install nvidia/openshell/openshell)"
    proc = subprocess.run(
        ["openshell", "status", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return False, f"openshell status failed: {proc.stderr.strip() or proc.stdout.strip()}"
    return True, proc.stdout


def sandbox_list() -> list[dict]:
    """Return list of openshell sandboxes as dicts."""
    proc = subprocess.run(
        ["openshell", "sandbox", "list", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
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
    cmd = [
        "openshell",
        "sandbox",
        "create",
        "--name",
        t.sandbox_name,
    ]
    if image:
        cmd += ["--from", image]
    if policy:
        cmd += ["--policy", policy]
    cmd += ["--", agent]
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"openshell sandbox create failed (exit {proc.returncode})")


def sandbox_connect(t: Trybox) -> int:
    """Connect to an existing sandbox; replaces this process."""
    return subprocess.run(
        ["openshell", "sandbox", "connect", t.sandbox_name], check=False
    ).returncode


# ---------------------------------------------------------------------------
# commands


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = []
    checks.append(("macOS arm64", os.uname().machine == "arm64"))
    checks.append(("container CLI", shutil.which("container") is not None))
    checks.append(("try CLI", shutil.which("try") is not None))
    openshell_cli = shutil.which("openshell") is not None
    checks.append(("openshell CLI", openshell_cli))
    if openshell_cli:
        ok, msg = openshell_ok()
        checks.append((f"openshell gateway ({msg.splitlines()[0] if not ok else 'OK'})", ok))
    checks.append((f"try path ({DEFAULT_TRY_PATH})", DEFAULT_TRY_PATH.exists() or True))

    # Apple Container driver
    driver_bin = shutil.which("openshell-driver-apple-container")
    checks.append(("openshell-driver-apple-container binary", driver_bin is not None))
    if driver_bin:
        driver_v = subprocess.run([driver_bin, "--version"], capture_output=True, text=True, check=False)
        checks.append((f"driver version: {driver_v.stdout.strip().splitlines()[0] if driver_v.returncode == 0 else 'unknown'}", driver_v.returncode == 0))

    # Driver socket, if exists
    sock_path = Path(os.environ.get("TRYBOX_DRIVER_SOCK", Path.home() / ".local" / "state" / "trybox" / "driver.sock"))
    checks.append((f"driver socket ({sock_path})", sock_path.exists()))

    all_ok = all(ok for _, ok in checks)
    for label, ok in checks:
        mark = "ok" if ok else "FAIL"
        print(f"[{mark}] {label}")
    return 0 if all_ok else 1


def cmd_new_or_resume(args: argparse.Namespace) -> int:
    name = slugify(" ".join(args.name))
    if not name:
        print("trybox needs a non-empty name", file=sys.stderr)
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
    return subprocess.run(["openshell", "sandbox", "stop", target], check=False).returncode


def cmd_rm(args: argparse.Namespace) -> int:
    name = slugify(args.name)
    t = find_trybox(name)
    target = t.sandbox_name if t else f"trybox-{name}"
    rc = subprocess.run(["openshell", "sandbox", "delete", target], check=False).returncode
    if rc != 0:
        return rc
    if t and not args.keep_dir:
        if args.yes or input(f"also delete {t.dir}? [y/N] ").strip().lower() in {"y", "yes"}:
            shutil.rmtree(t.dir)
            print(f"deleted {t.dir}")
    return 0


# ---------------------------------------------------------------------------
# driver management

DRIVER_SOCK_DEFAULT = Path.home() / ".local" / "state" / "trybox" / "driver.sock"
DRIVER_PIDFILE = Path.home() / ".local" / "state" / "trybox" / "driver.pid"
DRIVER_LOG = Path.home() / ".local" / "state" / "trybox" / "driver.log"
DRIVER_SUPERVISOR_BIN = Path.home() / ".local/share/trybox/supervisor-bin"


def _driver_running() -> int | None:
    pidfile = DRIVER_PIDFILE
    if not pidfile.exists():
        return None
    try:
        pid = int(pidfile.read_text().strip())
    except ValueError:
        return None
    result = subprocess.run(["kill", "-0", str(pid)], capture_output=True, check=False)
    return pid if result.returncode == 0 else None


def cmd_driver(args: argparse.Namespace) -> int:
    sock = Path(os.environ.get("TRYBOX_DRIVER_SOCK", DRIVER_SOCK_DEFAULT))
    sock.parent.mkdir(parents=True, exist_ok=True)

    if args.action == "status":
        pid = _driver_running()
        if pid:
            print(f"openshell-driver-apple-container running (pid {pid}, sock {sock})")
            return 0
        print("openshell-driver-apple-container not running")
        return 1

    if args.action == "stop":
        pid = _driver_running()
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
        if _driver_running():
            print(f"driver already running (pid {_driver_running()})")
            return 0
        driver_bin = shutil.which("openshell-driver-apple-container")
        if not driver_bin:
            print("openshell-driver-apple-container not installed. See `trybox doctor`.", file=sys.stderr)
            return 1
        supervisor_bin = args.supervisor_bin_dir or DRIVER_SUPERVISOR_BIN
        if not supervisor_bin.exists():
            print(f"supervisor_bin_dir missing: {supervisor_bin}", file=sys.stderr)
            return 1
        log = DRIVER_LOG
        log.parent.mkdir(parents=True, exist_ok=True)
        logfile = open(log, "a", buffering=1)
        proc = subprocess.Popen(
            [driver_bin, "--bind-socket", str(sock), "--supervisor-bin-dir", str(supervisor_bin)],
            stdout=logfile, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        DRIVER_PIDFILE.write_text(str(proc.pid))
        print(f"driver started (pid {proc.pid}, sock {sock}, log {log})")
        return 0

    print(f"unknown driver action: {args.action}", file=sys.stderr)
    return 1


def cmd_image(args: argparse.Namespace) -> int:
    script = Path(__file__).parent.parent / "images" / "build.sh"
    if not script.exists():
        # pip-installed case: look next to the venv
        # uv tool installs go to ~/.local/share/uv/tools/<pkg>/lib/pythonX/site-packages/<pkg>/
        here = Path(sys.executable).parent.parent.parent.parent / "share" / "trybox" / "images" / "build.sh"
        if here.exists():
            script = here
    env = dict(os.environ)
    env["TRYBOX_IMAGE_REF"] = args.tag
    return subprocess.run(["bash", str(script)], env=env, check=False).returncode


# ---------------------------------------------------------------------------
# entry


def main() -> int:
    argv = sys.argv[1:]

    # Custom dispatch BEFORE argparse to avoid the subparser-vs-name collision.
    if argv and argv[0] in {"doctor", "list", "stop", "rm", "driver", "image"}:
        subcmd = argv[0]
        subargv = argv[1:]
        if subcmd == "doctor":
            p = argparse.ArgumentParser(prog="trybox doctor")
            return cmd_doctor(p.parse_args(subargv))
        if subcmd == "list":
            p = argparse.ArgumentParser(prog="trybox list")
            return cmd_list(p.parse_args(subargv))
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
            p = argparse.ArgumentParser(prog="trybox driver")
            p.add_argument("action", choices=["start", "stop", "status"])
            p.add_argument("--supervisor-bin-dir", type=Path)
            return cmd_driver(p.parse_args(subargv))
        if subcmd == "image":
            p = argparse.ArgumentParser(prog="trybox image")
            p.add_argument("--tag", default="local/trybox-sandbox:latest")
            return cmd_image(p.parse_args(subargv))

    # Bare name / flag form: trybox [opts] name...
    parser = argparse.ArgumentParser(
        prog="trybox",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  trybox my big new project\n"
            "  trybox list\n"
            "  trybox rm my-big-new-project\n"
            "\n"
            "the name is slugged with try's rules (whitespace -> '-').\n"
            "if a trybox by that name exists, `trybox <name>` resumes it; otherwise\n"
            "it creates the try dir and a fresh openshell sandbox in one motion.\n"
        ),
    )
    parser.add_argument("--agent", default=os.environ.get("TRYBOX_AGENT", "opencode"),
                        help="agent CLI to run inside the sandbox (default: %(default)s)")
    parser.add_argument("--image", default=os.environ.get("TRYBOX_IMAGE", "local/trybox-sandbox:latest"),
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
