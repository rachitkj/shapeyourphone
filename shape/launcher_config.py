"""The launcher's config format (v1): validation, rule evaluation, summaries.

The launcher (launcher/app/src/main/java/.../config) implements the same rule
semantics; tests/vectors/rules.json is run by both test suites to keep them in
lockstep. Full reference: docs/launcher-config.md
"""

from __future__ import annotations

import copy
import datetime as _dt
import re
from typing import List, Optional, Tuple

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
PKG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")
ROLE_TOKENS = {"@dialer", "@sms", "@browser", "@camera", "@settings"}
FONTS = {"sans", "light", "thin", "medium", "condensed", "serif", "mono"}
ICON_STYLES = {"color", "mono", "grayscale", "none"}
ALIGN = {"start", "center", "end"}
APP_STYLES = {"list", "grid", "row"}
TEXT_COLORS = {"foreground", "secondary", "accent"}
GESTURE_ACTIONS = {"drawer", "search", "notifications", "quickSettings", "homeSettings", "none"}
WIDGET_TYPES = {"clock", "text", "spacer", "apps", "search", "calendar"}

TOP_KEYS = {"version", "name", "theme", "home", "dock", "drawer", "labels", "gestures", "pause", "rules"}
PAUSE_KEYS = {"apps", "seconds", "message"}
THEME_KEYS = {"background", "dim", "foreground", "secondary", "accent", "font", "textSize", "iconStyle", "iconSize", "padding"}
DOCK_KEYS = {"apps", "labels"}
DRAWER_KEYS = {"style", "columns", "showSearch", "autoLaunch", "hidden", "searchOnly"}
GESTURE_KEYS = {"swipeUp", "swipeDown", "doubleTap", "longPress"}
RULE_KEYS = {"name", "days", "from", "to", "hide", "set"}
WIDGET_KEYS = {
    "clock": {"type", "format", "size", "showDate", "dateFormat", "align"},
    "text": {"type", "text", "size", "align", "color"},
    "spacer": {"type", "height", "flex"},
    "apps": {"type", "apps", "style", "columns", "align", "labels", "size"},
    "search": {"type", "hint"},
    "calendar": {"type", "hours", "align", "size"},
}


class Report:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def err(self, where: str, msg: str) -> None:
        self.errors.append("%s: %s" % (where, msg))

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append("%s: %s" % (where, msg))

    @property
    def ok(self) -> bool:
        return not self.errors


def _unknown(r: Report, where: str, obj: dict, allowed: set) -> None:
    for k in obj:
        if k not in allowed and not k.startswith("_"):
            r.warn(where, "unknown key %r is ignored by the launcher" % k)


def _num(r: Report, where: str, v, lo: float, hi: float) -> None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        r.err(where, "must be a number")
    elif not lo <= v <= hi:
        r.err(where, "must be between %s and %s" % (lo, hi))


def _bool(r: Report, where: str, v) -> None:
    if not isinstance(v, bool):
        r.err(where, "must be true or false")


def _enum(r: Report, where: str, v, allowed: set) -> None:
    if v not in allowed:
        r.err(where, "must be one of %s" % ", ".join(sorted(allowed)))


def _color(r: Report, where: str, v, allow_names: bool = False, allow_wallpaper: bool = False) -> None:
    if isinstance(v, str) and COLOR_RE.match(v):
        return
    if allow_wallpaper and v == "wallpaper":
        return
    if allow_names and v in TEXT_COLORS:
        return
    extra = (" or 'wallpaper'" if allow_wallpaper else "") + (" or foreground/secondary/accent" if allow_names else "")
    r.err(where, "must be a color like #RRGGBB" + extra)


def _appref(r: Report, where: str, v, known: Optional[set]) -> None:
    if not isinstance(v, str):
        r.err(where, "must be a package name string")
        return
    if v in ROLE_TOKENS:
        return
    pkg = v.split("/")[0]
    if not PKG_RE.match(pkg):
        r.err(where, "%r is not a package name (or @dialer/@sms/@browser/@camera/@settings)" % v)
    elif known is not None and pkg not in known:
        r.warn(where, "%s is not installed on this phone; it will be skipped" % pkg)


