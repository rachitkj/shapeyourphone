import json
import tempfile
import unittest

from helpers import ROOT, PhoneTest

from shape import LAUNCHER_PACKAGE
from shape import changes as ch
from shape import launcher as lz


class LauncherFlow(PhoneTest):
    def install(self):
        apk = tempfile.NamedTemporaryFile(suffix=".apk", delete=False)
        apk.write(b"fake")
        apk.close()
        lz.install(self.dev, self.ps, apk.name, echo=lambda *_: None)

    def test_install_sets_home_and_uninstall_restores_it(self):
        stock = self.phone.home
        self.install()
        self.assertIn(LAUNCHER_PACKAGE, self.phone.pkgs)
        self.assertTrue(self.phone.home.startswith(LAUNCHER_PACKAGE + "/"))
        self.assertTrue(lz.status(self.dev)["is_default_home"])
        lz.uninstall(self.dev, self.ps, echo=lambda *_: None)
        self.assertNotIn(LAUNCHER_PACKAGE, self.phone.pkgs)
        self.assertEqual(self.phone.home.split("/")[0], stock.split("/")[0])

    def test_push_history_and_rollback(self):
        self.install()
        a = json.loads((ROOT / "config" / "default.json").read_text())
        b = json.loads((ROOT / "config" / "examples" / "minimal-text.json").read_text())
        ha, _ = lz.push(self.dev, self.ps, a)
        hb, cb = lz.push(self.dev, self.ps, b)
        self.assertNotEqual(ha, hb)
        self.assertEqual(lz.get_config(self.dev)["name"], "Minimal text")
        # history: the launcher's own initial config + 2 pushes
        self.assertEqual(len(lz.history(self.ps)), 3)
        stem, h = lz.rollback(self.dev, self.ps)
        self.assertEqual(lz.get_config(self.dev)["name"], "Default")
        # undoing the 'b' push through the change log also rolls back
        lz.push(self.dev, self.ps, b)
        log = ch.ChangeLog(self.ps)
        last = log.applied()[-1]
        self.assertEqual(last.kind, "launcher.config")
        r = ch.undo_change(self.dev, log, last, lz.undo_config_change(self.dev, self.ps))
        self.assertEqual(r.status, "applied", r.message)
        self.assertEqual(lz.get_config(self.dev)["name"], "Default")

    def test_large_config_is_chunked(self):
        self.install()
        cfg = json.loads((ROOT / "config" / "default.json").read_text())
        cfg["labels"] = {"com.whatsapp": "x" * 30000}
        lz.push(self.dev, self.ps, cfg)
        appends = [l for l in self.phone.log if "stage_append" in l]
        self.assertGreater(len(appends), 2)
        self.assertEqual(lz.get_config(self.dev)["labels"]["com.whatsapp"], "x" * 30000)

    def test_invalid_config_rejected_before_sending(self):
        self.install()
        with self.assertRaises(lz.LauncherError):
            lz.push(self.dev, self.ps, {"version": 1, "theme": {"background": "nope"}})
        self.assertFalse(any("stage_commit" in l for l in self.phone.log))

    def test_not_installed_message(self):
        with self.assertRaises(lz.LauncherError) as e:
            lz.status(self.dev)
        self.assertIn("not installed", str(e.exception))

    def test_list_apps_has_labels(self):
        self.install()
        apps = {a["package"]: a["label"] for a in lz.list_apps(self.dev)}
        self.assertEqual(apps["com.whatsapp"], "WhatsApp")
        self.assertNotIn(LAUNCHER_PACKAGE, apps)


if __name__ == "__main__":
    unittest.main()
