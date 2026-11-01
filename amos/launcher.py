"""Install and drive the amos launcher on the phone.

The launcher exposes a ContentProvider that only answers callers running as
the adb shell user (uid 2000) or root. We talk to it with `content call`:

    content call --uri content://<pkg>.control --method <m> [--arg <a>]

Results come back as `Result: Bundle[{ok=true, data_b64=...}]`. Free text is
always base64 so the Bundle string is trivially parseable.
"""

from __future__ import annotations

import base64
import glob
import hashlib
import json
import os
import re
import tempfile
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import LAUNCHER_AUTHORITY, LAUNCHER_HOME_ACTIVITY, LAUNCHER_PACKAGE, LAUNCHER_RELEASE_URL
from . import changes as ch
from .adb import AdbError, Device, quote
from .launcher_config import validate
from .state import REPO_ROOT, PhoneState, now_ts, read_json, write_json

CHUNK = 12000  # base64 chars per `content call` — well under adb's command length limits


class LauncherError(RuntimeError):
    pass


# -- provider calls ----------------------------------------------------------

def _parse_bundle(out: str) -> Dict[str, str]:
    m = re.search(r"Result: Bundle\[\{(.*)\}\]", out, re.S)
    if not m:
        if "Unknown authority" in out or "Could not find provider" in out or "Unknown URL" in out:
            raise LauncherError("The amos launcher is not installed (or not set up yet). Run: python3 -m amos launcher install")
        if "SecurityException" in out:
            raise LauncherError("The launcher refused the call: " + out.strip().splitlines()[-1])
        raise LauncherError("Unexpected reply from launcher: " + (out.strip()[:300] or "(empty)"))
    fields = {}
    for kv in re.finditer(r"(\w+)=([^,}]*)", m.group(1)):
        fields[kv.group(1)] = kv.group(2).strip()
    return fields


def _b64d(s: str) -> str:
    return base64.b64decode(s.encode()).decode("utf-8") if s else ""


def call(dev: Device, method: str, arg: Optional[str] = None) -> Dict[str, str]:
    argv = ["content", "call", "--uri", "content://" + LAUNCHER_AUTHORITY, "--method", method]
    if arg is not None:
        argv += ["--arg", arg]
    res = _parse_bundle(dev.shell(*argv, timeout=60))
    if res.get("ok") != "true":
        raise LauncherError(_b64d(res.get("error_b64", "")) or "launcher call %s failed" % method)
    return res


def status(dev: Device) -> dict:
    r = call(dev, "ping")
    return {
        "version": r.get("version", "?"),
        "config_hash": r.get("config_hash", ""),
        "active_rules": json.loads(_b64d(r.get("active_rules_b64", "")) or "[]"),
        "is_default_home": _is_default_home(dev),
    }


def _is_default_home(dev: Device) -> bool:
    from .probe import current_home
    home = current_home(dev)
    return bool(home) and home.split("/")[0] == LAUNCHER_PACKAGE


def is_installed(dev: Device) -> bool:
    return bool(dev.shell("pm", "path", LAUNCHER_PACKAGE).strip())


def list_apps(dev: Device) -> List[dict]:
    r = call(dev, "list_apps")
    return json.loads(_b64d(r.get("data_b64", "")) or "[]")


def get_config(dev: Device) -> dict:
    r = call(dev, "get_config")
    return json.loads(_b64d(r.get("data_b64", "")))


def config_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _canonical(cfg: dict) -> str:
    return json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"


def send_config(dev: Device, cfg: dict) -> str:
    text = _canonical(cfg)
    b64 = base64.b64encode(text.encode("utf-8")).decode()
    call(dev, "stage_begin")
    for i in range(0, len(b64), CHUNK):
        call(dev, "stage_append", b64[i:i + CHUNK])
    want = config_hash(text)
    r = call(dev, "stage_commit", want)
    got = r.get("config_hash", "")
    if got != want:
        raise LauncherError("launcher stored config %s, expected %s" % (got, want))
    return want


