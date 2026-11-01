"""End-to-end check against a real Android emulator (run in CI by the `emulator` job).

Drives the actual CLI over real adb — the same commands an agent runs — and
asserts the phone's real state after each step. Screenshots of the home screen
go to e2e-artifacts/ so a human can eyeball the launcher.

  python3 tests/e2e_emulator.py [path/to/app-debug.apk]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "e2e-artifacts"
APK = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "launcher/app/build/outputs/apk/debug/app-debug.apk")
LAUNCHER = "io.github.rachitkj.shape"
ENV = dict(os.environ, SHAPE_HOME=tempfile.mkdtemp(prefix="shape-e2e-"))
failures = []


def shape(*args, ok=True):
    p = subprocess.run([sys.executable, "-m", "shape", *args], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=300)
    print("$ shape %s  -> %d" % (" ".join(args), p.returncode))
    out = (p.stdout + p.stderr).strip()
    if out:
        print("  " + out.replace("\n", "\n  ")[:3000])
    if ok and p.returncode != 0:
        raise SystemExit("FAILED: shape %s" % " ".join(args))
    return p


def sh(cmd):
    return subprocess.run(["adb", "shell", cmd], capture_output=True, text=True, timeout=120).stdout.strip()


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        failures.append(what)


def screenshot(name):
    ART.mkdir(exist_ok=True)
    sh("input keyevent KEYCODE_WAKEUP")
    time.sleep(2.5)
    png = subprocess.run(["adb", "exec-out", "screencap", "-p"], capture_output=True, timeout=60).stdout
    (ART / ("%s.png" % name)).write_bytes(png)
    print("  screenshot %s (%d bytes)" % (name, len(png)))


def home():
    sh("input keyevent KEYCODE_HOME")
    time.sleep(1.5)


def swipe_up():
    size = sh("wm size").split()[-1]  # "Physical size: 1080x2400"
    w, h = (int(x) for x in size.split("x"))
    sh("input swipe %d %d %d %d 150" % (w // 2, h * 3 // 4, w // 2, h // 4))


def resumed_activity():
    out = sh("dumpsys activity activities")
    for line in out.splitlines():
        if "mResumedActivity" in line or "topResumedActivity" in line or "ResumedActivity:" in line:
            return line.strip()
    return ""


def home_component():
    lines = sh("cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME").splitlines()
    return lines[-1].strip() if lines else ""


def pull():
    return json.loads(shape("launcher", "pull").stdout)


def main():
    sdk = int(sh("getprop ro.build.version.sdk") or 0)
    print("Android SDK", sdk)
    shape("doctor", ok=False)
    shape("init")
    stock_home = home_component()
    print("stock home:", stock_home)

    # -- scan / privacy produce JSON on real output
    scan = json.loads(shape("scan", "--json").stdout)
    check(scan["counts"]["packages_total"] > 50, "scan sees the phone's packages (%d)" % scan["counts"]["packages_total"])
    json.loads(shape("privacy", "--json").stdout)

    # -- disable + undo a harmless package, verified with raw pm
    candidates = ["com.android.egg", "com.android.dreams.basic", "com.android.dreams.phototable", "com.android.wallpaper.livepicker"]
    enabled = sh("pm list packages -e").split()
    target = next((c for c in candidates if "package:" + c in enabled), None)
    check(target is not None, "found a harmless package to toggle (%s)" % target)
    if target:
        shape("pkg", "disable", target, "--yes")
        check("package:" + target in sh("pm list packages -d").split(), "%s is disabled on the device" % target)
        shape("undo", "--last", "1")
        check("package:" + target not in sh("pm list packages -d").split(), "%s is enabled again after undo" % target)

    # -- protected packages are refused
    shape("pkg", "disable", "com.android.systemui", "--yes", ok=False)
    check("package:com.android.systemui" not in sh("pm list packages -d").split(), "systemui untouched")

    # -- a tweak, read back raw
    anim_before = sh("settings get global animator_duration_scale")
    shape("tweak", "animations", "0.5", "--yes")
    check(sh("settings get global animator_duration_scale") == "0.5", "animator scale is 0.5")

    # -- launcher: install, default home, live config, rollback
    shape("launcher", "install", "--apk", APK)
    st = json.loads(shape("launcher", "status").stdout)
    check(st["is_default_home"], "Shape is the default home")
    check(st["version"] == "0.1.0", "launcher reports its version over content call")
    home()
    screenshot("1-default")

    apps = json.loads(shape("launcher", "apps", "--json").stdout)
    check(any(a["package"] == "com.android.settings" for a in apps), "list_apps returns labelled apps (%d)" % len(apps))

    shape("launcher", "push", str(ROOT / "config/examples/minimal-text.json"), "--yes")
    check(pull().get("name") == "Minimal text", "pushed config is what the phone has")
    home()
    screenshot("2-minimal-text")

    shape("launcher", "push", str(ROOT / "config/examples/focus-workday.json"), "--yes")
    home()
    screenshot("3-focus-workday")
    swipe_up()
    screenshot("4-drawer")
    home()

    shape("launcher", "rollback")
    check(pull().get("name") == "Minimal text", "rollback restored the previous config")

    # -- name-based edits on real app labels
    shape("launcher", "dock", "Settings", "--yes")
    check(pull()["dock"]["apps"] == ["com.android.settings"], "dock edit by app name")
    shape("launcher", "hide", "Settings", "--from", "00:00", "--to", "23:59", "--name", "AllDay", "--yes")
    check("AllDay" in json.loads(shape("launcher", "status").stdout)["active_rules"], "time rule is active on the phone")
    shape("launcher", "unhide", "Settings", "--yes")
    check(pull().get("rules") == [], "unhide removed the rule")
    shape("launcher", "theme", "--icons", "mono", "--yes")
    shape("launcher", "home-apps", "Settings", "Contacts", "--style", "grid", "--yes", ok=False)
    home()
    screenshot("5-mono-icons")

    # -- pause screen: swipe up opens Settings via a gesture, but the pause must come first
    shape("launcher", "gesture", "swipeUp", "Settings", "--yes")
    shape("launcher", "pause", "Settings", "--seconds", "30", "--yes")
    home()
    swipe_up()
    time.sleep(1.5)
    screenshot("6-pause")
    top = resumed_activity()
    check(LAUNCHER in top and "com.android.settings" not in top, "pause screen held Settings back (%s)" % top[-80:])
    sh("input keyevent KEYCODE_BACK")
    time.sleep(1)
    check("com.android.settings" not in resumed_activity(), "back dismissed the pause without opening the app")

    # -- usage access + suggestions (real UsageStatsManager)
    shape("launcher", "usage-access", "--yes")
    sug = shape("suggest", "--json", ok=False)
    check(sug.returncode == 0, "suggest works with usage access")
    if sug.returncode == 0:
        res = json.loads(sug.stdout)
        check(set(res) == {"put_in_reach", "heavy_use", "unused"}, "suggest returns all sections")

    rep = shape("report", "--share")
    check("Device report" in rep.stdout and ENV["SHAPE_HOME"] not in rep.stdout, "share report is generated and anonymous")
    shape("launcher", "history")
    shape("phones")

    # -- full restore: home back to stock, launcher removed, settings back
    shape("restore", "--yes")
    now_home = home_component()
    check(not now_home.startswith(LAUNCHER), "home handed back (%s)" % now_home)
    check(sh("pm path %s" % LAUNCHER) == "", "launcher uninstalled by restore")
    check(sh("settings get global animator_duration_scale") == anim_before, "animator scale restored to %s" % anim_before)
    shape("drift")
    shape("changes", "--all")

    print("\n%d check(s) failed" % len(failures) if failures else "\nall checks passed")
    for f in failures:
        print("  - " + f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