def _applist(r: Report, where: str, v, known: Optional[set]) -> None:
    if not isinstance(v, list):
        r.err(where, "must be a list of package names")
        return
    for i, a in enumerate(v):
        _appref(r, "%s[%d]" % (where, i), a, known)


def _widget(r: Report, where: str, w, known: Optional[set]) -> None:
    if not isinstance(w, dict):
        r.err(where, "must be an object")
        return
    t = w.get("type")
    if t not in WIDGET_TYPES:
        r.err(where, "type must be one of %s" % ", ".join(sorted(WIDGET_TYPES)))
        return
    _unknown(r, where, w, WIDGET_KEYS[t])
    if "align" in w:
        _enum(r, where + ".align", w["align"], ALIGN)
    if "size" in w:
        _num(r, where + ".size", w["size"], 8, 160)
    if t == "clock":
        for k in ("format", "dateFormat"):
            if k in w and (not isinstance(w[k], str) or not w[k].strip()):
                r.err(where + "." + k, "must be a date/time pattern like HH:mm")
        if "showDate" in w:
            _bool(r, where + ".showDate", w["showDate"])
    elif t == "text":
        if not isinstance(w.get("text"), str):
            r.err(where + ".text", "is required and must be a string")
        if "color" in w:
            _color(r, where + ".color", w["color"], allow_names=True)
    elif t == "spacer":
        if "height" in w:
            _num(r, where + ".height", w["height"], 0, 400)
        if "flex" in w:
            _num(r, where + ".flex", w["flex"], 0, 10)
    elif t == "apps":
        _applist(r, where + ".apps", w.get("apps", []), known)
        if "style" in w:
            _enum(r, where + ".style", w["style"], APP_STYLES)
        if "columns" in w:
            _num(r, where + ".columns", w["columns"], 1, 8)
        if "labels" in w:
            _bool(r, where + ".labels", w["labels"])
        if len(w.get("apps", [])) > 12 and w.get("style", "list") == "list":
            r.warn(where, "more than 12 apps in a list may not fit on screen; consider style 'grid'")
    elif t == "search":
        if "hint" in w and not isinstance(w["hint"], str):
            r.err(where + ".hint", "must be a string")
    elif t == "calendar":
        if "hours" in w:
            _num(r, where + ".hours", w["hours"], 1, 168)


