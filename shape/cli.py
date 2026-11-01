"""`python3 -m shape <command>` — the only way the agent should change a phone."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import LAUNCHER_PACKAGE, __version__
from . import changes as ch
from . import launcher as lz
from . import launcher_config as lc
from . import plans, privacy, probe, tweaks
from .adb import AdbError, Device, find_adb, list_devices, pick_device
from .state import PREFERENCES_TEMPLATE, PhoneState, read_json, write_json


def out(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        print("Not applied. Show this to the phone's owner, and once they agree re-run with --yes.")
        return False
    return input(question + " [y/N] ").strip().lower() in ("y", "yes")


def get_dev(args) -> Device:
    return pick_device(getattr(args, "device", None))


def ensure_init(dev: Device, quiet: bool = False) -> PhoneState:
    ps = PhoneState(dev)
    if not ps.exists:
        if not quiet:
            print("First time with this phone: saving its profile and a full backup first…")
        _init(dev, ps)
    return ps


def _init(dev: Device, ps: PhoneState) -> None:
    prof = probe.profile(dev)
    write_json(ps.path("profile.json"), prof)
    prefs = ps.path("preferences.md")
    if not prefs.exists():
        prefs.write_text(PREFERENCES_TEMPLATE.format(model="%s %s" % (prof["manufacturer"], prof["model"])))
    if not ps.path("keep.json").exists():
        ps.set_keep([])
    snap = probe.take_snapshot(dev, ps, "initial")
    print("  profile      %s" % ps.path("profile.json"))
    print("  preferences  %s" % prefs)
    print("  backup       %s" % snap)


# -- commands ----------------------------------------------------------------

def cmd_doctor(args) -> int:
    ok = True
    print("shape %s, Python %s" % (__version__, sys.version.split()[0]))
    try:
        adb = find_adb()
        print("  adb          %s" % adb)
    except AdbError as e:
        print("  adb          MISSING\n" + str(e))
        return 1
    devs = list_devices()
    if not devs:
        print("  phone        none connected")
        print("\nNext: turn on USB debugging (Settings → About phone → tap 'Build number' 7 times →\n"
              "Developer options → USB debugging), plug in, and tap Allow on the phone.")
        return 1
    for d in devs:
        print("  phone        %s  %s  %s" % (d["serial"], d["state"], d.get("model", "")))
    try:
        dev = get_dev(args)
    except AdbError as e:
        print("\n" + str(e))
        return 1
    prof = probe.profile(dev)
    print("  model        %s %s, Android %s (SDK %s), %s" % (prof["manufacturer"], prof["model"], prof["android"], prof["sdk"], prof["skin"]))
    if prof["sdk"] < 26:
        print("  !            The Shape launcher needs Android 8 or newer. Cleanup still works.")
        ok = False
    ps = PhoneState(dev)
    print("  data         %s%s" % (ps.dir, "" if ps.exists else "  (not initialised — run: shape init)"))
    if lz.is_installed(dev):
        try:
            st = lz.status(dev)
            print("  launcher     installed v%s, default home: %s, active rules: %s" % (
                st["version"], "yes" if st["is_default_home"] else "no", ", ".join(st["active_rules"]) or "none"))
        except lz.LauncherError as e:
            print("  launcher     installed but not answering: %s" % e)
            ok = False
    else:
        print("  launcher     not installed")
    if "xiaomi" in prof["manufacturer"].lower() or "miui" in prof["skin"].lower() or "hyperos" in prof["skin"].lower():
        print("  note         Xiaomi: also turn on 'USB debugging (Security settings)' and 'Install via USB' in Developer options.")
    return 0 if ok else 1


def cmd_devices(args) -> int:
    out(list_devices())
    return 0


def cmd_pair(args) -> int:
    dev = Device(None)
    rc, o, e = dev.adb("pair", args.address, args.code, timeout=60)
    print((o + e).strip())
    return rc


def cmd_connect(args) -> int:
    dev = Device(None)
    rc, o, e = dev.adb("connect", args.address, timeout=60)
    print((o + e).strip())
    return 0 if "connected" in o and "cannot" not in o else 1


def cmd_init(args) -> int:
    dev = get_dev(args)
    ps = PhoneState(dev)
    if ps.exists:
        prof = ps.profile()
        now = probe.profile(dev)
        print("Already set up: %s" % ps.dir)
        if prof.get("build") != now["build"]:
            print("  The phone's software changed since last time (%s → %s). Check: shape drift" % (prof.get("build"), now["build"]))
            prof.update({k: now[k] for k in ("android", "sdk", "skin", "build", "security_patch")})
            write_json(ps.path("profile.json"), prof)
        return 0
    print("Setting up %s" % ps.key)
    _init(dev, ps)
    return 0


def cmd_snapshot(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev)
    print(probe.take_snapshot(dev, ps, args.label or ""))
    return 0


def cmd_scan(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev, quiet=args.json)
    res = plans.scan(dev, ps)
    if args.json:
        out(res)
        return 0
    c = res["counts"]
    print("%d packages: %d on, %d disabled, %d removed for this user" % (c["packages_total"], c["enabled"], c["disabled"], c["removed_for_user"]))
    for tier in plans.TIERS:
        items = [b for b in res["bloat"] if b["tier"] == tier]
        if not items:
            continue
        print("\n%s (%d)" % (tier.upper(), len(items)))
        for b in items:
            flag = "" if b["allowed"] else "   [kept: %s]" % b["blocked_reason"]
            print("  %-48s %s%s" % (b["pkg"], b["name"], flag))
            print("  %-48s   why: %s | loses: %s" % ("", b["why"], b["breaks"]))
    if res["already_off"]:
        print("\nAlready off: %s" % ", ".join(a["pkg"] for a in res["already_off"]))
    if res["unreviewed_system_apps"]:
        print("\nPreinstalled apps no list knows about (ask the owner if they use them):")
        for p in res["unreviewed_system_apps"]:
            print("  " + p)
    return 0


def cmd_privacy(args) -> int:
    dev = get_dev(args)
    res = privacy.audit(dev)
    if args.json:
        out(res)
        return 0
    print("Apps that can see sensitive things (your apps first):")
    for a in res["apps"]:
        if a["system"] and not args.all:
            continue
        print("  %-44s %s" % (a["pkg"], ", ".join(a["access"])))
    if not args.all:
        print("  (system apps hidden; add --all to include them)")
    print("\nSpecial access:")
    for k, v in res["special_access"].items():
        print("  %-26s %s" % (k.replace("_", " "), ", ".join(v) or "-"))
    n = res["network"]
    print("\nPrivate DNS: %s %s" % (n["private_dns_mode"], n["private_dns_host"] or ""))
    return 0


def cmd_plan(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev)
    plan = plans.make_debloat_plan(dev, ps, args.tier, args.include or [], args.exclude or [], args.method)
    path = plans.save_plan(ps, plan)
    print("Plan: %s" % path)
    print("%d change(s), %d kept for safety\n" % (len(plan["actions"]), len(plan["blocked"])))
    for a in plan["actions"]:
        print("  %-8s %-44s %s" % (a["op"], a["pkg"], a["name"]))
        print("  %-8s %-44s   loses: %s" % ("", "", a["breaks"]))
    for b in plan["blocked"]:
        print("  keep     %-44s %s" % (b["pkg"], b["reason"]))
    print("\nEverything here is reversible. Apply with: python3 -m shape apply %s --yes" % path)
    return 0


def cmd_apply(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev)
    plan = plans.load_plan(args.plan)
    n = len(plan["actions"])
    print("%d action(s) in %s" % (n, args.plan))
    if not confirm("Apply them?", args.yes):
        return 2
    summary = plans.apply_plan(dev, ps, plan, "plan:%s" % Path(args.plan).name)
    print("\n%d applied, %d skipped, %d failed, %d blocked. Undo all: python3 -m shape restore" % (
        len(summary["applied"]), len(summary["skipped"]), len(summary["failed"]), len(summary["blocked"])))
    return 0 if not summary["failed"] else 1


def _run_actions(args, actions: List[dict], source: str) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev)
    for why in dict.fromkeys(a.get("why") or str(a) for a in actions):
        print("  %s" % why)
    if not confirm("Apply?", args.yes):
        return 2
    summary = plans.apply_plan(dev, ps, {"actions": actions}, source)
    return 0 if not summary["failed"] else 1


def cmd_tweak(args) -> int:
    dev = get_dev(args)
    try:
        actions = tweaks.actions_for(dev, args.name, args.args)
    except ValueError as e:
        print(e)
        return 2
    return _run_actions(args, actions, "tweak %s %s" % (args.name, " ".join(args.args)))


def cmd_setting(args) -> int:
    return _run_actions(args, [{"op": "setting", "ns": args.namespace, "key": args.key, "value": args.value,
                                "why": "settings %s %s = %s" % (args.namespace, args.key, args.value)}], "setting")


def cmd_perm(args) -> int:
    return _run_actions(args, [{"op": "perm-" + args.action, "pkg": args.package, "perm": args.permission,
                                "why": "%s %s for %s" % (args.action, args.permission, args.package)}], "perm")


def cmd_pkg(args) -> int:
    return _run_actions(args, [{"op": args.action, "pkg": p, "why": "%s %s" % (args.action, p)} for p in args.packages],
                        "pkg %s" % args.action)


def cmd_keep(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev)
    keep = set(ps.keep())
    if args.remove:
        keep -= set(args.packages)
    else:
        keep |= set(args.packages)
    ps.set_keep(sorted(keep))
    print("Never touched on this phone: %s" % (", ".join(sorted(keep)) or "(nothing yet)"))
    return 0


def cmd_changes(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev, quiet=True)
    log = ch.ChangeLog(ps)
    items = log.changes if args.all else log.applied()
    if args.json:
        out([c.__dict__ for c in items])
        return 0
    if not items:
        print("No changes yet.")
    for c in items:
        print("#%-4d %-8s %-18s %-48s %s → %s  %s" % (c.id, c.status, c.kind, c.target[:48], c.before[:16], c.after[:16], c.note[:40]))
    return 0


def _undo(dev: Device, ps: PhoneState, log: ch.ChangeLog, c: ch.Change) -> bool:
    res = ch.undo_change(dev, log, c, lz.undo_config_change(dev, ps))
    print("  %s #%d %s %s%s" % ("undone " if res.status == "applied" else res.status.upper().ljust(7),
                                c.id, c.kind, c.target, (" — " + res.message) if res.message else ""))
    return res.status == "applied"


def cmd_undo(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev, quiet=True)
    log = ch.ChangeLog(ps)
    if args.last:
        targets = sorted(log.applied(), key=lambda c: c.id)[-args.last:]
    else:
        targets = [log.get(i) for i in args.ids]
        if None in targets:
            print("Unknown change id. See: shape changes")
            return 2
    ok = True
    for c in sorted(targets, key=lambda c: c.id, reverse=True):
        ok &= _undo(dev, ps, log, c)
    plans.write_restore(ps, log)
    return 0 if ok else 1


def cmd_restore(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev, quiet=True)
    log = ch.ChangeLog(ps)
    path = plans.write_restore(ps, log)
    if args.script_only:
        print(path)
        return 0
    todo = sorted(log.applied(), key=lambda c: c.id, reverse=True)
    if not todo:
        print("Nothing to restore — no active changes.")
        return 0
    print("This undoes all %d active change(s), newest first." % len(todo))
    if not confirm("Restore the phone?", args.yes):
        return 2
    ok = True
    for c in todo:
        if c.kind == "launcher.config":
            c.status = "undone"
            log.save()
            continue
        ok &= _undo(dev, ps, log, c)
    plans.write_restore(ps, log)
    print("Done." if ok else "Some changes could not be undone — see above. Fallback script: %s" % path)
    return 0 if ok else 1


def cmd_drift(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev, quiet=True)
    items = ch.drift(dev, ch.ChangeLog(ps))
    if args.json:
        out(items)
        return 0
    if not items:
        print("Everything shape changed is still in place.")
        return 0
    print("%d change(s) were undone by the phone (often after a system update):" % len(items))
    for d in items:
        print("  #%-4d %-16s %-44s now %s, should be %s" % (d["id"], d["kind"], d["target"], d["now"], d["expected"]))
    print("Re-apply with: python3 -m shape reapply --yes")
    return 0


def cmd_reapply(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev, quiet=True)
    items = ch.drift(dev, ch.ChangeLog(ps))
    if not items:
        print("Nothing drifted.")
        return 0
    if not confirm("Re-apply %d change(s)?" % len(items), args.yes):
        return 2
    bad = 0
    for d in items:
        dev.sh(d["redo"])
        now = ch.read_state(dev, d["kind"], d["target"], dev.user)
        good = ch._matches(d["kind"], now, d["expected"])
        bad += 0 if good else 1
        print("  %s #%d %s" % ("done  " if good else "FAILED", d["id"], d["target"]))
    return 0 if not bad else 1


def cmd_report(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev, quiet=True)
    first = ps.first_snapshot()
    before = read_json(first / "packages.json", {}) if first else {}
    now = probe.package_states(dev)
    log = ch.ChangeLog(ps)

    def count(states, s):
        return sum(1 for v in states.values() if v["state"] == s)

    rep = {
        "device": ps.profile(),
        "packages_on": {"before": count(before, "enabled"), "now": count(now, "enabled")},
        "changes_active": len(log.applied()),
        "changes_by_kind": {},
        "ram_used_kb": {"before": (read_json(first / "meta.json", {}) or {}).get("used_ram_kb") if first else None,
                        "now": probe.used_ram_kb(dev)},
        "launcher": None,
    }
    for c in log.applied():
        rep["changes_by_kind"][c.kind] = rep["changes_by_kind"].get(c.kind, 0) + 1
    if lz.is_installed(dev):
        try:
            rep["launcher"] = lz.status(dev)
        except lz.LauncherError as e:
            rep["launcher"] = {"error": str(e)}
    if args.json:
        out(rep)
        return 0
    p = rep["device"]
    print("%s %s — %s" % (p.get("manufacturer"), p.get("model"), p.get("skin")))
    print("Apps running/enabled: %s → %s" % (rep["packages_on"]["before"], rep["packages_on"]["now"]))
    r = rep["ram_used_kb"]
    if r["before"] and r["now"]:
        print("RAM in use: %.1f GB → %.1f GB (a rough snapshot; it varies minute to minute)" % (r["before"] / 1e6, r["now"] / 1e6))
    print("Active changes: %d  %s" % (rep["changes_active"], ", ".join("%s×%d" % kv for kv in rep["changes_by_kind"].items())))
    if rep["launcher"]:
        print("Launcher: %s" % rep["launcher"])
    print("Undo everything: python3 -m shape restore   (or sh %s)" % ps.path("restore.sh"))
    return 0


def cmd_prefs(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev, quiet=True)
    p = ps.path("preferences.md")
    if args.path:
        print(p)
    else:
        print("# %s\n" % p)
        print(p.read_text())
        print("keep.json: %s" % (", ".join(ps.keep()) or "-"))
    return 0


# -- launcher ----------------------------------------------------------------

def _load_cfg(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except json.JSONDecodeError as e:
        raise SystemExit("%s is not valid JSON: %s" % (path, e))


def cmd_l_install(args) -> int:
    dev = get_dev(args)
    if dev.sdk < 26:
        print("The Shape launcher needs Android 8 or newer.")
        return 2
    ps = ensure_init(dev)
    lz.install(dev, ps, args.apk, make_default=not args.no_default)
    plans.write_restore(ps)
    return 0


def cmd_l_default(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev)
    r = lz.set_default(dev, ps)
    plans.write_restore(ps)
    return 0 if r and r.status in ("applied", "skipped") else 1


def cmd_l_status(args) -> int:
    dev = get_dev(args)
    out(lz.status(dev))
    return 0


def cmd_l_apps(args) -> int:
    dev = get_dev(args)
    try:
        apps = lz.list_apps(dev)
    except lz.LauncherError as e:
        print("%s\nFalling back to package names only:" % e)
        for c in probe.launchable_components(dev):
            print("  " + c)
        return 1
    if args.json:
        out(apps)
    else:
        for a in apps:
            print("  %-32s %s" % (a["label"][:32], a["package"]))
    return 0


def cmd_l_validate(args) -> int:
    cfg = _load_cfg(args.file)
    installed = None
    if args.device_check:
        installed = {a["package"] for a in lz.list_apps(get_dev(args))}
    r = lc.validate(cfg, installed)
    for e in r.errors:
        print("error:   " + e)
    for w in r.warnings:
        print("warning: " + w)
    if r.ok:
        print("OK — %s" % args.file)
        for line in lc.summarize(cfg):
            print("  " + line)
    return 0 if r.ok else 1


def cmd_l_preview(args) -> int:
    cfg = _load_cfg(args.file)
    day, minute = lc.parse_at(args.at)
    merged, hidden, active = lc.effective(cfg, day, minute)
    print("At %s %02d:%02d — active rules: %s" % (lc.DAYS[day - 1], minute // 60, minute % 60, ", ".join(active) or "none"))
    if hidden:
        print("Hidden by rules: " + ", ".join(hidden))
    for line in lc.summarize(merged):
        print("  " + line)
    return 0


def cmd_l_push(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev)
    cfg = _load_cfg(args.file)
    labels = {}
    try:
        labels = {a["package"]: a["label"] for a in lz.list_apps(dev)}
    except lz.LauncherError as e:
        print(e)
        return 1
    r = lc.validate(cfg, set(labels))
    for w in r.warnings:
        print("warning: " + w)
    if not r.ok:
        for e in r.errors:
            print("error:   " + e)
        return 1
    print("New home screen:")
    for line in lc.summarize(cfg, labels):
        print("  " + line)
    if not confirm("Push it to the phone?", args.yes):
        return 2
    h, c = lz.push(dev, ps, cfg)
    print("Pushed (#%d, config %s). Undo: python3 -m shape launcher rollback" % (c.id, h))
    return 0


def cmd_l_pull(args) -> int:
    dev = get_dev(args)
    cfg = lz.get_config(dev)
    text = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text)
        print(args.out)
    else:
        print(text)
    return 0


def cmd_l_history(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev, quiet=True)
    hist = lz.history(ps)
    if not hist:
        print("No configs pushed yet.")
    for i, (stem, cfg) in enumerate(hist):
        back = len(hist) - 1 - i
        print("  %-28s %-24s %s" % (stem, cfg.get("name", ""), "(current)" if back == 0 else "rollback -%d" % back))
    return 0


def cmd_l_rollback(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev, quiet=True)
    stem, h = lz.rollback(dev, ps, args.to)
    print("Home screen is back to %s (%s)." % (stem, h))
    return 0


def cmd_l_uninstall(args) -> int:
    dev = get_dev(args)
    ps = ensure_init(dev, quiet=True)
    if not confirm("Give the home screen back to the previous launcher and remove Shape?", args.yes):
        return 2
    lz.uninstall(dev, ps)
    plans.write_restore(ps)
    return 0


# -- parser ------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shape", description="Shape an Android phone with an AI agent — every change reversible.")
    p.add_argument("--device", "-d", help="adb serial (when several phones are connected)")
    p.add_argument("--version", action="version", version="shape " + __version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    add("doctor", cmd_doctor, "check adb, the phone and the launcher")
    add("devices", cmd_devices, "list connected phones")
    sp = add("pair", cmd_pair, "pair over Wireless debugging (Android 11+)")
    sp.add_argument("address", help="ip:port shown under 'Pair device with pairing code'")
    sp.add_argument("code")
    sp = add("connect", cmd_connect, "connect over Wireless debugging")
    sp.add_argument("address", help="ip:port shown on the Wireless debugging screen")
    add("init", cmd_init, "save profile + full backup, create preferences.md")
    sp = add("snapshot", cmd_snapshot, "take another full backup")
    sp.add_argument("--label", default="")
    sp = add("scan", cmd_scan, "find bloat and unknown preinstalled apps")
    sp.add_argument("--json", action="store_true")
    sp = add("privacy", cmd_privacy, "which apps can see location, camera, mic, contacts…")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--all", action="store_true", help="include system apps")
    sp = add("plan", cmd_plan, "write a reviewable debloat plan")
    sp.add_argument("--tier", default="recommended", choices=list(plans.TIER_SETS))
    sp.add_argument("--include", nargs="*", help="also these packages")
    sp.add_argument("--exclude", nargs="*", help="never these packages")
    sp.add_argument("--method", default="disable", choices=["disable", "remove"])
    sp = add("apply", cmd_apply, "apply a plan file")
    sp.add_argument("plan")
    sp.add_argument("--yes", action="store_true")
    sp = add("tweak", cmd_tweak, "named tweaks: " + ", ".join(tweaks.TWEAKS))
    sp.add_argument("name", choices=list(tweaks.TWEAKS))
    sp.add_argument("args", nargs="*")
    sp.add_argument("--yes", action="store_true")
    sp = add("setting", cmd_setting, "change any Android setting (logged, reversible)")
    sp.add_argument("namespace", choices=["global", "secure", "system"])
    sp.add_argument("key")
    sp.add_argument("value", help="'null' deletes the setting")
    sp.add_argument("--yes", action="store_true")
    sp = add("perm", cmd_perm, "grant or revoke an app permission")
    sp.add_argument("action", choices=["grant", "revoke"])
    sp.add_argument("package")
    sp.add_argument("permission")
    sp.add_argument("--yes", action="store_true")
    sp = add("pkg", cmd_pkg, "disable / remove / enable specific packages")
    sp.add_argument("action", choices=["disable", "remove", "enable"])
    sp.add_argument("packages", nargs="+")
    sp.add_argument("--yes", action="store_true")
    sp = add("keep", cmd_keep, "packages shape must never touch on this phone")
    sp.add_argument("packages", nargs="+")
    sp.add_argument("--remove", action="store_true")
    sp = add("changes", cmd_changes, "list changes")
    sp.add_argument("--all", action="store_true", help="include undone and failed")
    sp.add_argument("--json", action="store_true")
    sp = add("undo", cmd_undo, "undo specific changes")
    sp.add_argument("ids", nargs="*", type=int)
    sp.add_argument("--last", type=int)
    sp = add("restore", cmd_restore, "undo every change")
    sp.add_argument("--yes", action="store_true")
    sp.add_argument("--script-only", action="store_true", help="just (re)write restore.sh")
    sp = add("drift", cmd_drift, "find changes the phone has reverted (e.g. after an update)")
    sp.add_argument("--json", action="store_true")
    sp = add("reapply", cmd_reapply, "re-apply drifted changes")
    sp.add_argument("--yes", action="store_true")
    sp = add("report", cmd_report, "before/after summary")
    sp.add_argument("--json", action="store_true")
    sp = add("prefs", cmd_prefs, "show the owner's preferences file")
    sp.add_argument("--path", action="store_true")

    lp = sub.add_parser("launcher", help="the Shape home screen").add_subparsers(dest="lcmd", required=True)

    def ladd(name, fn, help_):
        sp = lp.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    sp = ladd("install", cmd_l_install, "install the launcher and make it the home screen")
    sp.add_argument("--apk")
    sp.add_argument("--no-default", action="store_true")
    ladd("default", cmd_l_default, "make Shape the home screen")
    ladd("status", cmd_l_status, "launcher version, config, active rules")
    sp = ladd("apps", cmd_l_apps, "installed apps with their names")
    sp.add_argument("--json", action="store_true")
    sp = ladd("validate", cmd_l_validate, "check a config file")
    sp.add_argument("file")
    sp.add_argument("--device-check", action="store_true", help="also check apps exist on the phone")
    sp = ladd("preview", cmd_l_preview, "what a config looks like at a given time")
    sp.add_argument("file")
    sp.add_argument("--at", help="e.g. 'fri 22:30' (default: now)")
    sp = ladd("push", cmd_l_push, "send a config to the phone (live, no reinstall)")
    sp.add_argument("file")
    sp.add_argument("--yes", action="store_true")
    sp = ladd("pull", cmd_l_pull, "read the config from the phone")
    sp.add_argument("--out")
    ladd("history", cmd_l_history, "every config pushed to this phone")
    sp = ladd("rollback", cmd_l_rollback, "go back to an earlier config")
    sp.add_argument("to", nargs="?", help="history name/prefix, or -N (default -1)")
    sp = ladd("uninstall", cmd_l_uninstall, "restore the previous launcher and remove Shape")
    sp.add_argument("--yes", action="store_true")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args) or 0
    except (AdbError, lz.LauncherError, ValueError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
