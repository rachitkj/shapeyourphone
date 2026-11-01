"""Read-only inspection of a phone: profile, packages, roles, snapshot."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .adb import Device
from .state import PhoneState, now_iso, now_ts, write_json

# -- OEM skin detection ------------------------------------------------------

_SKIN_PROPS = [
    ("ro.mi.os.version.name", "HyperOS"),
    ("ro.miui.ui.version.name", "MIUI"),
    ("ro.build.version.oneui", "One UI"),
    ("ro.oxygen.version", "OxygenOS"),
    ("ro.build.version.oplusrom", "ColorOS"),
    ("ro.build.version.opporom", "ColorOS"),
    ("ro.build.version.realmeui", "realme UI"),
    ("ro.vivo.os.version", "Funtouch/OriginOS"),
    ("ro.build.version.emui", "EMUI"),
    ("ro.build.version.magic", "MagicOS"),
    ("ro.mot.build.customerid", "Moto"),
    ("ro.nothing.version.id", "Nothing OS"),
]


def detect_skin(dev: Device) -> str:
    for prop, name in _SKIN_PROPS:
        v = dev.prop(prop)
        if v:
            return "%s %s" % (name, v) if name not in ("Moto",) else name
    brand = dev.prop("ro.product.brand").lower()
    if brand == "google":
        return "Pixel (stock Android)"
    return "Android"


def profile(dev: Device) -> dict:
    return {
        "manufacturer": dev.prop("ro.product.manufacturer"),
        "brand": dev.prop("ro.product.brand"),
        "model": dev.prop("ro.product.model"),
        "device": dev.prop("ro.product.device"),
        "android": dev.prop("ro.build.version.release"),
        "sdk": dev.sdk,
        "skin": detect_skin(dev),
        "build": dev.prop("ro.build.display.id"),
        "security_patch": dev.prop("ro.build.version.security_patch"),
        "user": dev.user,
        "first_seen": now_iso(),
    }


# -- packages ----------------------------------------------------------------

def _pkg_set(out: str) -> set:
    return {l[len("package:"):].strip() for l in out.splitlines() if l.startswith("package:")}


def package_states(dev: Device, user: Optional[str] = None) -> Dict[str, dict]:
    """Map every package (including ones removed for this user) to its state."""
    user = user or dev.user
    every = _pkg_set(dev.shell("pm", "list", "packages", "-u", "--user", user))
    installed = _pkg_set(dev.shell("pm", "list", "packages", "--user", user))
    disabled = _pkg_set(dev.shell("pm", "list", "packages", "-d", "--user", user))
    system = _pkg_set(dev.shell("pm", "list", "packages", "-s", "--user", user))
    states = {}
    for p in sorted(every | installed):
        if p not in installed:
            state = "removed-for-user"
        elif p in disabled:
            state = "disabled"
        else:
            state = "enabled"
        states[p] = {"state": state, "system": p in system}
    return states


_COMPONENT = re.compile(r"^\s*([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)\s*$")


def launchable_components(dev: Device) -> List[str]:
    out = dev.shell(
        "cmd", "package", "query-activities", "--brief",
        "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
    )
    comps = []
    for line in out.splitlines():
        m = _COMPONENT.match(line)
        if m:
            comps.append("%s/%s" % (m.group(1), m.group(2)))
    return comps


def current_home(dev: Device) -> Optional[str]:
    """Component of the current default home app, or None if the user hasn't picked one."""
    out = dev.shell(
        "cmd", "package", "resolve-activity", "--brief",
        "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME",
    )
    for line in reversed(out.splitlines()):
        m = _COMPONENT.match(line)
        if m:
            pkg = m.group(1)
            if pkg == "android":  # ResolverActivity: no default chosen
                return None
            return "%s/%s" % (pkg, m.group(2))
    return None


def camera_package(dev: Device) -> Optional[str]:
    out = dev.shell("cmd", "package", "resolve-activity", "--brief", "-a", "android.media.action.STILL_IMAGE_CAMERA")
    for line in reversed(out.splitlines()):
        m = _COMPONENT.match(line)
        if m and m.group(1) != "android":
            return m.group(1)
    return None


def home_candidates(dev: Device) -> List[str]:
    """Every installed home-screen app (stock launcher first if it's listed)."""
    out = dev.shell(
        "cmd", "package", "query-activities", "--brief",
        "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME",
    )
    comps = []
    for line in out.splitlines():
        m = _COMPONENT.match(line)
        if m and m.group(1) != "android" and "fallbackhome" not in m.group(2).lower():
            comps.append("%s/%s" % (m.group(1), m.group(2)))
    return comps


def role_holders(dev: Device, role: str) -> List[str]:
    if dev.sdk < 29:
        return []
    out = dev.shell("cmd", "role", "get-role-holders", "--user", dev.user, role)
    return [p.strip() for p in re.split(r"[;\s]+", out) if re.match(r"^[A-Za-z0-9_.]+$", p.strip() or "-")]


def default_ime_package(dev: Device) -> Optional[str]:
    ime = dev.setting("secure", "default_input_method")
    return ime.split("/")[0] if ime else None


def webview_provider(dev: Device) -> Optional[str]:
    v = dev.setting("global", "webview_provider")
    if v:
        return v
    out = dev.shell("dumpsys", "webviewupdate")
    m = re.search(r"Current WebView package \(name, version\): \(([A-Za-z0-9_.]+)", out)
    return m.group(1) if m else None


def colon_list_packages(value: Optional[str]) -> List[str]:
    """'pkg/.Svc:pkg2/.Svc' -> ['pkg', 'pkg2']"""
    if not value:
        return []
    return sorted({part.split("/")[0] for part in value.split(":") if "/" in part})


def device_admins(dev: Device) -> List[str]:
    out = dev.shell("dumpsys", "device_policy")
    return sorted(set(re.findall(r"ComponentInfo\{([A-Za-z0-9_.]+)/", out)))


def used_ram_kb(dev: Device) -> Optional[int]:
    out = dev.shell("dumpsys", "meminfo")
    m = re.search(r"Used RAM:\s*([\d,]+)K", out)
    return int(m.group(1).replace(",", "")) if m else None


# -- snapshot ----------------------------------------------------------------

def take_snapshot(dev: Device, ps: PhoneState, label: str = "") -> str:
    ts = now_ts() + ("-" + label if label else "")
    d = ps.path("snapshots", ts)
    d.mkdir(parents=True, exist_ok=True)
    write_json(d / "packages.json", package_states(dev))
    for ns in ("global", "secure", "system"):
        (d / ("settings_%s.txt" % ns)).write_text(dev.shell("settings", "list", ns) + "\n")
    (d / "getprop.txt").write_text(dev.sh("getprop") + "\n")
    write_json(d / "roles.json", {
        "home": current_home(dev),
        "dialer": role_holders(dev, "android.app.role.DIALER"),
        "sms": role_holders(dev, "android.app.role.SMS"),
        "browser": role_holders(dev, "android.app.role.BROWSER"),
        "ime": dev.setting("secure", "default_input_method"),
        "webview": webview_provider(dev),
    })
    write_json(d / "meta.json", {"taken": now_iso(), "used_ram_kb": used_ram_kb(dev), "sdk": dev.sdk})
    return str(d)