# -- history -----------------------------------------------------------------

def history_dir(ps: PhoneState) -> Path:
    return ps.path("launcher", "history")


def history(ps: PhoneState) -> List[Tuple[str, dict]]:
    d = history_dir(ps)
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        out.append((f.stem, read_json(f, {})))
    return out


def push(dev: Device, ps: PhoneState, cfg: dict, source: str = "launcher push") -> Tuple[str, ch.Change]:
    installed = {a["package"] for a in list_apps(dev)}
    report = validate(cfg, installed)
    if not report.ok:
        raise LauncherError("config is invalid:\n  " + "\n  ".join(report.errors))
    try:
        before = get_config(dev)
    except LauncherError:
        before = None
    log = ch.ChangeLog(ps)
    # history: keep what was there before the first amos push, then every pushed version
    hd = history_dir(ps)
    if before is not None and not history(ps):
        write_json(hd / ("%s-before.json" % now_ts()), before)
    h = send_config(dev, cfg)
    stamp = "%s-%s" % (now_ts(), h)
    write_json(hd / ("%s.json" % stamp), cfg)
    write_json(ps.path("launcher", "current.json"), cfg)
    prev_file = ""
    hist = history(ps)
    if len(hist) >= 2:
        prev_file = hist[-2][0]
    op = ch.Op("launcher.config", h, config_hash(_canonical(before)) if before else "none", h,
               "launcher push %s" % stamp, "launcher rollback %s" % prev_file if prev_file else "", cfg.get("name", ""))
    c = log.add(op, source, "applied", data={"history": stamp, "previous": prev_file})
    return h, c


def rollback(dev: Device, ps: PhoneState, to: Optional[str] = None) -> Tuple[str, str]:
    """Push an earlier config. `to` is a history stem, a prefix of one, or -N (N pushes back)."""
    hist = history(ps)
    if len(hist) < 2 and not to:
        raise LauncherError("nothing to roll back to yet")
    if to is None or to == "-1":
        target = hist[-2]
    elif re.match(r"^-\d+$", to):
        n = int(to[1:])
        if n >= len(hist):
            raise LauncherError("only %d versions in history" % len(hist))
        target = hist[-1 - n]
    else:
        matches = [hh for hh in hist if hh[0].startswith(to)]
        if not matches:
            raise LauncherError("no history entry starts with %r (see: amos launcher history)" % to)
        target = matches[-1]
    h, _ = push(dev, ps, target[1], source="launcher rollback %s" % target[0])
    return target[0], h


def undo_config_change(dev: Device, ps: PhoneState):
    def _undo(c: ch.Change):
        prev = c.data.get("previous")
        if not prev:
            return False, "no earlier config recorded for change %d" % c.id
        try:
            rollback(dev, ps, prev)
        except LauncherError as e:
            return False, str(e)
        return True, "rolled back to %s" % prev
    return _undo


# -- install -----------------------------------------------------------------

def find_local_apk() -> Optional[str]:
    patterns = [
        REPO_ROOT / "launcher/app/build/outputs/apk/release/*.apk",
        REPO_ROOT / "launcher/app/build/outputs/apk/debug/*.apk",
        REPO_ROOT / "dist/*.apk",
    ]
    for p in patterns:
        hits = sorted(glob.glob(str(p)), key=os.path.getmtime, reverse=True)
        hits = [h for h in hits if "unsigned" not in h]
        if hits:
            return hits[0]
    return None


def download_release_apk() -> str:
    dest = Path(tempfile.gettempdir()) / "amos-launcher.apk"
    try:
        urllib.request.urlretrieve(LAUNCHER_RELEASE_URL, str(dest))
    except Exception as e:  # noqa: BLE001 — surface any network error plainly
        raise LauncherError(
            "Couldn't download the launcher from %s (%s).\n"
            "Build it instead: cd launcher && ./gradlew assembleDebug  (needs JDK 17+ and the Android SDK),\n"
            "or pass --apk /path/to/amos-launcher.apk" % (LAUNCHER_RELEASE_URL, e)
        )
    return str(dest)


