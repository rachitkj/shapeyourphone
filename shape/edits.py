"""High-level, name-based edits to the launcher config.

`shape launcher hide Instagram --from 22:00 --to 07:00` is safer for an agent
(and nicer for a human) than hand-editing JSON: apps are resolved by the name
the owner uses, and each edit is a small pure function that is easy to test.
"""

from __future__ import annotations

import copy
import re
from typing import Dict, List, Optional

from .launcher_config import DAYS, PKG_RE, ROLE_TOKENS, TIME_RE

DAY_GROUPS = {
    "weekdays": ["mon", "tue", "wed", "thu", "fri"],
    "weekends": ["sat", "sun"],
    "everyday": list(DAYS),
}


class EditError(ValueError):
    pass


class AppResolver:
    """Turns 'Instagram', 'insta', 'com.instagram.android' or '@camera' into a package / token."""

    def __init__(self, apps: List[dict]):
        self.apps = apps
        self.by_pkg = {a["package"]: a for a in apps}

    def label(self, pkg: str) -> str:
        return self.by_pkg.get(pkg, {}).get("label", pkg)

    def resolve(self, name: str) -> str:
        n = name.strip()
        if n.startswith("@"):
            if n not in ROLE_TOKENS:
                raise EditError("%s isn't a known role. Use one of: %s" % (n, ", ".join(sorted(ROLE_TOKENS))))
            return n
        if n in self.by_pkg:
            return n
        key = n.casefold()
        for test in (lambda l: l == key, lambda l: l.startswith(key), lambda l: key in l):
            hits = sorted({a["package"] for a in self.apps if test(a["label"].casefold())})
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                raise EditError("'%s' matches several apps: %s. Be more specific or use the package name." % (
                    name, ", ".join("%s (%s)" % (self.label(p), p) for p in hits[:8])))
        if PKG_RE.match(n):
            return n  # a package that isn't installed (yet); the validator will warn
        close = [a["label"] for a in self.apps if key[:3] in a["label"].casefold()][:5]
        raise EditError("No app called '%s' on this phone.%s" % (name, (" Did you mean: " + ", ".join(close)) if close else ""))

    def resolve_all(self, names: List[str]) -> List[str]:
        out: List[str] = []
        for n in names:
            # allow "WhatsApp, Spotify" as well as separate arguments
            for part in [p for p in re.split(r"\s*,\s*", n) if p]:
                r = self.resolve(part)
                if r not in out:
                    out.append(r)
        return out


def parse_days(spec: Optional[str]) -> Optional[List[str]]:
    if not spec:
        return None
    s = spec.strip().lower()
    if s in DAY_GROUPS:
        return list(DAY_GROUPS[s])
    days = [d.strip()[:3] for d in s.split(",") if d.strip()]
    bad = [d for d in days if d not in DAYS]
    if bad:
        raise EditError("unknown day(s): %s. Use mon..sun, weekdays or weekends." % ", ".join(bad))
    return days


def when(days: Optional[str], start: Optional[str], end: Optional[str]) -> Optional[dict]:
    if (start is None) != (end is None):
        raise EditError("give both --from and --to")
    for t in (start, end):
        if t is not None and not TIME_RE.match(t):
            raise EditError("times must be HH:MM (24-hour), got %r" % t)
    d = parse_days(days)
    if d is None and start is None:
        return None
    w: dict = {}
    if d is not None and set(d) != set(DAYS):
        w["days"] = d
    if start is not None:
        w["from"], w["to"] = start, end
    return w or None  # "everyday" with no times means: always


def _drawer(cfg: dict) -> dict:
    return cfg.setdefault("drawer", {})


def _rule_name(w: dict) -> str:
    days = w.get("days")
    if days == DAY_GROUPS["weekdays"]:
        dpart = "Weekdays"
    elif days == DAY_GROUPS["weekends"]:
        dpart = "Weekends"
    elif days:
        dpart = "/".join(d.capitalize() for d in days)
    else:
        dpart = ""
    tpart = "%s–%s" % (w["from"], w["to"]) if "from" in w else ""
    return " ".join(p for p in (dpart, tpart) if p) or "Always"


def _same_when(rule: dict, w: dict) -> bool:
    return (rule.get("days") == w.get("days") and rule.get("from") == w.get("from") and rule.get("to") == w.get("to"))


# -- edits (each returns a new config) ----------------------------------------

def hide(cfg: dict, pkgs: List[str], w: Optional[dict] = None, name: Optional[str] = None) -> dict:
    cfg = copy.deepcopy(cfg)
    if not w:
        d = _drawer(cfg)
        d["hidden"] = list(dict.fromkeys(d.get("hidden", []) + pkgs))
        d["searchOnly"] = [p for p in d.get("searchOnly", []) if p not in pkgs]
        return cfg
    rules = cfg.setdefault("rules", [])
    target = next((r for r in rules if _same_when(r, w) and (name is None or r.get("name") == name)), None)
    if target is None:
        target = {"name": name or _rule_name(w), **w}
        rules.append(target)
    target["hide"] = list(dict.fromkeys(target.get("hide", []) + pkgs))
    return cfg


