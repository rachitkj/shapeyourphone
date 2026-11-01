import json
import unittest

from helpers import ROOT, PhoneTest

from shape import changes as ch
from shape import plans
from shape.safety import Guard, static_reason


class BloatData(unittest.TestCase):
    def test_lists_are_well_formed(self):
        seen = {}
        for f in sorted((ROOT / "shape" / "data" / "bloat").glob("*.json")):
            for e in json.loads(f.read_text()):
                for k in ("pkg", "name", "tier", "why", "breaks"):
                    self.assertIn(k, e, "%s: %s missing %s" % (f.name, e.get("pkg"), k))
                self.assertIn(e["tier"], plans.TIERS, e["pkg"])
                self.assertNotIn(e["pkg"], seen, "%s listed in both %s and %s" % (e["pkg"], seen.get(e["pkg"]), f.name))
                seen[e["pkg"]] = f.name

    def test_no_bloat_entry_is_protected(self):
        for pkg in plans.load_bloat():
            self.assertIsNone(static_reason(pkg), "%s is in a bloat list but also protected" % pkg)

    def test_static_protection(self):
        self.assertIsNotNone(static_reason("com.android.systemui"))
        self.assertIsNotNone(static_reason("com.android.providers.contacts"))
        self.assertIsNotNone(static_reason("com.samsung.android.knox.containercore"))
        self.assertIsNone(static_reason("com.samsung.android.app.tips"))


class Planning(PhoneTest):
    def test_scan_finds_bloat_and_unknowns(self):
        res = plans.scan(self.dev, self.ps)
        found = {b["pkg"]: b for b in res["bloat"]}
        self.assertIn("com.samsung.android.app.tips", found)
        self.assertIn("com.facebook.appmanager", found)
        self.assertEqual(found["com.samsung.android.bixby.agent"]["tier"], "optional")
        self.assertIn("com.samsung.android.app.notes", res["unreviewed_system_apps"])
        self.assertNotIn("com.whatsapp", res["unreviewed_system_apps"])  # user app
        self.assertNotIn("com.sec.android.app.camera", res["unreviewed_system_apps"])  # the camera app

    def test_dynamic_guard(self):
        g = Guard(self.dev, keep=["com.spotify.music"])
        self.assertFalse(g.check("com.samsung.android.honeyboard")[0])  # current keyboard
        self.assertFalse(g.check("com.google.android.webview")[0])
        self.assertFalse(g.check("com.sec.android.app.launcher")[0])
        self.assertFalse(g.check("com.spotify.music")[0])
        self.assertTrue(g.check("com.samsung.android.app.tips")[0])

    def test_tiers(self):
        safe = plans.make_debloat_plan(self.dev, self.ps, "safe", [], [])
        rec = plans.make_debloat_plan(self.dev, self.ps, "recommended", [], [])
        allp = plans.make_debloat_plan(self.dev, self.ps, "all", [], [])
        ps_ = lambda p: {a["pkg"] for a in p["actions"]}
        self.assertIn("com.facebook.appmanager", ps_(safe))
        self.assertNotIn("com.samsung.android.app.spage", ps_(safe))
        self.assertIn("com.samsung.android.app.spage", ps_(rec))
        self.assertNotIn("com.samsung.android.bixby.agent", ps_(rec))
        self.assertIn("com.samsung.android.bixby.agent", ps_(allp))

    def test_include_exclude_and_protected_include(self):
        p = plans.make_debloat_plan(self.dev, self.ps, "safe", ["com.samsung.android.bixby.agent", "com.android.systemui"],
                                    ["com.facebook.appmanager"])
        pk = {a["pkg"] for a in p["actions"]}
        self.assertIn("com.samsung.android.bixby.agent", pk)
        self.assertNotIn("com.facebook.appmanager", pk)
        self.assertNotIn("com.android.systemui", pk)
        self.assertIn("com.android.systemui", {b["pkg"] for b in p["blocked"]})

    def test_apply_falls_back_to_remove_and_everything_undoes(self):
        plan = plans.make_debloat_plan(self.dev, self.ps, "safe", [], [])
        before = {p: i["state"] for p, i in self.phone.pkgs.items()}
        summary = plans.apply_plan(self.dev, self.ps, plan, "test", echo=lambda *_: None)
        self.assertFalse(summary["failed"], summary["failed"])
        self.assertEqual(self.state("com.facebook.services"), "removed-for-user")  # disable was refused
        self.assertEqual(self.state("com.samsung.android.app.tips"), "disabled")
        log = ch.ChangeLog(self.ps)
        for c in sorted(log.applied(), key=lambda c: c.id, reverse=True):
            self.assertEqual(ch.undo_change(self.dev, log, c).status, "applied")
        after = {p: i["state"] for p, i in self.phone.pkgs.items()}
        self.assertEqual(before, after)
        self.assertTrue(self.ps.path("restore.sh").exists())

    def test_apply_blocks_protected_even_if_plan_was_edited(self):
        plan = {"actions": [{"op": "disable", "pkg": "com.android.systemui"},
                            {"op": "disable", "pkg": "com.samsung.android.honeyboard"}]}
        summary = plans.apply_plan(self.dev, self.ps, plan, "test", echo=lambda *_: None)
        self.assertEqual(len(summary["blocked"]), 2)
        self.assertEqual(self.state("com.android.systemui"), "enabled")

    def test_keep_list_respected(self):
        self.ps.set_keep(["com.samsung.android.app.tips"])
        plan = plans.make_debloat_plan(self.dev, self.ps, "safe", [], [])
        self.assertNotIn("com.samsung.android.app.tips", {a["pkg"] for a in plan["actions"]})


if __name__ == "__main__":
    unittest.main()
