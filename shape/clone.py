"""Set up a new (or factory-reset) phone the way another one was.

Everything needed is already on disk for the old phone: the change log says
exactly what was done, preferences.md says why, keep.json says what not to
touch, and launcher/current.json is the home screen. Cloning turns the old
phone's active changes into a normal, reviewable plan for the new phone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

from . import probe
from .adb import Device
from .state import PREFERENCES_TEMPLATE, PhoneState, now_iso, read_json, shape_home

SKIP_KINDS = {"home", "app.install", "launcher.config"}  # handled by the launcher step


def known_phones(root: Optional[Path] = None) -> List[dict]:
    root = root or shape_home()
    out = []
    if not root.exists():
        return out
    for d in sorted(p for p in root.iterdir() if (p / "profile.json").exists()):
        prof = read_json(d / "profile.json", {}) or {}
        changes = read_json(d / "changes.json", []) or []
        applied = [c for c in changes if c.get("status") == "applied"]
        out.append({
            "key": d.name,
            "phone": "%s %s" % (prof.get("manufacturer", "?"), prof.get("model", "?")),
            "android": prof.get("android", "?"),
            "active_changes": len(applied),
            "last_change": max((c.get("ts", "") for c in changes), default=""),
            "has_launcher_config": (d / "launcher" / "current.json").exists(),
        })
    return out


def find_phone(spec: str, root: Optional[Path] = None) -> Path:
    root = root or shape_home()
    matches = [p for p in root.iterdir() if p.name.startswith(spec) and (p / "profile.json").exists()] if root.exists() else []
    if not matches:
        raise ValueError("No saved phone matches %r. Known phones: %s" % (
            spec, ", ".join(p["key"] for p in known_phones(root)) or "none"))
    if len(matches) > 1:
        raise ValueError("%r matches several phones: %s" % (spec, ", ".join(m.name for m in matches)))
    return matches[0]


def build_plan(dev: Device, ps: PhoneState, src: Path) -> Tuple[dict, Optional[dict]]:
    changes = read_json(src / "changes.json", []) or []
    latest = {}
    for c in sorted((c for c in changes if c.get("status") == "applied"), key=lambda c: c["id"]):
        if c["kind"] not in SKIP_KINDS:
            latest[(c["kind"], c["target"])] = c
    states = probe.package_states(dev)

    def installed(pkg: str) -> bool:
        st = states.get(pkg)
        return bool(st) and st["state"] != "absent"

    actions, skipped = [], []
    for (kind, target), c in latest.items():
        a = None
        if kind in ("package.disable", "package.remove", "package.enable"):
            if installed(target):
                a = {"op": kind.split(".")[1], "pkg": target}
        elif kind == "setting":
            ns, key = target.split("/", 1)
            a = {"op": "setting", "ns": ns, "key": key, "value": c["after"]}
        elif kind in ("permission.grant", "permission.revoke"):
            pkg, perm = target.split(" ", 1)
            if installed(pkg):
                a = {"op": "perm-" + kind.split(".")[1], "pkg": pkg, "perm": perm}
        elif kind == "appop":
            pkg, op = target.split(" ", 1)
            if installed(pkg):
                a = {"op": "appop", "pkg": pkg, "appop": op, "mode": c["after"]}
        elif kind == "standby":
            if installed(target):
                a = {"op": "standby", "pkg": target, "bucket": c["after"]}
        elif kind == "nightmode":
            a = {"op": "nightmode", "mode": c["after"]}
        if a is None:
            skipped.append({"kind": kind, "target": target, "reason": "not on this phone"})
            continue
        a["why"] = c.get("note") or "as on %s" % src.name
        a["name"] = target
        actions.append(a)
    launcher_cfg = read_json(src / "launcher" / "current.json")
    plan = {"kind": "clone", "created": now_iso(), "device": ps.key, "source": src.name,
            "actions": actions, "skipped": skipped,
            "launcher": "will install the Shape launcher and push the old home screen" if launcher_cfg else "none"}
    return plan, launcher_cfg


def copy_memory(ps: PhoneState, src: Path) -> List[str]:
    """Bring over preferences.md and keep.json. Never overwrites notes the owner already wrote here."""
    notes = []
    src_prefs = src / "preferences.md"
    dst_prefs = ps.path("preferences.md")
    if src_prefs.exists():
        model = "%s %s" % (ps.profile().get("manufacturer", ""), ps.profile().get("model", ""))
        untouched = (not dst_prefs.exists()) or dst_prefs.read_text() == PREFERENCES_TEMPLATE.format(model=model)
        if untouched:
            dst_prefs.write_text(src_prefs.read_text().replace("\n## History", "\n## History\n- %s — cloned from %s" % (now_iso()[:10], src.name), 1))
            notes.append("preferences.md copied from %s" % src.name)
        else:
            notes.append("preferences.md already has notes here; merge by hand from %s" % src_prefs)
    keep = sorted(set(ps.keep()) | set(read_json(src / "keep.json", []) or []))
    ps.set_keep(keep)
    if keep:
        notes.append("keep list: %s" % ", ".join(keep))
    return notes


def dump(plan: dict) -> str:
    return json.dumps(plan, indent=2)
