"""Scan for bloat, write reviewable plans, and apply them.

A plan is a JSON file with a list of actions. `shape plan` writes one for
debloating; the agent may also write or edit plans by hand (e.g. drop a line
the owner wants to keep). `shape apply` runs any plan through the safety guard
and the change log.

Action shapes:
  {"op": "disable",      "pkg": "..."}
  {"op": "remove",       "pkg": "..."}          # uninstall for this user, keeps APK
  {"op": "enable",       "pkg": "..."}
  {"op": "setting",      "ns": "global|secure|system", "key": "...", "value": "..."}
  {"op": "perm-revoke",  "pkg": "...", "perm": "android.permission.X"}
  {"op": "perm-grant",   "pkg": "...", "perm": "android.permission.X"}
  {"op": "appop",        "pkg": "...", "appop": "RUN_ANY_IN_BACKGROUND", "mode": "ignore"}
  {"op": "standby",      "pkg": "...", "bucket": "restricted"}
  {"op": "nightmode",    "mode": "yes|no|auto"}
Every action may carry "why" / "breaks" / "name" for the human reading it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from . import changes as ch
from . import probe
from .adb import Device
from .safety import Guard
from .state import REPO_ROOT, PhoneState, now_iso, now_ts, read_json, write_json

TIERS = ("safe", "recommended", "optional")
TIER_SETS = {"safe": {"safe"}, "recommended": {"safe", "recommended"}, "all": set(TIERS)}


def load_bloat() -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for f in sorted((REPO_ROOT / "data" / "bloat").glob("*.json")):
        for e in json.loads(f.read_text()):
            e = dict(e)
            e["list"] = f.stem
            out.setdefault(e["pkg"], e)
    return out


def scan(dev: Device, ps: PhoneState) -> dict:
    states = probe.package_states(dev)
    bloat = load_bloat()
    guard = Guard(dev, ps.keep())
    found, already = [], []
    for pkg, e in sorted(bloat.items(), key=lambda kv: (TIERS.index(kv[1]["tier"]), kv[0])):
        st = states.get(pkg)
        if not st:
            continue
        if st["state"] != "enabled":
            already.append({"pkg": pkg, "name": e["name"], "state": st["state"]})
            continue
        ok, reason = guard.check(pkg)
        found.append({**{k: e[k] for k in ("pkg", "name", "tier", "why", "breaks") if k in e},
                      "list": e["list"], "allowed": ok, "blocked_reason": reason})
    # system apps with an icon that no list knows about: ask the owner
    visible = {c.split("/")[0] for c in probe.launchable_components(dev)}
    unknown = []
    for pkg in sorted(visible):
        st = states.get(pkg)
        if not st or not st["system"] or pkg in bloat or st["state"] != "enabled":
            continue
        ok, reason = guard.check(pkg)
        if ok:
            unknown.append(pkg)
    counts = {
        "packages_total": len(states),
        "enabled": sum(1 for s in states.values() if s["state"] == "enabled"),
        "disabled": sum(1 for s in states.values() if s["state"] == "disabled"),
        "removed_for_user": sum(1 for s in states.values() if s["state"] == "removed-for-user"),
    }
    return {"counts": counts, "bloat": found, "already_off": already, "unreviewed_system_apps": unknown}


def make_debloat_plan(dev: Device, ps: PhoneState, tier: str, include: List[str], exclude: List[str],
                      method: str = "disable") -> dict:
    if tier not in TIER_SETS:
        raise ValueError("tier must be one of: " + ", ".join(TIER_SETS))
    result = scan(dev, ps)
    bloat = load_bloat()
    wanted = TIER_SETS[tier]
    actions, blocked = [], []
    chosen = []
    for e in result["bloat"]:
        if e["pkg"] in exclude:
            continue
        if e["tier"] in wanted or e["pkg"] in include:
            chosen.append(e)
    known = {e["pkg"] for e in result["bloat"]}
    guard = Guard(dev, ps.keep())
    states = probe.package_states(dev)
    for pkg in include:
        if pkg in known or pkg in exclude:
            continue
        st = states.get(pkg)
        if not st or st["state"] != "enabled":
            blocked.append({"pkg": pkg, "reason": "not installed or already off"})
            continue
        ok, reason = guard.check(pkg)
        e = bloat.get(pkg, {"pkg": pkg, "name": pkg, "tier": "custom", "why": "requested by the owner", "breaks": "unknown — explain to the owner"})
        chosen.append({**e, "allowed": ok, "blocked_reason": reason})
    for e in chosen:
        if not e.get("allowed", True):
            blocked.append({"pkg": e["pkg"], "name": e.get("name", ""), "reason": e["blocked_reason"]})
            continue
        actions.append({"op": method, "pkg": e["pkg"], "name": e.get("name", ""), "tier": e.get("tier", ""),
                        "why": e.get("why", ""), "breaks": e.get("breaks", "")})
    return {"kind": "debloat", "created": now_iso(), "device": ps.key, "tier": tier,
            "actions": actions, "blocked": blocked,
            "how_to_review": "Remove any action the owner wants to keep, then: python3 -m shape apply <this file> --yes"}


def save_plan(ps: PhoneState, plan: dict) -> str:
    path = ps.path("plans", "%s-%s.json" % (now_ts(), plan.get("kind", "plan")))
    write_json(path, plan)
    return str(path)


def build_op(dev: Device, a: dict) -> ch.Op:
    op, note = a["op"], a.get("why", "")
    if op == "disable":
        return ch.op_package_disable(dev, a["pkg"], note)
    if op == "remove":
        return ch.op_package_remove(dev, a["pkg"], note)
    if op == "enable":
        return ch.op_package_enable(dev, a["pkg"], note)
    if op == "setting":
        return ch.op_setting(dev, a["ns"], a["key"], a["value"], note)
    if op in ("perm-revoke", "perm-grant"):
        return ch.op_permission(dev, a["pkg"], a["perm"], op == "perm-grant", note)
    if op == "appop":
        return ch.op_appop(dev, a["pkg"], a["appop"], a["mode"], note)
    if op == "standby":
        return ch.op_standby(dev, a["pkg"], a["bucket"], note)
    if op == "nightmode":
        return ch.op_night_mode(dev, a["mode"], note)
    raise ValueError("unknown action op: %r" % op)


def apply_plan(dev: Device, ps: PhoneState, plan: dict, source: str, echo=print) -> dict:
    log = ch.ChangeLog(ps)
    guard = Guard(dev, ps.keep())
    summary = {"applied": [], "skipped": [], "failed": [], "blocked": []}
    for a in plan.get("actions", []):
        label = a.get("name") or a.get("pkg") or a.get("key") or a["op"]
        if a["op"] in ("disable", "remove"):
            ok, reason = guard.check(a["pkg"])
            if not ok:
                summary["blocked"].append({"action": a, "reason": reason})
                echo("  BLOCKED  %s — %s" % (label, reason))
                continue
        try:
            op = build_op(dev, a)
        except (ValueError, KeyError) as e:
            summary["failed"].append({"action": a, "error": str(e)})
            echo("  FAILED   %s — %s" % (label, e))
            continue
        if op.before == "absent":
            summary["skipped"].append({"action": a, "reason": "not installed"})
            echo("  skip     %s — not installed" % label)
            continue
        res = ch.execute(dev, log, op, source)
        if res.status == "failed" and a["op"] == "disable":
            # Some OEMs refuse disable-user for certain packages; per-user uninstall is equally reversible.
            res2 = ch.execute(dev, log, ch.op_package_remove(dev, a["pkg"], op.note), source)
            if res2.status == "applied":
                res = res2
                echo("  (disable refused, removed for this user instead)")
        if res.status == "applied":
            summary["applied"].append({"action": a, "change": res.change.id})
            echo("  done     %s  (#%d, undo: shape undo %d)" % (label, res.change.id, res.change.id))
        elif res.status == "skipped":
            summary["skipped"].append({"action": a, "reason": res.message})
            echo("  skip     %s — %s" % (label, res.message))
        else:
            summary["failed"].append({"action": a, "error": res.message})
            echo("  FAILED   %s — %s" % (label, res.message))
    write_restore(ps, log)
    return summary


def write_restore(ps: PhoneState, log: Optional[ch.ChangeLog] = None) -> str:
    log = log or ch.ChangeLog(ps)
    path = ps.path("restore.sh")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ch.restore_script(log))
    try:
        path.chmod(0o755)
    except OSError:
        pass
    return str(path)


def load_plan(path: str) -> dict:
    plan = read_json(Path(path))
    if not isinstance(plan, dict) or not isinstance(plan.get("actions"), list):
        raise ValueError("%s is not a plan (needs an 'actions' list)" % path)
    return plan
