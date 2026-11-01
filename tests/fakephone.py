"""A stateful fake Android phone that answers the adb commands shape sends.

Not a full emulator — just enough of pm/settings/cmd/dumpsys/content to verify
that every change shape makes is applied, verified, logged and undone correctly.
"""

from __future__ import annotations

import base64
import hashlib
import json
import shlex
from typing import Dict, List, Optional, Tuple

LAUNCHER = "io.github.rachitkj.shape"
AUTH = LAUNCHER + ".control"

PROPS = {
    "ro.product.manufacturer": "samsung",
    "ro.product.brand": "samsung",
    "ro.product.model": "SM-A546B",
    "ro.product.device": "a54x",
    "ro.build.version.release": "14",
    "ro.build.version.sdk": "34",
    "ro.build.version.oneui": "60101",
    "ro.build.display.id": "UP1A.231005.007.A546BXXU7CXA1",
    "ro.build.version.security_patch": "2024-01-01",
    "ro.serialno": "R58TEST123",
}

# pkg: (system, launcher_activity or None, label)
PACKAGES = {
    "android": (True, None, "Android System"),
    "com.android.systemui": (True, None, "System UI"),
    "com.android.settings": (True, ".Settings", "Settings"),
    "com.google.android.gms": (True, None, "Google Play services"),
    "com.android.vending": (True, ".AssetBrowserActivity", "Play Store"),
    "com.google.android.webview": (True, None, "Android System WebView"),
    "com.android.chrome": (True, "com.google.android.apps.chrome.Main", "Chrome"),
    "com.sec.android.app.launcher": (True, None, "One UI Home"),
    "com.samsung.android.honeyboard": (True, None, "Samsung Keyboard"),
    "com.samsung.android.dialer": (True, ".DialtactsActivity", "Phone"),
    "com.samsung.android.messaging": (True, ".ui.ConversationComposer", "Messages"),
    "com.sec.android.app.camera": (True, ".Camera", "Camera"),
    "com.samsung.android.app.tips": (True, ".TipsActivity", "Tips"),
    "com.samsung.android.tvplus": (True, ".MainActivity", "Samsung TV Plus"),
    "com.facebook.appmanager": (True, None, "Meta App Manager"),
    "com.facebook.services": (True, None, "Meta Services"),
    "com.samsung.android.bixby.agent": (True, ".MainActivity", "Bixby"),
    "com.samsung.android.app.spage": (True, None, "Samsung Free"),
    "com.samsung.android.app.notes": (True, ".MainActivity", "Samsung Notes"),
    "com.whatsapp": (False, ".Main", "WhatsApp"),
    "com.instagram.android": (False, ".activity.MainTabActivity", "Instagram"),
    "com.spotify.music": (False, ".MainActivity", "Spotify"),
}


def _split_commands(cmd: str) -> List[List[str]]:
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=";&")
    lex.whitespace_split = True
    cmds, cur = [], []
    for tok in lex:
        if tok in (";", "&&", "&"):
            if cur:
                cmds.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        cmds.append(cur)
    return cmds


