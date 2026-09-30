#!/usr/bin/env python3
"""Exercise the real VM, execution, policy allow/deny, and sandbox cleanup."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trybox.runtime import ROOT, run


def main():
    name = "trybox-" + uuid.uuid4().hex[:10]
    policy = ROOT / "assets/policies/trybox-default-ro-github.yaml"
    if not policy.exists():
        policy = Path(__file__).resolve().parents[1] / "policies/trybox-default-ro-github.yaml"
    created = False
    try:
        created = True  # clean up partially created resources on failure, too
        run(["openshell", "sandbox", "create", "--name", name, "--from", "local/trybox-sandbox:latest",
             "--policy", str(policy), "--detach", "--", "/bin/sleep", "infinity"], timeout=180)
        result = run(["openshell", "sandbox", "get", name, "-o", "json"], capture_output=True, text=True)
        sandbox = json.loads(result.stdout)
        assert sandbox["phase"].lower() == "ready", sandbox["phase"]
        run(["openshell", "sandbox", "exec", "--name", name, "--", "/bin/sh", "-ec", """
test "$(id -u)" = 1000
grep -q 'CapEff:.*0000000000000000' /proc/self/status
grep -q 'NoNewPrivs:.*1' /proc/self/status
printf 'trybox-smoke-ok\n' > /sandbox/smoke.txt
cat /sandbox/smoke.txt
curl -fsS --max-time 20 https://api.github.com/zen
if curl --noproxy '*' -fsS --connect-timeout 3 --max-time 4 http://1.1.1.1/ >/dev/null 2>&1; then
    echo 'FAIL: direct egress bypass succeeded'; exit 1
fi
if curl -fsS --connect-timeout 3 --max-time 4 https://example.com/ >/dev/null 2>&1; then
    echo 'FAIL: unlisted host was allowed'; exit 1
fi
echo 'PASS: allowed HTTPS works; direct egress and unlisted hosts are blocked'
"""], timeout=45)
    finally:
        if created:
            run(["openshell", "sandbox", "delete", name], timeout=60)


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, subprocess.SubprocessError) as error:
        print(f"Smoke test failed: {error}", file=sys.stderr)
        raise SystemExit(1)