def _partial(r: Report, where: str, cfg: dict, known: Optional[set]) -> None:
    """Validate the parts of a config that are present (used for rules' `set`)."""
    if "theme" in cfg:
        t = cfg["theme"]
        if not isinstance(t, dict):
            r.err(where + ".theme", "must be an object")
        else:
            _unknown(r, where + ".theme", t, THEME_KEYS)
            if "background" in t:
                _color(r, where + ".theme.background", t["background"], allow_wallpaper=True)
            for k in ("foreground", "secondary", "accent"):
                if k in t:
                    _color(r, where + ".theme." + k, t[k])
            if "dim" in t:
                _num(r, where + ".theme.dim", t["dim"], 0, 1)
            if "font" in t:
                _enum(r, where + ".theme.font", t["font"], FONTS)
            if "textSize" in t:
                _num(r, where + ".theme.textSize", t["textSize"], 10, 40)
            if "iconStyle" in t:
                _enum(r, where + ".theme.iconStyle", t["iconStyle"], ICON_STYLES)
            if "iconSize" in t:
                _num(r, where + ".theme.iconSize", t["iconSize"], 16, 96)
            if "padding" in t:
                _num(r, where + ".theme.padding", t["padding"], 0, 64)
    if "home" in cfg:
        if not isinstance(cfg["home"], list):
            r.err(where + ".home", "must be a list of widgets")
        else:
            for i, w in enumerate(cfg["home"]):
                _widget(r, "%s.home[%d]" % (where, i), w, known)
    if "dock" in cfg:
        d = cfg["dock"]
        if not isinstance(d, dict):
            r.err(where + ".dock", "must be an object")
        else:
            _unknown(r, where + ".dock", d, DOCK_KEYS)
            if "apps" in d:
                _applist(r, where + ".dock.apps", d["apps"], known)
                if isinstance(d["apps"], list) and len(d["apps"]) > 6:
                    r.warn(where + ".dock.apps", "more than 6 dock apps will be cramped")
            if "labels" in d:
                _bool(r, where + ".dock.labels", d["labels"])
    if "drawer" in cfg:
        d = cfg["drawer"]
        if not isinstance(d, dict):
            r.err(where + ".drawer", "must be an object")
        else:
            _unknown(r, where + ".drawer", d, DRAWER_KEYS)
            if "style" in d:
                _enum(r, where + ".drawer.style", d["style"], {"list", "grid"})
            if "columns" in d:
                _num(r, where + ".drawer.columns", d["columns"], 2, 6)
            for k in ("showSearch", "autoLaunch"):
                if k in d:
                    _bool(r, where + ".drawer." + k, d[k])
            for k in ("hidden", "searchOnly"):
                if k in d:
                    _applist(r, where + ".drawer." + k, d[k], known)
    if "labels" in cfg:
        lab = cfg["labels"]
        if not isinstance(lab, dict) or not all(isinstance(v, str) for v in lab.values()):
            r.err(where + ".labels", "must map package names to display names")
        else:
            for k in lab:
                _appref(r, where + ".labels", k, known)
    if "pause" in cfg:
        pz = cfg["pause"]
        if not isinstance(pz, dict):
            r.err(where + ".pause", "must be an object")
        else:
            _unknown(r, where + ".pause", pz, PAUSE_KEYS)
            _applist(r, where + ".pause.apps", pz.get("apps", []), known)
            if "seconds" in pz:
                _num(r, where + ".pause.seconds", pz["seconds"], 1, 60)
            if "message" in pz and not isinstance(pz["message"], str):
                r.err(where + ".pause.message", "must be a string")
    if "gestures" in cfg:
        g = cfg["gestures"]
        if not isinstance(g, dict):
            r.err(where + ".gestures", "must be an object")
        else:
            _unknown(r, where + ".gestures", g, GESTURE_KEYS)
            for k, v in g.items():
                if k in GESTURE_KEYS and v not in GESTURE_ACTIONS and not (isinstance(v, str) and v.startswith("app:")):
                    r.err(where + ".gestures." + k, "must be one of %s or app:<package>" % ", ".join(sorted(GESTURE_ACTIONS)))
                elif isinstance(v, str) and v.startswith("app:"):
                    _appref(r, where + ".gestures." + k, v[4:], known)


def validate(cfg, installed: Optional[set] = None) -> Report:
    r = Report()
    if not isinstance(cfg, dict):
        r.err("config", "must be a JSON object")
        return r
    if cfg.get("version") != 1:
        r.err("version", "must be 1")
    _unknown(r, "config", cfg, TOP_KEYS)
    if "name" in cfg and not isinstance(cfg["name"], str):
        r.err("name", "must be a string")
    _partial(r, "config", cfg, installed)
    rules = cfg.get("rules", [])
    if not isinstance(rules, list):
        r.err("rules", "must be a list")
        rules = []
    for i, rule in enumerate(rules):
        where = "rules[%d]" % i
        if not isinstance(rule, dict):
            r.err(where, "must be an object")
            continue
        _unknown(r, where, rule, RULE_KEYS)
        if "days" in rule:
            if not isinstance(rule["days"], list) or not all(d in DAYS for d in rule["days"]):
                r.err(where + ".days", "must be a list of mon/tue/wed/thu/fri/sat/sun")
        for k in ("from", "to"):
            if k in rule and not (isinstance(rule[k], str) and TIME_RE.match(rule[k])):
                r.err(where + "." + k, "must be HH:MM (24-hour)")
        if ("from" in rule) != ("to" in rule):
            r.err(where, "needs both 'from' and 'to', or neither")
        if "hide" in rule:
            _applist(r, where + ".hide", rule["hide"], installed)
        if "set" in rule:
            if not isinstance(rule["set"], dict):
                r.err(where + ".set", "must be an object")
            else:
                bad = set(rule["set"]) - (TOP_KEYS - {"version", "rules", "name"})
                for k in bad:
                    r.err(where + ".set", "can't change %r from a rule" % k)
                _partial(r, where + ".set", rule["set"], installed)
        if "hide" not in rule and "set" not in rule:
            r.warn(where, "rule changes nothing (add 'hide' or 'set')")
    return r


# -- rules -------------------------------------------------------------------

