import contextlib
import io
import json
import tempfile
import unittest
from unittest import mock

from helpers import ROOT, PhoneTest

from fakephone import FakePhone
from shape import changes as ch
from shape import cli
from shape import clone as cl
from shape import insights
from shape import launcher as lz
from shape.adb import Device
from shape.state import PhoneState


class Base(PhoneTest):
    def run_cli(self, dev, *argv):
        buf = io.StringIO()
        with mock.patch.object(cli, "pick_device", return_value=dev), \
                contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = cli.main(list(argv))
        return code, buf.getvalue()

    def install(self, dev, ps):
        apk = tempfile.NamedTemporaryFile(suffix=".apk", delete=False)
        apk.close()
        with mock.patch.object(lz, "find_local_apk", return_value=apk.name):
            lz.install(dev, ps, apk.name, echo=lambda *_: None)


class Clone(Base):
    def test_new_phone_gets_same_changes_and_home_screen(self):
        # old phone: debloat, tweak, revoke a permission, custom home screen, notes
        self.run_cli(self.dev, "init")
        self.run_cli(self.dev, "pkg", "disable", "com.samsung.android.app.tips", "--yes")
        self.run_cli(self.dev, "tweak", "animations", "0.5", "--yes")
        self.run_cli(self.dev, "perm", "revoke", "com.instagram.android", "android.permission.CAMERA", "--yes")
        self.run_cli(self.dev, "keep", "com.spotify.music")
        self.install(self.dev, self.ps)
        lz.push(self.dev, self.ps, json.loads((ROOT / "config/examples/minimal-text.json").read_text()))
        self.ps.path("preferences.md").write_text("# Preferences\n- dark and minimal\n\n## History\n")

        # new phone: different serial, Instagram not installed
        new = FakePhone(serial="NEWPHONE999")
        new.props["ro.serialno"] = "NEWPHONE999"
        new.props["ro.product.model"] = "SM-S921B"
        del new.pkgs["com.instagram.android"]
        ndev = Device(new.serial, runner=new.runner)
        nps = PhoneState(ndev)
        self.assertNotEqual(nps.key, self.ps.key)

        code, out = self.run_cli(ndev, "phones")
        self.assertIn(self.ps.key, out)
        code, out = self.run_cli(ndev, "clone", "--from", self.ps.key[:12])
        self.assertEqual(code, 2, out)  # shows plan, needs --yes
        self.assertIn("disable", out)
        with mock.patch.object(lz, "find_local_apk", return_value=tempfile.NamedTemporaryFile(suffix=".apk", delete=False).name):
            code, out = self.run_cli(ndev, "clone", "--from", self.ps.key[:12], "--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(new.pkgs["com.samsung.android.app.tips"]["state"], "disabled")
        self.assertEqual(new.settings["global"]["animator_duration_scale"], "0.5")
        self.assertIn("1 change(s) skipped", out)  # the Instagram permission
        self.assertEqual(lz.get_config(ndev)["name"], "Minimal text")
        self.assertIn("dark and minimal", nps.path("preferences.md").read_text())
        self.assertIn("cloned from", nps.path("preferences.md").read_text())
        self.assertEqual(nps.keep(), ["com.spotify.music"])
        # and it is all reversible on the new phone too
        code, out = self.run_cli(ndev, "restore", "--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(new.pkgs["com.samsung.android.app.tips"]["state"], "enabled")

    def test_clone_from_self_refused(self):
        self.run_cli(self.dev, "init")
        code, out = self.run_cli(self.dev, "clone", "--from", self.ps.key)
        self.assertEqual(code, 2)
        self.assertIn("That's this phone", out)


class Suggest(Base):
    def test_needs_usage_access_then_suggests(self):
        self.install(self.dev, self.ps)
        code, out = self.run_cli(self.dev, "suggest")
        self.assertEqual(code, 2)
        self.assertIn("usage-access", out)
        self.assertEqual(self.run_cli(self.dev, "launcher", "usage-access", "--yes")[0], 0)
        code, out = self.run_cli(self.dev, "suggest", "--json")
        self.assertEqual(code, 0, out)
        res = json.loads(out)
        self.assertEqual(res["put_in_reach"][0]["package"], "com.whatsapp")
        self.assertEqual({u["package"] for u in res["heavy_use"]}, {"com.whatsapp", "com.instagram.android"})
        unused = {u["package"]: u for u in res["unused"]}
        self.assertIn("disable with shape", unused["com.samsung.android.app.tips"]["option"])
        self.assertIsNone(unused["com.samsung.android.app.notes"]["last_used_days_ago"])
        # granting usage access is a normal, undoable change
        log = ch.ChangeLog(self.ps)
        self.assertEqual(log.applied()[-1].target, "io.github.rachitkj.shape GET_USAGE_STATS")

    def test_suggest_logic_respects_dock_and_hidden(self):
        usage = [{"package": "a.x", "label": "X", "foreground_ms": 10 * 3_600_000, "last_used": 1},
                 {"package": "a.y", "label": "Y", "foreground_ms": 1, "last_used": 1}]
        cfg = {"dock": {"apps": ["a.x"]}, "drawer": {"hidden": ["a.y"]}}
        res = insights.suggest(usage, cfg, 10, lambda p: True, lambda p: False, now_ms=10 ** 12)
        self.assertEqual(res["put_in_reach"], [])
        self.assertEqual(res["unused"], [])


class ShareReport(Base):
    def test_report_is_anonymous(self):
        self.run_cli(self.dev, "init")
        self.run_cli(self.dev, "plan", "--tier", "safe")
        plan = sorted(self.ps.path("plans").glob("*.json"))[-1]
        self.run_cli(self.dev, "apply", str(plan), "--yes")
        self.run_cli(self.dev, "perm", "revoke", "com.whatsapp", "android.permission.READ_CONTACTS", "--yes")
        code, out = self.run_cli(self.dev, "report", "--share")
        self.assertEqual(code, 0, out)
        self.assertIn("SM-A546B", out)
        self.assertIn("`com.samsung.android.app.tips`", out)  # bloat that worked
        self.assertIn("Cannot disable a protected package", out)  # the failure, for maintainers
        for private in ("R58TEST123", "abcdef0123456789", self.ps.key, "com.whatsapp"):
            self.assertNotIn(private, out)

    def test_restore_ps1_written(self):
        self.run_cli(self.dev, "pkg", "disable", "com.samsung.android.app.tips", "--yes")
        ps1 = self.ps.path("restore.ps1").read_bytes()
        self.assertIn(b"\r\n", ps1)
        self.assertIn(b"& $adb @s shell 'pm enable --user 0 com.samsung.android.app.tips'", ps1)


if __name__ == "__main__":
    unittest.main()
