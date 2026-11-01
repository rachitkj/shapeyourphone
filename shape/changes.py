"""Every change to the phone is an Op with a `do` and an `undo` shell command.

Ops are executed, verified against the phone's real state, and appended to
devices/<key>/changes.json. Undo, full restore, drift detection and the
generated restore.sh are all driven by that log, so nothing is ever applied
that we can't take back.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import asdict, dataclass, field
from typing import Callable, List, Optional

from .adb import Device, quote
from .state import PhoneState, now_iso, read_json, write_json

STANDBY_NAMES = {5: "exempted", 10: "active", 20: "working_set", 30: "frequent", 40: "rare", 45: "restricted", 50: "never"}


# -- reading current state ---------------------------------------------------

def _exact_pkg_in(out: str, pkg: str) -> bool:
    return ("package:" + pkg) in {l.strip() for l in out.splitlines()}


def package_state(dev: Device, pkg: str, user: str) -> str:
    if not _exact_pkg_in(dev.shell("pm", "list", "packages", "--user", user, pkg), pkg):
        if _exact_pkg_in(dev.shell("pm", "list", "packages", "-u", "--user", user, pkg), pkg):
            return "removed-for-user"
        return "absent"
    if _exact_pkg_in(dev.shell("pm", "list", "packages", "-d", "--user", user, pkg), pkg):
        return "disabled"
    return "enabled"


def permission_granted(dev: Device, pkg: str, perm: str) -> Optional[bool]:
    out = dev.shell("dumpsys", "package", pkg)
    m = re.search(re.escape(perm) + r": granted=(true|false)", out)
    return None if not m else m.group(1) == "true"


def appop_mode(dev: Device, pkg: str, op: str) -> str:
    out = dev.shell("cmd", "appops", "get", pkg, op)
    m = re.search(re.escape(op) + r": (\w+)", out)
    return m.group(1) if m else "default"


def standby_bucket(dev: Device, pkg: str) -> str:
    out = dev.shell("am", "get-standby-bucket", pkg).strip()
    try:
        return STANDBY_NAMES.get(int(out), out)
    except ValueError:
        return out or "unknown"


def night_mode(dev: Device) -> str:
    out = dev.shell("cmd", "uimode", "night")
    m = re.search(r"Night mode: (\w+)", out)
    return m.group(1) if m else "unknown"


def read_state(dev: Device, kind: str, target: str, user: str) -> str:
    if kind.startswith("package."):
        return package_state(dev, target, user)
    if kind == "setting":
        ns, key = target.split("/", 1)
        v = dev.setting(ns, key)
        return "null" if v is None else v
    if kind.startswith("permission."):
        pkg, perm = target.split(" ", 1)
        g = permission_granted(dev, pkg, perm)
        return "unknown" if g is None else ("granted" if g else "revoked")
    if kind == "appop":
        pkg, op = target.split(" ", 1)
        return appop_mode(dev, pkg, op)
    if kind == "standby":
        return standby_bucket(dev, target)
    if kind == "nightmode":
        return night_mode(dev)
    if kind == "home":
        from .probe import current_home
        return current_home(dev) or "none"
    if kind == "app.install":
        return "installed" if dev.shell("pm", "path", target).strip() else "absent"
    return "unknown"


# -- ops ---------------------------------------------------------------------

@dataclass
class Op:
    kind: str
    target: str
    before: str
    after: str
    do: str
    undo: str
    note: str = ""
    # some ops run on the host (adb install) or in Python (launcher config)
    host_do: Optional[Callable[[], tuple]] = field(default=None, repr=False, compare=False)

    @property
    def noop(self) -> bool:
        return self.before == self.after


def op_package_disable(dev: Device, pkg: str, note: str = "") -> Op:
    u = dev.user
    before = package_state(dev, pkg, u)
    if before == "disabled":
        return Op("package.disable", pkg, before, "disabled", "", "", note)
    undo = quote(["pm", "enable", "--user", u, pkg])
    return Op("package.disable", pkg, before, "disabled", quote(["pm", "disable-user", "--user", u, pkg]), undo, note)


def op_package_remove(dev: Device, pkg: str, note: str = "") -> Op:
    """Uninstall for this user only (`-k` keeps data). The APK stays on the system partition."""
    u = dev.user
    before = package_state(dev, pkg, u)
    if before == "removed-for-user":
        return Op("package.remove", pkg, before, "removed-for-user", "", "", note)
    undo = quote(["pm", "install-existing", "--user", u, pkg])
    if before == "disabled":
        undo += " && " + quote(["pm", "disable-user", "--user", u, pkg])
    return Op("package.remove", pkg, before, "removed-for-user", quote(["pm", "uninstall", "-k", "--user", u, pkg]), undo, note)


def op_package_enable(dev: Device, pkg: str, note: str = "") -> Op:
    u = dev.user
    before = package_state(dev, pkg, u)
    if before == "removed-for-user":
        do, undo = quote(["pm", "install-existing", "--user", u, pkg]), quote(["pm", "uninstall", "-k", "--user", u, pkg])
    else:
        do, undo = quote(["pm", "enable", "--user", u, pkg]), quote(["pm", "disable-user", "--user", u, pkg])
    if before == "enabled":
        do = undo = ""
    return Op("package.enable", pkg, before, "enabled", do, undo, note)


def op_setting(dev: Device, ns: str, key: str, value: str, note: str = "") -> Op:
    if ns not in ("global", "secure", "system"):
        raise ValueError("settings namespace must be global, secure or system")
    cur = dev.setting(ns, key)
    before = "null" if cur is None else cur
    value = str(value)
    if value == "null":
        do = quote(["settings", "delete", ns, key])
    else:
        do = quote(["settings", "put", ns, key, value])
    undo = quote(["settings", "delete", ns, key]) if cur is None else quote(["settings", "put", ns, key, cur])
    return Op("setting", "%s/%s" % (ns, key), before, value, do, undo, note)


def op_permission(dev: Device, pkg: str, perm: str, grant: bool, note: str = "") -> Op:
    g = permission_granted(dev, pkg, perm)
    before = "unknown" if g is None else ("granted" if g else "revoked")
    after = "granted" if grant else "revoked"
    do = quote(["pm", "grant" if grant else "revoke", pkg, perm])
    undo = quote(["pm", "revoke" if grant else "grant", pkg, perm])
    return Op("permission." + ("grant" if grant else "revoke"), "%s %s" % (pkg, perm), before, after, do, undo, note)


def op_appop(dev: Device, pkg: str, op: str, mode: str, note: str = "") -> Op:
    before = appop_mode(dev, pkg, op)
    return Op("appop", "%s %s" % (pkg, op), before, mode,
              quote(["cmd", "appops", "set", pkg, op, mode]),
              quote(["cmd", "appops", "set", pkg, op, before]), note)


def op_standby(dev: Device, pkg: str, bucket: str, note: str = "") -> Op:
    before = standby_bucket(dev, pkg)
    undo_bucket = before if before in ("active", "working_set", "frequent", "rare", "restricted") else "active"
    return Op("standby", pkg, before, bucket,
              quote(["am", "set-standby-bucket", pkg, bucket]),
              quote(["am", "set-standby-bucket", pkg, undo_bucket]), note)


def op_night_mode(dev: Device, mode: str, note: str = "") -> Op:
    before = night_mode(dev)
    undo_mode = before if before in ("yes", "no", "auto") else "no"
    return Op("nightmode", "uimode", before, mode,
              quote(["cmd", "uimode", "night", mode]),
              quote(["cmd", "uimode", "night", undo_mode]), note)


def _set_home_cmd(dev: Device, component: str) -> str:
    u = dev.user
    pkg = component.split("/")[0]
    cmds = []
    if dev.sdk >= 29:
        cmds.append(quote(["cmd", "role", "add-role-holder", "--user", u, "android.app.role.HOME", pkg]))
    cmds.append(quote(["cmd", "package", "set-home-activity", "--user", u, component]))
    return "; ".join(cmds)


def op_home(dev: Device, component: str, note: str = "") -> Op:
    from .probe import current_home, home_candidates
    before = current_home(dev)
    if before is None:
        others = [c for c in home_candidates(dev) if c.split("/")[0] != component.split("/")[0]]
        before_for_undo = others[0] if others else None
    else:
        before_for_undo = before
    undo = _set_home_cmd(dev, before_for_undo) if before_for_undo else ""
    return Op("home", component, before or "none", component, _set_home_cmd(dev, component), undo, note)


# -- the log -----------------------------------------------------------------

@dataclass
class Change:
    id: int
    ts: str
    kind: str
    target: str
    before: str
    after: str
    do: str
    undo: str
    note: str = ""
    source: str = ""
    status: str = "applied"  # applied | undone | failed
    error: str = ""
    undone_ts: str = ""
    data: dict = field(default_factory=dict)


class ChangeLog:
    def __init__(self, ps: PhoneState):
        self.ps = ps
        self.path = ps.path("changes.json")
        self.changes: List[Change] = [Change(**c) for c in (read_json(self.path, []) or [])]

    def save(self) -> None:
        write_json(self.path, [asdict(c) for c in self.changes])

    def next_id(self) -> int:
        return (max((c.id for c in self.changes), default=0)) + 1

    def add(self, op: Op, source: str, status: str, error: str = "", data: Optional[dict] = None) -> Change:
        c = Change(self.next_id(), now_iso(), op.kind, op.target, op.before, op.after, op.do, op.undo,
                   op.note, source, status, error, "", data or {})
        self.changes.append(c)
        self.save()
        return c

    def get(self, cid: int) -> Optional[Change]:
        return next((c for c in self.changes if c.id == cid), None)

    def applied(self) -> List[Change]:
        return [c for c in self.changes if c.status == "applied"]


@dataclass
class Result:
    status: str  # applied | skipped | failed
    op: Op
    change: Optional[Change] = None
    message: str = ""


def execute(dev: Device, log: ChangeLog, op: Op, source: str) -> Result:
    if op.noop:
        return Result("skipped", op, message="already %s" % op.after)
    if op.host_do is not None:
        ok, msg = op.host_do()
        out = msg
    else:
        out = dev.sh(op.do)
    now = read_state(dev, op.kind, op.target, dev.user)
    if _matches(op.kind, now, op.after):
        return Result("applied", op, log.add(op, source, "applied"))
    err = (out or "").strip().splitlines()
    err_text = err[-1] if err else "state is '%s', expected '%s'" % (now, op.after)
    log.add(op, source, "failed", err_text)
    return Result("failed", op, message=err_text)


def _matches(kind: str, now: str, want: str) -> bool:
    if kind == "home":
        return now.split("/")[0] == want.split("/")[0]
    if kind == "setting":
        return now == want or (want == "null" and now in ("null", ""))
    return now == want


def undo_change(dev: Device, log: ChangeLog, c: Change, launcher_undo: Optional[Callable[[Change], tuple]] = None) -> Result:
    op = Op(c.kind, c.target, c.after, c.before, c.undo, c.do, c.note)
    if c.status != "applied":
        return Result("skipped", op, c, "change %d is %s" % (c.id, c.status))
    if c.kind == "launcher.config":
        if launcher_undo is None:
            return Result("skipped", op, c, "launcher config undo needs the launcher")
        ok, msg = launcher_undo(c)
        if not ok:
            return Result("failed", op, c, msg)
    else:
        if not c.undo:
            return Result("failed", op, c, "no undo command recorded")
        dev.sh(c.undo)
        now = read_state(dev, c.kind, c.target, dev.user)
        expected = c.before
        if c.kind == "home" and c.before == "none":
            expected = now  # nothing specific to return to; any non-Shape home is fine
        if not _matches(c.kind, now, expected):
            return Result("failed", op, c, "after undo, state is '%s', expected '%s'" % (now, c.before))
    c.status = "undone"
    c.undone_ts = now_iso()
    log.save()
    return Result("applied", op, c)


def drift(dev: Device, log: ChangeLog) -> List[dict]:
    """Applied changes the phone no longer reflects (e.g. after a system update)."""
    out = []
    latest = {}
    for c in log.applied():
        if c.kind == "launcher.config":
            continue
        latest[(c.kind, c.target)] = c  # newest change per target wins
    for c in latest.values():
        now = read_state(dev, c.kind, c.target, dev.user)
        if not _matches(c.kind, now, c.after):
            out.append({"id": c.id, "kind": c.kind, "target": c.target, "expected": c.after, "now": now, "redo": c.do})
    return out


def restore_script(log: ChangeLog, serial_hint: str = "") -> str:
    lines = [
        "#!/bin/sh",
        "# Generated by shapeyourphone. Undoes every change, newest first.",
        "# Usage: sh restore.sh [adb-serial]      (needs adb on PATH, or set ADB=/path/to/adb)",
        'ADB="${ADB:-adb}"',
        'if [ -n "$1" ]; then S="-s $1"; else S=""; fi',
        "",
    ]
    for c in sorted(log.applied(), key=lambda c: c.id, reverse=True):
        if c.kind == "launcher.config" or not c.undo:
            continue
        lines.append("# #%d %s %s (%s -> %s)" % (c.id, c.kind, c.target, c.before, c.after))
        lines.append('$ADB $S shell %s' % shlex.quote(c.undo))
    lines.append('echo "Done. Reboot the phone if anything looks off."')
    return "\n".join(lines) + "\n"