class FakePhone:
    def __init__(self, serial: str = "R58TEST123", sdk: int = 34):
        self.serial = serial
        self.props = dict(PROPS)
        self.props["ro.build.version.sdk"] = str(sdk)
        self.sdk = sdk
        self.pkgs: Dict[str, dict] = {
            p: {"system": s, "activity": a, "label": l, "state": "enabled"} for p, (s, a, l) in PACKAGES.items()
        }
        self.settings = {
            "global": {"window_animation_scale": "1.0", "transition_animation_scale": "1.0", "animator_duration_scale": "1.0",
                       "webview_provider": "com.google.android.webview"},
            "secure": {"default_input_method": "com.samsung.android.honeyboard/.service.HoneyBoardService",
                       "enabled_input_methods": "com.samsung.android.honeyboard/.service.HoneyBoardService",
                       "android_id": "abcdef0123456789"},
            "system": {"font_scale": "1.0", "screen_off_timeout": "30000"},
        }
        self.perms = {("com.instagram.android", "android.permission.CAMERA"): True,
                      ("com.instagram.android", "android.permission.ACCESS_FINE_LOCATION"): True,
                      ("com.whatsapp", "android.permission.READ_CONTACTS"): True,
                      ("com.whatsapp", "android.permission.POST_NOTIFICATIONS"): True}
        self.appops: Dict[Tuple[str, str], str] = {}
        self.buckets: Dict[str, int] = {}
        self.night = "no"
        self.home: Optional[str] = "com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity"
        self.refuse_disable = {"com.facebook.services"}  # simulate an OEM refusing disable-user
        self.provider_config: Optional[str] = None
        self.stage = ""
        self.log: List[str] = []

    # -- adb entry point ------------------------------------------------------
    def runner(self, argv: List[str], timeout: int, stdin: Optional[bytes]) -> Tuple[int, str, str]:
        args = argv[1:]
        if args[:1] == ["devices"]:
            return 0, "List of devices attached\n%s device product:a54x model:SM_A546B device:a54x\n" % self.serial, ""
        if args[:1] == ["-s"]:
            args = args[2:]
        if args[:1] == ["install"]:
            self.pkgs[LAUNCHER] = {"system": False, "activity": ".HomeActivity", "label": "Shape", "state": "enabled"}
            if self.provider_config is None:
                self.provider_config = json.dumps({"version": 1, "name": "Default"}, indent=2) + "\n"
            return 0, "Performing Streamed Install\nSuccess\n", ""
        if args[:1] == ["shell"]:
            out = []
            for c in _split_commands(args[1]):
                self.log.append(" ".join(c))
                out.append(self.exec(c))
            return 0, "\n".join(o for o in out if o), ""
        return 1, "", "unsupported: %s" % args

    # -- shell ---------------------------------------------------------------
    def _user_flag(self, c: List[str]) -> List[str]:
        if "--user" in c:
            i = c.index("--user")
            return c[:i] + c[i + 2:]
        return c

    def exec(self, c: List[str]) -> str:
        if c == ["getprop"]:
            return "\n".join("[%s]: [%s]" % kv for kv in self.props.items())
        if c[:2] == ["am", "get-current-user"]:
            return "0"
        if c[0] == "settings":
            return self._settings(c)
        if c[0] == "pm":
            return self._pm(self._user_flag(c))
        if c[:2] == ["cmd", "package"]:
            return self._cmd_package(self._user_flag(c))
        if c[:2] == ["cmd", "role"]:
            c = self._user_flag(c)
            if c[2] == "get-role-holders":
                return {"android.app.role.HOME": self.home.split("/")[0] if self.home else "",
                        "android.app.role.DIALER": "com.samsung.android.dialer",
                        "android.app.role.SMS": "com.samsung.android.messaging"}.get(c[3], "")
            if c[2] == "add-role-holder" and c[3] == "android.app.role.HOME":
                pkg = c[4]
                act = self.pkgs.get(pkg, {}).get("activity") if pkg != "com.sec.android.app.launcher" else None
                if pkg == "com.sec.android.app.launcher":
                    self.home = "com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity"
                elif pkg in self.pkgs:
                    self.home = pkg + "/" + (act or ".Home")
                return ""
            return ""
        if c[:2] == ["cmd", "appops"]:
            return self._appops(self._user_flag(c))
        if c[:2] == ["am", "get-standby-bucket"]:
            return str(self.buckets.get(c[2], 10))
        if c[:2] == ["am", "set-standby-bucket"]:
            names = {"active": 10, "working_set": 20, "frequent": 30, "rare": 40, "restricted": 45}
            self.buckets[c[2]] = names[c[3]]
            return ""
        if c[:2] == ["am", "start"]:
            return "Starting: Intent"
        if c[:3] == ["cmd", "uimode", "night"]:
            if len(c) > 3:
                self.night = c[3]
            return "Night mode: %s" % self.night
        if c[0] == "dumpsys":
            return self._dumpsys(c[1:])
        if c[:2] == ["content", "call"]:
            return self._content_call(c)
        return "/system/bin/sh: %s: inaccessible or not found" % c[0]

    def _settings(self, c: List[str]) -> str:
        op, ns = c[1], c[2]
        if op == "get":
            return self.settings[ns].get(c[3], "null")
        if op == "put":
            self.settings[ns][c[3]] = c[4]
            return ""
        if op == "delete":
            self.settings[ns].pop(c[3], None)
            return "Deleted 1 rows"
        if op == "list":
            return "\n".join("%s=%s" % kv for kv in self.settings[ns].items())
        return ""

    def _visible(self, pkg: str) -> bool:
        return pkg in self.pkgs and self.pkgs[pkg]["state"] != "absent"

    def _pm(self, c: List[str]) -> str:
        sub = c[1]
        if sub == "list" and c[2] == "packages":
            flags = [a for a in c[3:] if a.startswith("-")]
            filt = [a for a in c[3:] if not a.startswith("-")]
            res = []
            for p, info in sorted(self.pkgs.items()):
                st = info["state"]
                if st == "absent":
                    continue
                if "-u" not in flags and st == "removed-for-user":
                    continue
                if "-d" in flags and st != "disabled":
                    continue
                if "-s" in flags and not info["system"]:
                    continue
                if "-3" in flags and info["system"]:
                    continue
                if filt and filt[0] not in p:
                    continue
                res.append("package:" + p)
            return "\n".join(res)
        if sub == "disable-user":
            p = c[2]
            if p in self.refuse_disable:
                return "Error: java.lang.IllegalArgumentException: Cannot disable a protected package: " + p
            if self._visible(p):
                self.pkgs[p]["state"] = "disabled"
                return "Package %s new state: disabled-user" % p
            return "Error: Unknown package: " + p
        if sub == "enable":
            p = c[2]
            if self._visible(p) and self.pkgs[p]["state"] == "disabled":
                self.pkgs[p]["state"] = "enabled"
            return "Package %s new state: enabled" % p
        if sub == "uninstall":
            p = c[-1]
            if "-k" in c:
                if self._visible(p):
                    self.pkgs[p]["state"] = "removed-for-user"
                    return "Success"
                return "Failure [not installed for 0]"
            if p in self.pkgs and not self.pkgs[p]["system"]:
                del self.pkgs[p]
                if self.home and self.home.startswith(p + "/"):
                    self.home = None
                return "Success"
            return "Failure [DELETE_FAILED_INTERNAL_ERROR]"
        if sub == "install-existing":
            p = c[-1]
            if p in self.pkgs and self.pkgs[p]["state"] == "removed-for-user":
                self.pkgs[p]["state"] = "enabled"
                return "Package %s installed for user: 0" % p
            return "Error"
        if sub == "path":
            p = c[2]
            return "package:/data/app/%s/base.apk" % p if self._visible(p) else ""
        if sub in ("grant", "revoke"):
            self.perms[(c[2], c[3])] = sub == "grant"
            return ""
        return "Unknown pm command"

    def _cmd_package(self, c: List[str]) -> str:
        sub = c[2]
        if sub == "query-activities":
            cat = c[c.index("-c") + 1]
            lines = []
            if cat.endswith("HOME"):
                lines.append("  com.sec.android.app.launcher/com.sec.android.app.launcher.activities.LauncherActivity")
                if LAUNCHER in self.pkgs:
                    lines.append("  %s/.HomeActivity" % LAUNCHER)
                lines.append("  com.android.settings/.FallbackHome")
            else:
                for p, info in sorted(self.pkgs.items()):
                    if info["activity"] and info["state"] == "enabled":
                        lines.append("  %s/%s" % (p, info["activity"]))
            return "%d activities found:\n%s" % (len(lines), "\n".join(lines))
        if sub == "resolve-activity":
            if "android.media.action.STILL_IMAGE_CAMERA" in c:
                return "priority=0\ncom.sec.android.app.camera/.Camera"
            if not self.home:
                return "priority=0 preferredOrder=0\nandroid/com.android.internal.app.ResolverActivity"
            return "priority=0 preferredOrder=0 match=0x108000\n%s" % self.home
        if sub == "set-home-activity":
            self.home = c[3]
            return "Success"
        return ""

    def _appops(self, c: List[str]) -> str:
        sub = c[2]
        if sub == "get":
            mode = self.appops.get((c[3], c[4]))
            return "%s: %s; time=+1d" % (c[4], mode) if mode else "No operations."
        if sub == "set":
            if c[5] == "default":
                self.appops.pop((c[3], c[4]), None)
            else:
                self.appops[(c[3], c[4])] = c[5]
            return ""
        if sub == "query-op":
            return "\n".join(p for (p, op), m in self.appops.items() if op == c[3] and m == c[4])
        return ""

    def _dumpsys(self, c: List[str]) -> str:
        if c == ["package", "packages"]:
            blocks = []
            for p in sorted(self.pkgs):
                lines = ["  Package [%s] (1a2b3c):" % p, "    userId=10%03d" % (len(blocks)), "    User 0: installed=true",
                         "      runtime permissions:"]
                for (pk, perm), g in sorted(self.perms.items()):
                    if pk == p:
                        lines.append("        %s: granted=%s, flags=[ USER_SET ]" % (perm, "true" if g else "false"))
                blocks.append("\n".join(lines))
            return "Packages:\n" + "\n".join(blocks)
        if c[:1] == ["package"] and len(c) == 2:
            p = c[1]
            lines = ["Packages:", "  Package [%s] (1a2b3c):" % p, "    User 0: installed=true", "      runtime permissions:"]
            for (pk, perm), g in sorted(self.perms.items()):
                if pk == p:
                    lines.append("        %s: granted=%s, flags=[ USER_SET ]" % (perm, "true" if g else "false"))
            return "\n".join(lines)
        if c == ["webviewupdate"]:
            return "Current WebView package (name, version): (com.google.android.webview, 120.0)"
        if c == ["device_policy"]:
            return "Current Device Policy Manager state:\n  Enabled Device Admins (User 0, provisioningState: 3):\n    admin=ComponentInfo{com.google.android.gms/com.google.android.gms.mdm.receivers.MdmDeviceAdminReceiver}"
        if c == ["meminfo"]:
            return "Total RAM: 7,654,321K\n Used RAM: 4,123,456K (3,000,000K used pss)"
        return ""

    # -- the launcher's ContentProvider ---------------------------------------
    def _content_call(self, c: List[str]) -> str:
        uri = c[c.index("--uri") + 1]
        if uri != "content://" + AUTH or LAUNCHER not in self.pkgs:
            return "Error while accessing provider:%s\njava.lang.IllegalArgumentException: Unknown authority %s" % (AUTH, AUTH)
        method = c[c.index("--method") + 1]
        arg = c[c.index("--arg") + 1] if "--arg" in c else None

        def b(s: str) -> str:
            return base64.b64encode(s.encode()).decode()

        def h(s: str) -> str:
            return hashlib.sha256(s.encode()).hexdigest()[:12]

        def res(**kw) -> str:
            return "Result: Bundle[{%s}]" % ", ".join("%s=%s" % kv for kv in kw.items())

        cfg = self.provider_config or ""
        if method == "ping":
            return res(ok="true", version="0.1.0", config_hash=h(cfg), active_rules_b64=b("[]"))
        if method == "get_config":
            return res(ok="true", data_b64=b(cfg))
        if method == "list_apps":
            apps = [{"package": p, "activity": i["activity"], "label": i["label"]}
                    for p, i in sorted(self.pkgs.items()) if i["activity"] and i["state"] == "enabled" and p != LAUNCHER]
            return res(ok="true", data_b64=b(json.dumps(apps)))
        if method == "stage_begin":
            self.stage = ""
            return res(ok="true")
        if method == "stage_append":
            self.stage += arg or ""
            return res(ok="true")
        if method == "stage_commit":
            text = base64.b64decode(self.stage).decode()
            try:
                obj = json.loads(text)
                assert obj.get("version") == 1
            except Exception:  # noqa: BLE001
                return res(ok="false", error_b64=b("config is not valid"))
            self.provider_config = text
            return res(ok="true", config_hash=h(text))
        return res(ok="false", error_b64=b("unknown method " + method))