def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def is_active(rule: dict, day: int, minute: int) -> bool:
    """day: 1=Mon..7=Sun, minute: 0..1439. Overnight windows belong to the day they start."""
    days = {DAYS.index(d) + 1 for d in rule.get("days", DAYS)}
    if "from" not in rule or "to" not in rule:
        return day in days
    f, t = _minutes(rule["from"]), _minutes(rule["to"])
    if f == t:
        return day in days
    if f < t:
        return day in days and f <= minute < t
    prev = 7 if day == 1 else day - 1
    return (minute >= f and day in days) or (minute < t and prev in days)


def deep_merge(base: dict, overlay: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def effective(cfg: dict, day: int, minute: int) -> Tuple[dict, List[str], List[str]]:
    """(merged config, extra hidden packages, names of active rules)"""
    merged = {k: v for k, v in cfg.items() if k != "rules"}
    hidden: List[str] = []
    active: List[str] = []
    for i, rule in enumerate(cfg.get("rules", [])):
        if not is_active(rule, day, minute):
            continue
        active.append(rule.get("name") or "rule %d" % (i + 1))
        if isinstance(rule.get("set"), dict):
            merged = deep_merge(merged, rule["set"])
        for p in rule.get("hide", []):
            if p not in hidden:
                hidden.append(p)
    return merged, hidden, active


def parse_at(s: Optional[str]) -> Tuple[int, int]:
    """'fri 22:30' -> (5, 1350). None -> now."""
    if not s:
        n = _dt.datetime.now()
        return n.isoweekday(), n.hour * 60 + n.minute
    parts = s.strip().lower().split()
    if len(parts) != 2 or parts[0][:3] not in DAYS or not TIME_RE.match(parts[1]):
        raise ValueError("time must look like 'fri 22:30'")
    return DAYS.index(parts[0][:3]) + 1, _minutes(parts[1])


def summarize(cfg: dict, labels: Optional[dict] = None) -> List[str]:
    """Plain-language description for showing the owner before a push."""
    labels = labels or {}

    def name(a: str) -> str:
        return (cfg.get("labels", {}) or {}).get(a) or labels.get(a.split("/")[0]) or a

    out = []
    t = cfg.get("theme", {})
    bg = t.get("background", "#0B0B0C")
    out.append("Look: %s background, %s text, %s font, icons: %s" % (
        "wallpaper" if bg == "wallpaper" else bg, t.get("foreground", "#F2F2F2"), t.get("font", "sans"), t.get("iconStyle", "color")))
    for w in cfg.get("home", []):
        typ = w.get("type")
        if typ == "clock":
            out.append("Home: clock%s" % (" with date" if w.get("showDate", True) else ""))
        elif typ == "apps":
            out.append("Home: %s of %s" % (w.get("style", "list"), ", ".join(name(a) for a in w.get("apps", [])) or "(no apps)"))
        elif typ == "text":
            out.append("Home: text \"%s\"" % w.get("text", ""))
        elif typ == "search":
            out.append("Home: search bar")
        elif typ == "calendar":
            out.append("Home: next calendar event")
    dock = cfg.get("dock", {}).get("apps", [])
    if dock:
        out.append("Dock: " + ", ".join(name(a) for a in dock))
    d = cfg.get("drawer", {})
    if d.get("hidden"):
        out.append("Hidden everywhere: " + ", ".join(name(a) for a in d["hidden"]))
    if d.get("searchOnly"):
        out.append("Only via search: " + ", ".join(name(a) for a in d["searchOnly"]))
    pz = cfg.get("pause", {})
    if pz.get("apps"):
        out.append("Pause %ss before opening: %s" % (pz.get("seconds", 5), ", ".join(name(a) for a in pz["apps"])))
    g = cfg.get("gestures", {})
    if g:
        out.append("Gestures: " + ", ".join("%s → %s" % (k, v) for k, v in g.items()))
    for rule in cfg.get("rules", []):
        when = ",".join(rule.get("days", [])) or "every day"
        if "from" in rule:
            when += " %s–%s" % (rule["from"], rule["to"])
        what = []
        if rule.get("hide"):
            what.append("hide " + ", ".join(name(a) for a in rule["hide"]))
        if rule.get("set"):
            what.append("change " + ", ".join(rule["set"].keys()))
        out.append("Rule '%s' (%s): %s" % (rule.get("name", "unnamed"), when, "; ".join(what) or "nothing"))
    return out
