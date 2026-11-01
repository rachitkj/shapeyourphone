"""End-to-end through the CLI, the way an agent would drive it."""

import contextlib
import io
import json
import unittest
from unittest import mock

from helpers import PhoneTest

from shape import cli
from shape import privacy


class Cli(PhoneTest):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with mock.patch.object(cli, "pick_device", return_value=self.dev), contextlib.redirect_stdout(buf):
            code = cli.main(list(argv))
        return code, buf.getvalue()

    def test_full_session(self):
        code, out = self.run_cli("init")
        self.assertEqual(code, 0, out)
        self.assertTrue(self.ps.path("preferences.md").exists())
        self.assertTrue(self.ps.first_snapshot())

        code, out = self.run_cli("scan", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["bloat"])

        code, out = self.run_cli("plan", "--tier", "safe")
        self.assertEqual(code, 0, out)
        plan_path = out.split("Plan: ")[1].splitlines()[0].strip()

        # without --yes and without a TTY nothing happens
        code, out = self.run_cli("apply", plan_path)
        self.assertEqual(code, 2)
        self.assertEqual(self.state("com.samsung.android.app.tips"), "enabled")

        code, out = self.run_cli("apply", plan_path, "--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.state("com.samsung.android.app.tips"), "disabled")

        code, out = self.run_cli("tweak", "animations", "0.5", "--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.phone.settings["global"]["animator_duration_scale"], "0.5")

        code, out = self.run_cli("tweak", "private-dns", "adguard", "--yes")
        self.assertEqual(self.phone.settings["global"]["private_dns_specifier"], "dns.adguard-dns.com")

        code, out = self.run_cli("tweak", "notifications-off", "com.whatsapp", "--yes")
        self.assertFalse(self.phone.perms[("com.whatsapp", "android.permission.POST_NOTIFICATIONS")])

        code, out = self.run_cli("changes", "--json")
        self.assertGreaterEqual(len(json.loads(out)), 6)

        code, out = self.run_cli("drift")
        self.assertIn("still in place", out)

        code, out = self.run_cli("report")
        self.assertEqual(code, 0, out)

        code, out = self.run_cli("restore", "--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.state("com.samsung.android.app.tips"), "enabled")
        self.assertEqual(self.phone.settings["global"]["animator_duration_scale"], "1.0")
        self.assertNotIn("private_dns_mode", self.phone.settings["global"])
        self.assertTrue(self.phone.perms[("com.whatsapp", "android.permission.POST_NOTIFICATIONS")])

    def test_keep_and_pkg(self):
        self.run_cli("keep", "com.samsung.android.app.tips")
        code, out = self.run_cli("pkg", "disable", "com.samsung.android.app.tips", "--yes")
        self.assertIn("BLOCKED", out)
        self.assertEqual(self.state("com.samsung.android.app.tips"), "enabled")

    def test_privacy(self):
        code, out = self.run_cli("privacy", "--json")
        self.assertEqual(code, 0, out)
        apps = {a["pkg"]: a for a in json.loads(out)["apps"]}
        self.assertIn("camera", apps["com.instagram.android"]["access"])

    def test_privacy_parser_ignores_other_users(self):
        dump = """Packages:
  Package [com.a] (1):
    User 0: installed=true
      runtime permissions:
        android.permission.CAMERA: granted=true, flags=[ ]
    User 10: installed=true
      runtime permissions:
        android.permission.RECORD_AUDIO: granted=true, flags=[ ]
  Package [com.b] (2):
    User 0: installed=true
      runtime permissions:
        android.permission.CAMERA: granted=false, flags=[ ]
"""
        r = privacy.granted_runtime_permissions(dump, "0")
        self.assertEqual(r, {"com.a": ["android.permission.CAMERA"]})


if __name__ == "__main__":
    unittest.main()