def install(dev: Device, ps: PhoneState, apk: Optional[str], make_default: bool = True, echo=print) -> List[ch.Result]:
    log = ch.ChangeLog(ps)
    results = []
    apk = apk or find_local_apk()
    if not apk:
        echo("No local build found; downloading the latest release…")
        apk = download_release_apk()
    if not os.path.isfile(apk):
        raise LauncherError("APK not found: %s" % apk)
    already = is_installed(dev)

    def host_install():
        rc, out, err = dev.adb("install", "-r", apk, timeout=300)
        return rc == 0 and "Success" in out, (out + err).strip()

    op = ch.Op("app.install", LAUNCHER_PACKAGE, "installed" if already else "absent", "installed",
               "adb install -r amos-launcher.apk", quote(["pm", "uninstall", LAUNCHER_PACKAGE]) if not already else "",
               "amos launcher", host_do=host_install)
    if already:
        # reinstall/upgrade: run it, but don't log a second install change
        ok, msg = host_install()
        if not ok:
            raise LauncherError("install failed: " + msg)
        echo("  updated  amos launcher")
    else:
        r = ch.execute(dev, log, op, "launcher install")
        if r.status != "applied":
            hint = ""
            if "INSTALL_FAILED_USER_RESTRICTED" in r.message or "USER_RESTRICTED" in r.message:
                hint = "\n  Xiaomi/POCO: turn on 'Install via USB' in Developer options (needs a Mi account), then retry."
            raise LauncherError("install failed: %s%s" % (r.message, hint))
        results.append(r)
        echo("  done     installed amos launcher (#%d)" % r.change.id)
    if make_default:
        r = set_default(dev, ps, echo)
        if r:
            results.append(r)
    return results


def set_default(dev: Device, ps: PhoneState, echo=print) -> Optional[ch.Result]:
    log = ch.ChangeLog(ps)
    op = ch.op_home(dev, LAUNCHER_HOME_ACTIVITY, "make amos the home screen")
    r = ch.execute(dev, log, op, "launcher default")
    if r.status == "applied":
        echo("  done     amos is now the home screen (#%d). Previous: %s" % (r.change.id, op.before))
        return r
    if r.status == "skipped":
        echo("  skip     amos is already the home screen")
        return r
    echo("  This phone didn't let adb switch the home app. Opening the picker on the phone —\n"
         "  tap 'amos' there. (Settings → Apps → Default apps → Home app)")
    dev.shell("am", "start", "-a", "android.settings.HOME_SETTINGS")
    return r


def uninstall(dev: Device, ps: PhoneState, echo=print) -> None:
    """Hand the home screen back to the previous launcher, then remove amos."""
    log = ch.ChangeLog(ps)
    homes = [c for c in log.applied() if c.kind == "home" and c.target.split("/")[0] == LAUNCHER_PACKAGE]
    for c in reversed(homes):
        res = ch.undo_change(dev, log, c)
        echo("  %s home screen → %s" % ("done    " if res.status == "applied" else "FAILED  ", c.before))
    for c in reversed([c for c in log.applied() if c.kind == "launcher.config"]):
        c.status = "undone"
    log.save()
    inst = [c for c in log.applied() if c.kind == "app.install" and c.target == LAUNCHER_PACKAGE]
    for c in reversed(inst):
        res = ch.undo_change(dev, log, c)
        echo("  %s uninstalled amos launcher" % ("done    " if res.status == "applied" else "FAILED  "))
    if not inst and is_installed(dev):
        dev.shell("pm", "uninstall", LAUNCHER_PACKAGE)
        echo("  done     uninstalled amos launcher")
