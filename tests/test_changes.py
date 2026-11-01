import subprocess
import unittest

from helpers import PhoneTest

from amos import changes as ch


class ChangeRoundTrips(PhoneTest):
    def test_disable_then_undo(self):
        log = ch.ChangeLog(self.ps)
        op = ch.op_package_disable(self.dev, "com.samsung.android.app.tips")
        self.assertEqual(op.before, "enabled")
        r = ch.execute(self.dev, log, op, "test")
        self.assertEqual(r.status, "applied")
        self.assertEqual(self.state("com.samsung.android.app.tips"), "disabled")
        u = ch.undo_change(self.dev, log, r.change)
        self.assertEqual(u.status, "applied")
        self.assertEqual(self.state("com.samsung.android.app.tips"), "enabled")
        self.assertEqual(log.get(r.change.id).status, "undone")

    def test_disable_already_disabled_is_noop(self):
        self.phone.pkgs["com.samsung.android.app.tips"]["state"] = "disabled"
        log = ch.ChangeLog(self.ps)
        r = ch.execute(self.dev, log, ch.op_package_disable(self.dev, "com.samsung.android.app.tips"), "test")
        self.assertEqual(r.status, "skipped")
        self.assertEqual(log.changes, [])

    def test_refused_disable_is_logged_as_failed(self):
        log = ch.ChangeLog(self.ps)
        r = ch.execute(self.dev, log, ch.op_package_disable(self.dev, "com.facebook.services"), "test")
        self.assertEqual(r.status, "failed")
        self.assertIn("Cannot disable", r.message)
        self.assertEqual(log.applied(), [])

    def test_remove_for_user_then_undo(self):
        log = ch.ChangeLog(self.ps)
        r = ch.execute(self.dev, log, ch.op_package_remove(self.dev, "com.facebook.appmanager"), "test")
        self.assertEqual(r.status, "applied")
        self.assertEqual(self.state("com.facebook.appmanager"), "removed-for-user")
        self.assertEqual(ch.undo_change(self.dev, log, r.change).status, "applied")
        self.assertEqual(self.state("com.facebook.appmanager"), "enabled")

    def test_remove_of_disabled_package_restores_disabled(self):
        self.phone.pkgs["com.samsung.android.tvplus"]["state"] = "disabled"
        log = ch.ChangeLog(self.ps)
        r = ch.execute(self.dev, log, ch.op_package_remove(self.dev, "com.samsung.android.tvplus"), "test")
        self.assertEqual(r.status, "applied")
        ch.undo_change(self.dev, log, r.change)
        self.assertEqual(self.state("com.samsung.android.tvplus"), "disabled")

    def test_setting_put_and_undo_previous_value(self):
        log = ch.ChangeLog(self.ps)
        r = ch.execute(self.dev, log, ch.op_setting(self.dev, "global", "window_animation_scale", "0.5"), "t")
        self.assertEqual(self.phone.settings["global"]["window_animation_scale"], "0.5")
        ch.undo_change(self.dev, log, r.change)
        self.assertEqual(self.phone.settings["global"]["window_animation_scale"], "1.0")

    def test_setting_undo_deletes_when_previously_unset(self):
        log = ch.ChangeLog(self.ps)
        r = ch.execute(self.dev, log, ch.op_setting(self.dev, "global", "private_dns_mode", "hostname"), "t")
        self.assertEqual(r.change.before, "null")
        ch.undo_change(self.dev, log, r.change)
        self.assertNotIn("private_dns_mode", self.phone.settings["global"])

    def test_permission_revoke_and_undo(self):
        log = ch.ChangeLog(self.ps)
        r = ch.execute(self.dev, log, ch.op_permission(self.dev, "com.instagram.android", "android.permission.CAMERA", False), "t")
        self.assertEqual(r.status, "applied")
        self.assertFalse(self.phone.perms[("com.instagram.android", "android.permission.CAMERA")])
        ch.undo_change(self.dev, log, r.change)
        self.assertTrue(self.phone.perms[("com.instagram.android", "android.permission.CAMERA")])

    def test_appop_and_standby_undo_to_defaults(self):
        log = ch.ChangeLog(self.ps)
        a = ch.execute(self.dev, log, ch.op_appop(self.dev, "com.spotify.music", "RUN_ANY_IN_BACKGROUND", "ignore"), "t")
        s = ch.execute(self.dev, log, ch.op_standby(self.dev, "com.spotify.music", "restricted"), "t")
        self.assertEqual((a.status, s.status), ("applied", "applied"))
        ch.undo_change(self.dev, log, s.change)
        ch.undo_change(self.dev, log, a.change)
        self.assertNotIn(("com.spotify.music", "RUN_ANY_IN_BACKGROUND"), self.phone.appops)
        self.assertEqual(self.phone.buckets["com.spotify.music"], 10)

    def test_night_mode(self):
        log = ch.ChangeLog(self.ps)
        r = ch.execute(self.dev, log, ch.op_night_mode(self.dev, "yes"), "t")
        self.assertEqual(self.phone.night, "yes")
        ch.undo_change(self.dev, log, r.change)
        self.assertEqual(self.phone.night, "no")

    def test_drift_detects_and_reapply_command_fixes(self):
        log = ch.ChangeLog(self.ps)
        ch.execute(self.dev, log, ch.op_package_disable(self.dev, "com.samsung.android.app.tips"), "t")
        ch.execute(self.dev, log, ch.op_setting(self.dev, "system", "font_scale", "1.15"), "t")
        self.assertEqual(ch.drift(self.dev, log), [])
        # a system update re-enables the app and resets the font
        self.phone.pkgs["com.samsung.android.app.tips"]["state"] = "enabled"
        self.phone.settings["system"]["font_scale"] = "1.0"
        d = ch.drift(self.dev, log)
        self.assertEqual({x["target"] for x in d}, {"com.samsung.android.app.tips", "system/font_scale"})
        for x in d:
            self.dev.sh(x["redo"])
        self.assertEqual(ch.drift(self.dev, log), [])

    def test_restore_script_is_reverse_order_and_runs(self):
        log = ch.ChangeLog(self.ps)
        ch.execute(self.dev, log, ch.op_package_disable(self.dev, "com.samsung.android.app.tips"), "t")
        ch.execute(self.dev, log, ch.op_setting(self.dev, "global", "window_animation_scale", "0.5"), "t")
        script = ch.restore_script(log)
        i_setting = script.index("window_animation_scale")
        i_pkg = script.index("pm enable")
        self.assertLess(i_setting, i_pkg, "newest change must be undone first")
        # every undo line must be valid sh (host-side quoting)
        r = subprocess.run(["sh", "-n"], input=script.encode(), capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_change_log_persists(self):
        log = ch.ChangeLog(self.ps)
        ch.execute(self.dev, log, ch.op_package_disable(self.dev, "com.samsung.android.app.tips"), "t")
        again = ch.ChangeLog(self.ps)
        self.assertEqual(len(again.applied()), 1)
        self.assertEqual(again.applied()[0].target, "com.samsung.android.app.tips")


if __name__ == "__main__":
    unittest.main()
