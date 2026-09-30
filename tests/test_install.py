import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from trybox import cli, runtime

REPO = Path(__file__).resolve().parents[1]


class PreflightTests(unittest.TestCase):
    def check(self, **overrides):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            commands = base / "commands"
            commands.mkdir()
            scripts = {
                "uname": 'case "$1" in -s) echo Darwin;; -m) echo "${MOCK_ARCH:-arm64}";; esac',
                "sw_vers": 'echo "${MOCK_MACOS:-26.0}"',
                "sysctl": 'echo "${MOCK_HV:-1}"',
                "xcode-select": 'exit "${MOCK_XCODE:-0}"',
                "xcrun": 'exit "${MOCK_XCODE:-0}"',
                "id": 'echo 501',
                "df": 'printf "Filesystem blocks used available capacity mount\\nmock 99999999 1 ${MOCK_FREE:-99999998} 1%% /\\n"',
                "brew": 'echo mutation >> "$MUTATIONS"; exit 99',
                "gh": 'exit "${MOCK_GH:-0}"',
            }
            for name, body in scripts.items():
                file = commands / name
                file.write_text("#!/bin/bash\n" + body + "\n")
                file.chmod(0o755)
            install = base / "not-created"
            env = dict(os.environ, PATH=f"{commands}:/usr/bin:/bin:/usr/sbin", HOME=str(base),
                       TRYBOX_INSTALL_ROOT=str(install), MUTATIONS=str(base / "mutations"), **overrides)
            result = subprocess.run(["/bin/bash", str(REPO / "install.sh"), "--check"],
                                    env=env, text=True, capture_output=True)
            self.assertFalse(install.exists(), result.stdout + result.stderr)
            self.assertFalse((base / "mutations").exists())
            return result

    def test_supported_system_check_makes_no_changes(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("System checks passed", result.stdout)

    def test_platform_and_access_failures_do_not_install(self):
        for condition in ({"MOCK_ARCH": "x86_64"}, {"MOCK_MACOS": "15.0"},
                          {"MOCK_HV": "0"}, {"MOCK_FREE": "100"},
                          {"MOCK_XCODE": "1"}, {"MOCK_GH": "1"}):
            with self.subTest(condition=condition):
                result = self.check(**condition)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("No installation changes made", result.stderr)


class UninstallTests(unittest.TestCase):
    def test_preview_and_uninstall_preserve_user_data_and_other_containers(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            root = home / "runtime"
            for name in ("bin", "venv", "state", "tls", "src", "build"):
                (root / name).mkdir(parents=True)
                (root / name / "sentinel").write_text(name)
            project = home / "src/tries/my-project"
            project.mkdir(parents=True)
            (project / "work.py").write_text("keep me")
            launcher = home / ".local/bin/trybox"
            launcher.parent.mkdir(parents=True)
            (root / "bin/trybox").write_text("launcher")
            launcher.symlink_to(root / "bin/trybox")
            (root / "install.json").write_text(json.dumps({"app": "trybox", "root": str(root),
                                                          "launcher": str(launcher)}))
            container_list = [
                {"id": "ours", "configuration": {"id": "ours", "labels": {
                    "openshell.ai/sandbox-namespace": "trybox", "openshell.ai/managed-by": "openshell"}},
                 "status": {"state": "running"}},
                {"id": "other", "configuration": {"id": "other", "labels": {}}, "status": "running"},
            ]
            commands = []
            def fake_run(args, **kwargs):
                commands.append(args)
                return subprocess.CompletedProcess(args, 0, json.dumps(container_list), "")
            with patch.object(runtime, "ROOT", root), patch.dict(os.environ, HOME=str(home)), \
                 patch.object(runtime, "run", side_effect=fake_run), \
                 patch.object(runtime.subprocess, "run", side_effect=fake_run):
                for name in ("driver", "gateway"):
                    service = runtime.service_path(name)
                    service.parent.mkdir(parents=True, exist_ok=True)
                    service.write_bytes(plistlib.dumps({"EnvironmentVariables": {"TRYBOX_INSTALL_ROOT": str(root)}}))
                runtime.uninstall()
                self.assertEqual(commands, [])
                self.assertTrue(launcher.exists())
                runtime.uninstall(yes=True)
                self.assertIn(["container", "stop", "ours"], commands)
                self.assertNotIn(["container", "stop", "other"], commands)
                self.assertFalse(launcher.is_symlink())
                self.assertFalse((root / "venv").exists())
                self.assertTrue((root / "state/sentinel").exists())
                self.assertTrue((root / "tls/sentinel").exists())
                self.assertEqual((project / "work.py").read_text(), "keep me")

    def test_mismatched_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "install.json").write_text(json.dumps({"app": "trybox", "root": "/elsewhere"}))
            with patch.object(runtime, "ROOT", root):
                with self.assertRaises(RuntimeError):
                    runtime.uninstall(yes=True)


class CliTests(unittest.TestCase):
    def test_project_names_cannot_escape_try_directory_or_exceed_gateway_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            for text in ("../../escape", "my very long project name with spaces"):
                slug = cli.slugify(text)
                self.assertNotIn("/", slug)
                project = cli.create_try_dir(slug, Path(temp))
                self.assertEqual(project.dir.parent, Path(temp))
                self.assertLessEqual(len(project.sandbox_name), 19)
                self.assertEqual(cli.find_trybox(slug, Path(temp)), project)


if __name__ == "__main__":
    unittest.main()
