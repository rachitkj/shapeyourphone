import json
import unittest

from helpers import ROOT

from shape import launcher_config as lc

VECTORS = json.loads((ROOT / "tests" / "vectors" / "rules.json").read_text())


class Validation(unittest.TestCase):
    def test_shipped_configs_are_valid(self):
        files = [ROOT / "config" / "default.json"] + sorted((ROOT / "config" / "examples").glob("*.json"))
        for f in files:
            r = lc.validate(json.loads(f.read_text()))
            self.assertEqual(r.errors, [], f.name)
            self.assertEqual(r.warnings, [], f.name)

    def test_errors(self):
        bad = {
            "version": 2,
            "theme": {"background": "blue", "iconStyle": "neon", "textSize": 99},
            "home": [{"type": "weather"}, {"type": "apps", "apps": ["not a package"]}],
            "gestures": {"swipeUp": "fly"},
            "rules": [{"from": "25:00"}, {"set": {"rules": []}}],
        }
        r = lc.validate(bad)
        text = "\n".join(r.errors)
        for needle in ("version", "background", "iconStyle", "textSize", "home[0]", "home[1].apps[0]", "swipeUp",
                       "rules[0].from", "rules[0]: needs both", "can't change 'rules'"):
            self.assertIn(needle, text)

    def test_unknown_keys_warn_and_missing_apps_warn(self):
        cfg = {"version": 1, "colour": "x", "dock": {"apps": ["com.not.installed"]}}
        r = lc.validate(cfg, installed={"com.whatsapp"})
        self.assertTrue(r.ok)
        self.assertTrue(any("colour" in w for w in r.warnings))
        self.assertTrue(any("not installed" in w for w in r.warnings))

    def test_role_tokens_and_components(self):
        cfg = {"version": 1, "dock": {"apps": ["@dialer", "@camera", "com.whatsapp/.Main"]}}
        self.assertTrue(lc.validate(cfg, installed={"com.whatsapp"}).ok)


class RuleVectors(unittest.TestCase):
    """Same vectors run by the Kotlin launcher's unit tests."""

    def test_active(self):
        for v in VECTORS["active"]:
            got = lc.is_active(v["rule"], v["day"], lc._minutes(v["time"]))
            self.assertEqual(got, v["active"], v)

    def test_merge(self):
        for v in VECTORS["merge"]:
            merged, hidden, active = lc.effective(v["config"], v["day"], lc._minutes(v["time"]))
            e = v["expect"]
            self.assertEqual(active, e["active"], v["name"])
            self.assertEqual(hidden, e["hidden"], v["name"])
            for k, val in e["theme"].items():
                self.assertEqual(merged["theme"][k], val, v["name"])
            self.assertEqual(merged["dock"]["apps"], e["dock_apps"], v["name"])
            self.assertNotIn("rules", merged)

    def test_parse_at(self):
        self.assertEqual(lc.parse_at("fri 22:30"), (5, 22 * 60 + 30))
        self.assertEqual(lc.parse_at("Sunday 00:00"), (7, 0))
        with self.assertRaises(ValueError):
            lc.parse_at("someday")


if __name__ == "__main__":
    unittest.main()
