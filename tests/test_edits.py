import contextlib
import io
import json
import tempfile
import unittest
from unittest import mock

from helpers import ROOT, PhoneTest

from shape import cli
from shape import edits as ed
from shape import launcher as lz
from shape import launcher_config as lc

APPS = [
    {"package": "com.whatsapp", "label": "WhatsApp"},
    {"package": "com.instagram.android", "label": "Instagram"},
    {"package": "com.spotify.music", "label": "Spotify"},
    {"package": "com.google.android.apps.photos", "label": "Photos"},
    {"package": "com.samsung.android.gallery", "label": "Gallery"},
    {"package": "com.samsung.android.app.notes", "label": "Samsung Notes"},
    {"package": "com.google.android.keep", "label": "Keep Notes"},
]


class Resolver(unittest.TestCase):
    r = ed.AppResolver(APPS)

    def test_exact_prefix_contains_package_token(self):
        self.assertEqual(self.r.resolve("whatsapp"), "com.whatsapp")
        self.assertEqual(self.r.resolve("Insta"), "com.instagram.android")
        self.assertEqual(self.r.resolve("Gall"), "com.samsung.android.gallery")
        self.assertEqual(self.r.resolve("com.spotify.music"), "com.spotify.music")
        self.assertEqual(self.r.resolve("@camera"), "@camera")

    def test_ambiguous_and_unknown(self):
        with self.assertRaises(ed.EditError) as e:
            self.r.resolve("notes")
        self.assertIn("several", str(e.exception))
        with self.assertRaises(ed.EditError):
            self.r.resolve("Tiktok")
        with self.assertRaises(ed.EditError):
            self.r.resolve("@teleporter")

    def test_resolve_all_splits_commas_and_dedupes(self):
        self.assertEqual(self.r.resolve_all(["WhatsApp, Spotify", "whatsapp"]), ["com.whatsapp", "com.spotify.music"])


class PureEdits(unittest.TestCase):
    base = json.loads((ROOT / "config" / "default.json").read_text())

    def test_every_edit_keeps_config_valid(self):
        cfg = self.base
        cfg = ed.hide(cfg, ["com.instagram.android"], ed.when("weekdays", "09:00", "18:00"))
        cfg = ed.hide(cfg, ["com.spotify.music"], ed.when("weekdays", "09:00", "18:00"))
        cfg = ed.hide(cfg, ["com.whatsapp"])
        cfg = ed.search_only(cfg, ["com.whatsapp"])
        cfg = ed.dock(cfg, ["com.whatsapp", "@camera"])
        cfg = ed.home_apps(cfg, ["com.spotify.music"], style="grid")
        cfg = ed.theme(cfg, background="wallpaper", iconStyle="mono", dim=0.4)
        cfg = ed.gesture(cfg, "doubleTap", "app:com.spotify.music")
        cfg = ed.rename(cfg, "com.whatsapp", "Chats")
        cfg = ed.pause(cfg, ["com.instagram.android"], seconds=8, message="Breathe.")
        r = lc.validate(cfg)
        self.assertEqual(r.errors, [])
        # same time window -> one rule with both apps
        self.assertEqual(len(cfg["rules"]), 1)
        self.assertEqual(cfg["rules"][0]["name"], "Weekdays 09:00–18:00")
        self.assertEqual(cfg["rules"][0]["hide"], ["com.instagram.android", "com.spotify.music"])
        # search-only moved WhatsApp out of hidden
        self.assertNotIn("com.whatsapp", cfg["drawer"]["hidden"])
        self.assertIn("com.whatsapp", cfg["drawer"]["searchOnly"])
        # the original is untouched
        self.assertNotIn("rules", self.base) if "rules" not in self.base else self.assertEqual(self.base["rules"], [])

    def test_unhide_cleans_up_empty_rules(self):
        cfg = ed.hide(self.base, ["com.instagram.android"], ed.when(None, "22:00", "07:00"))
        cfg = ed.unhide(cfg, ["com.instagram.android"])
        self.assertEqual(cfg["rules"], [])

    def test_home_apps_inserts_after_flex_spacer(self):
        cfg = ed.home_apps(self.base, ["com.whatsapp"])
        types = [w["type"] for w in cfg["home"]]
        self.assertEqual(types.index("apps"), types.index("spacer") + 1)
        cfg2 = ed.home_apps(cfg, ["com.spotify.music"], mode="add")
        apps = [w for w in cfg2["home"] if w["type"] == "apps"][0]["apps"]
        self.assertEqual(apps, ["com.whatsapp", "com.spotify.music"])

    def test_when_parsing(self):
        self.assertIsNone(ed.when(None, None, None))
        self.assertEqual(ed.when("everyday", None, None), None)
        self.assertEqual(ed.when("sat,sun", None, None), {"days": ["sat", "sun"]})
        for bad in (("funday", None, None), (None, "22:00", None), (None, "25:00", "07:00")):
            with self.assertRaises(ed.EditError):
                ed.when(*bad)

    def test_pause_remove_last_drops_section(self):
        cfg = ed.pause(self.base, ["com.whatsapp"])
        cfg = ed.pause(cfg, ["com.whatsapp"], mode="remove")
        self.assertNotIn("pause", cfg)


