import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from helpers import ROOT, PhoneTest

from shape import __version__, cli, mcp
from shape import launcher as lz


def call(mid, tool, **arguments):
    return mcp.handle({"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": tool, "arguments": arguments}})


def text(resp):
    return resp["result"]["content"][0]["text"]


class Protocol(unittest.TestCase):
    def test_initialize_list_ping_errors(self):
        r = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(r["result"]["serverInfo"]["version"], __version__)
        self.assertIn("playbook", r["result"]["instructions"])
        r = mcp.handle({"jsonrpc": "2.0", "id": 9, "method": "initialize", "params": {"protocolVersion": "2099-01-01"}})
        self.assertEqual(r["result"]["protocolVersion"], mcp.KNOWN_PROTOCOLS[-1])
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"], {})
        tools = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertTrue({"playbook", "scan", "apply_plan", "launcher_edit", "undo", "restore_everything"} <= names)
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            if "owner_approved" in t["inputSchema"]["properties"]:
                self.assertFalse(t["annotations"]["readOnlyHint"], t["name"])
        self.assertEqual(mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "nope"})["error"]["code"], -32601)
        self.assertEqual(call(5, "nope")["error"]["code"], -32602)
        self.assertEqual(call(6, "apply_plan")["error"]["code"], -32602)  # missing plan_path

    def test_playbook_is_in_sync_with_prompt_md(self):
        self.assertEqual((ROOT / "shape" / "data" / "playbook.md").read_text(), (ROOT / "PROMPT.md").read_text(),
                         "run: cp PROMPT.md shape/data/playbook.md")
        self.assertIn("Hard rules", text(call(7, "playbook")))

    def test_stdio_roundtrip(self):
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        p = subprocess.run([sys.executable, "-m", "shape.mcp"], cwd=ROOT, capture_output=True, text=True, timeout=60,
                           encoding="utf-8",  # MCP is UTF-8 on every OS; Windows would default to cp1252
                           input="\n".join(json.dumps(m) for m in msgs) + "\nnot json\n")
        lines = [json.loads(l) for l in p.stdout.splitlines()]
        self.assertEqual([l.get("id") for l in lines], [1, 2, None])
        self.assertEqual(lines[2]["error"]["code"], -32700)


class ToolsOnFakePhone(PhoneTest):
    def setUp(self):
        super().setUp()
        self.patch = mock.patch.object(cli, "pick_device", return_value=self.dev)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        super().tearDown()

    def test_preview_then_approve(self):
        self.assertFalse(call(1, "init")["result"]["isError"])
        plan_out = text(call(2, "plan_debloat", tier="safe"))
        path = plan_out.split("Plan: ")[1].splitlines()[0].strip()
        preview = call(3, "apply_plan", plan_path=path)
        self.assertFalse(preview["result"]["isError"])
        self.assertIn("preview only", text(preview))
        self.assertEqual(self.state("com.samsung.android.app.tips"), "enabled")
        done = call(4, "apply_plan", plan_path=path, owner_approved=True)
        self.assertFalse(done["result"]["isError"], text(done))
        self.assertEqual(self.state("com.samsung.android.app.tips"), "disabled")
        self.assertNotIn("preview only", text(done))
        # undo needs approval too; without it, it only lists changes
        self.assertIn("applied", text(call(5, "undo", last=1)))
        self.assertEqual(self.state("com.samsung.android.app.tips"), "disabled")
        call(6, "restore_everything", owner_approved=True)
        self.assertEqual(self.state("com.samsung.android.app.tips"), "enabled")

    def test_blocked_and_errors_reported(self):
        r = call(1, "change_packages", action="disable", packages=["com.android.systemui"], owner_approved=True)
        self.assertIn("BLOCKED", text(r))
        r = call(2, "tweak", name="font-scale", args=["9"], owner_approved=True)
        self.assertIn("between 0.7 and 2.0", text(r))

    def test_preferences_and_launcher_edit(self):
        call(1, "init")
        call(2, "preferences_write", content="# Prefs\n- likes dark\n")
        self.assertIn("likes dark", text(call(3, "preferences_read")))
        apk = tempfile.NamedTemporaryFile(suffix=".apk", delete=False)
        apk.close()
        with mock.patch.object(lz, "find_local_apk", return_value=apk.name):
            self.assertIn("preview only", text(call(4, "launcher_install")))
            self.assertNotIn(lz.LAUNCHER_PACKAGE, self.phone.pkgs)
            call(5, "launcher_install", owner_approved=True)
        self.assertIn(lz.LAUNCHER_PACKAGE, self.phone.pkgs)
        prev = call(6, "launcher_edit", command="hide", args=["Instagram", "--from", "22:00", "--to", "07:00"])
        self.assertIn("+ Rule", text(prev))
        call(7, "launcher_edit", command="hide", args=["Instagram", "--from", "22:00", "--to", "07:00"], owner_approved=True)
        self.assertEqual(lz.get_config(self.dev)["rules"][0]["hide"], ["com.instagram.android"])
        cfg = json.loads(text(call(8, "launcher_get_config")))
        cfg["name"] = "From MCP"
        call(9, "launcher_set_config", config=cfg, owner_approved=True)
        self.assertEqual(lz.get_config(self.dev)["name"], "From MCP")


class Packaging(unittest.TestCase):
    def test_wheel_contains_data_and_runs(self):
        out = tempfile.mkdtemp(prefix="shape-wheel-")
        # build isolation pulls a modern setuptools (old system ones ignore pyproject metadata)
        p = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", "-w", out, str(ROOT)],
                           capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            self.skipTest("could not build wheel here: %s" % p.stderr[-300:])
        import zipfile
        wheel = [f for f in os.listdir(out) if f.endswith(".whl")][0]
        names = zipfile.ZipFile(os.path.join(out, wheel)).namelist()
        for needed in ("shape/data/protected.json", "shape/data/bloat/samsung.json", "shape/data/playbook.md", "shape/mcp.py"):
            self.assertIn(needed, names)
        self.assertIn(__version__, wheel)

    def test_home_dir_outside_checkout(self):
        from shape import state
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHAPE_HOME", None)
            with mock.patch.object(state, "running_from_checkout", return_value=False):
                self.assertEqual(state.shape_home(), state.Path.home() / ".shapeyourphone" / "devices")
            self.assertEqual(state.shape_home(), ROOT / "devices")


if __name__ == "__main__":
    unittest.main()