def unhide(cfg: dict, pkgs: List[str]) -> dict:
    cfg = copy.deepcopy(cfg)
    d = _drawer(cfg)
    for k in ("hidden", "searchOnly"):
        if k in d:
            d[k] = [p for p in d[k] if p not in pkgs]
    kept = []
    for r in cfg.get("rules", []):
        if "hide" in r:
            r["hide"] = [p for p in r["hide"] if p not in pkgs]
            if not r["hide"]:
                del r["hide"]
        if r.get("hide") or r.get("set"):
            kept.append(r)
    if "rules" in cfg:
        cfg["rules"] = kept
    return cfg


def search_only(cfg: dict, pkgs: List[str]) -> dict:
    cfg = copy.deepcopy(cfg)
    d = _drawer(cfg)
    d["searchOnly"] = list(dict.fromkeys(d.get("searchOnly", []) + pkgs))
    d["hidden"] = [p for p in d.get("hidden", []) if p not in pkgs]
    return cfg


def _merge_list(current: List[str], pkgs: List[str], mode: str) -> List[str]:
    if mode == "add":
        return list(dict.fromkeys(current + pkgs))
    if mode == "remove":
        return [p for p in current if p not in pkgs]
    return list(pkgs)


def dock(cfg: dict, pkgs: List[str], mode: str = "set") -> dict:
    cfg = copy.deepcopy(cfg)
    dk = cfg.setdefault("dock", {})
    dk["apps"] = _merge_list(dk.get("apps", []), pkgs, mode)
    return cfg


def home_apps(cfg: dict, pkgs: List[str], mode: str = "set", style: Optional[str] = None) -> dict:
    cfg = copy.deepcopy(cfg)
    home = cfg.setdefault("home", [])
    widget = next((w for w in home if w.get("type") == "apps"), None)
    if widget is None:
        widget = {"type": "apps", "style": style or "list", "apps": []}
        # put it after the first flexible spacer (bottom half of the screen), else at the end
        idx = next((i + 1 for i, w in enumerate(home) if w.get("type") == "spacer" and w.get("flex")), len(home))
        home.insert(idx, widget)
    widget["apps"] = _merge_list(widget.get("apps", []), pkgs, mode)
    if style:
        widget["style"] = style
    return cfg


THEME_KEYS = {"background", "dim", "foreground", "secondary", "accent", "font", "textSize", "iconStyle", "iconSize", "padding"}


def theme(cfg: dict, **changes) -> dict:
    cfg = copy.deepcopy(cfg)
    t = cfg.setdefault("theme", {})
    for k, v in changes.items():
        if v is None:
            continue
        if k not in THEME_KEYS:
            raise EditError("unknown theme setting %s" % k)
        t[k] = v
    return cfg


def gesture(cfg: dict, which: str, action: str) -> dict:
    cfg = copy.deepcopy(cfg)
    cfg.setdefault("gestures", {})[which] = action
    return cfg


def rename(cfg: dict, pkg: str, label: Optional[str]) -> dict:
    cfg = copy.deepcopy(cfg)
    labels = cfg.setdefault("labels", {})
    if label:
        labels[pkg] = label
    else:
        labels.pop(pkg, None)
    return cfg


def pause(cfg: dict, pkgs: List[str], mode: str = "add", seconds: Optional[int] = None, message: Optional[str] = None) -> dict:
    cfg = copy.deepcopy(cfg)
    p = cfg.setdefault("pause", {})
    p["apps"] = _merge_list(p.get("apps", []), pkgs, mode)
    if seconds is not None:
        p["seconds"] = seconds
    if message is not None:
        p["message"] = message
    if not p["apps"]:
        del cfg["pause"]
    return cfg


def remove_rule(cfg: dict, name: str) -> dict:
    cfg = copy.deepcopy(cfg)
    rules = cfg.get("rules", [])
    left = [r for r in rules if r.get("name") != name]
    if len(left) == len(rules):
        raise EditError("no rule named %r (see: shape launcher rules)" % name)
    cfg["rules"] = left
    return cfg


def diff_lines(before: List[str], after: List[str]) -> List[str]:
    """Line-level diff of two summaries, for showing the owner what will change."""
    b, a = set(before), set(after)
    return ["- " + l for l in before if l not in a] + ["+ " + l for l in after if l not in b]


def label_map(apps: List[dict]) -> Dict[str, str]:
    return {a["package"]: a["label"] for a in apps}
