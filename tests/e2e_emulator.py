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


def main():
    shape("doctor", ok=False)
    shape("init")
    stock_home = sh("cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME").splitlines()[-1]
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
    pulled = json.loads(shape("launcher", "pull").stdout)
    check(pulled.get("name") == "Minimal text", "pushed config is what the phone has")
    home()
    screenshot("2-minimal-text")

    shape("launcher", "push", str(ROOT / "config/examples/focus-workday.json"), "--yes")
    home()
    screenshot("3-focus-workday")
    size = sh("wm size").split()[-1]  # "Physical size: 1080x2400"
    w, h = (int(x) for x in size.split("x"))
    sh("input swipe %d %d %d %d 150" % (w // 2, h * 3 // 4, w // 2, h // 4))  # swipe up -> drawer
    screenshot("4-drawer")
    home()

    shape("launcher", "rollback")
    check(json.loads(shape("launcher", "pull").stdout).get("name") == "Minimal text", "rollback restored the previous config")
    shape("launcher", "history")

    # -- full restore: home back to stock, launcher removed, settings back
    shape("restore", "--yes")
    now_home = sh("cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME").splitlines()[-1]
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