class CliEdits(PhoneTest):
    def setUp(self):
        super().setUp()
        apk = tempfile.NamedTemporaryFile(suffix=".apk", delete=False)
        apk.close()
        lz.install(self.dev, self.ps, apk.name, echo=lambda *_: None)
        lz.push(self.dev, self.ps, json.loads((ROOT / "config" / "default.json").read_text()))

    def run_cli(self, *argv):
        buf = io.StringIO()
        with mock.patch.object(cli, "pick_device", return_value=self.dev), \
                contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = cli.main(list(argv))
        return code, buf.getvalue()

    def phone_cfg(self):
        return lz.get_config(self.dev)

    def test_hide_by_name_with_time(self):
        code, out = self.run_cli("launcher", "hide", "Instagram", "--days", "weekdays", "--from", "09:00", "--to", "18:00")
        self.assertEqual(code, 2)  # needs --yes
        self.assertIn("+ Rule 'Weekdays 09:00–18:00'", out)
        self.assertNotIn("rules", self.phone_cfg()) if "rules" not in self.phone_cfg() else self.assertEqual(self.phone_cfg()["rules"], [])
        code, out = self.run_cli("launcher", "hide", "Instagram", "--days", "weekdays", "--from", "09:00", "--to", "18:00", "--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.phone_cfg()["rules"][0]["hide"], ["com.instagram.android"])

    def test_dock_theme_rename_pause_and_rollback(self):
        self.assertEqual(self.run_cli("launcher", "dock", "WhatsApp", "Spotify", "--yes")[0], 0)
        self.assertEqual(self.phone_cfg()["dock"]["apps"], ["com.whatsapp", "com.spotify.music"])
        self.assertEqual(self.run_cli("launcher", "theme", "--icons", "grayscale", "--font", "serif", "--yes")[0], 0)
        self.assertEqual(self.phone_cfg()["theme"]["iconStyle"], "grayscale")
        self.assertEqual(self.run_cli("launcher", "rename", "whatsapp", "Chats", "--yes")[0], 0)
        self.assertEqual(self.phone_cfg()["labels"]["com.whatsapp"], "Chats")
        self.assertEqual(self.run_cli("launcher", "pause", "Instagram", "--seconds", "10", "--yes")[0], 0)
        self.assertEqual(self.phone_cfg()["pause"], {"apps": ["com.instagram.android"], "seconds": 10})
        self.assertEqual(self.run_cli("launcher", "gesture", "doubleTap", "Spotify", "--yes")[0], 0)
        self.assertEqual(self.phone_cfg()["gestures"]["doubleTap"], "app:com.spotify.music")
        self.run_cli("launcher", "rollback")
        self.assertEqual(self.phone_cfg()["gestures"]["doubleTap"], "none")

    def test_no_change_and_errors(self):
        code, out = self.run_cli("launcher", "dock", "@dialer", "@sms", "@browser", "@camera", "--yes")
        self.assertIn("No change", out)
        code, out = self.run_cli("launcher", "dock", "Nonexistent App", "--yes")
        self.assertEqual(code, 2)
        self.assertIn("No app called", out)
        code, out = self.run_cli("launcher", "theme", "--background", "blue", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("background", out)

    def test_rules_list_and_remove(self):
        self.run_cli("launcher", "hide", "Instagram", "--from", "22:00", "--to", "07:00", "--name", "Night", "--yes")
        code, out = self.run_cli("launcher", "rules")
        self.assertIn("Rule 'Night'", out)
        self.assertEqual(self.run_cli("launcher", "rule-remove", "Night", "--yes")[0], 0)
        self.assertEqual(self.phone_cfg()["rules"], [])


if __name__ == "__main__":
    unittest.main()
