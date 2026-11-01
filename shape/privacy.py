"""Who can see what: runtime permissions and special access, in plain words."""

from __future__ import annotations

import re
from typing import Dict, List

from . import probe
from .adb import Device

SENSITIVE = {
    "android.permission.ACCESS_FINE_LOCATION": "precise location",
    "android.permission.ACCESS_COARSE_LOCATION": "approximate location",
    "android.permission.ACCESS_BACKGROUND_LOCATION": "location while not in use",
    "android.permission.CAMERA": "camera",
    "android.permission.RECORD_AUDIO": "microphone",
    "android.permission.READ_CONTACTS": "contacts",
    "android.permission.READ_CALL_LOG": "call history",
    "android.permission.READ_SMS": "text messages",
    "android.permission.RECEIVE_SMS": "incoming texts",
    "android.permission.READ_CALENDAR": "calendar",
    "android.permission.BODY_SENSORS": "body sensors",
    "android.permission.ACTIVITY_RECOGNITION": "physical activity",
    "android.permission.READ_MEDIA_IMAGES": "photos",
    "android.permission.READ_MEDIA_VIDEO": "videos",
    "android.permission.READ_EXTERNAL_STORAGE": "files and media",
    "android.permission.BLUETOOTH_SCAN": "nearby devices",
    "android.permission.NEARBY_WIFI_DEVICES": "nearby Wi-Fi devices",
}

SPECIAL_APPOPS = {
    "SYSTEM_ALERT_WINDOW": "can draw over other apps",
    "GET_USAGE_STATS": "can see which apps you use",
    "REQUEST_INSTALL_PACKAGES": "can install other apps",
    "MANAGE_EXTERNAL_STORAGE": "can read all your files",
}

_PKG_LINE = re.compile(r"^\s*Package \[([^\]]+)\]")
_USER_LINE = re.compile(r"^\s*User (\d+):")
_PERM_LINE = re.compile(r"^\s*([\w.]+): granted=(true|false)")


def granted_runtime_permissions(dump: str, user: str = "0") -> Dict[str, List[str]]:
    """Parse `dumpsys package packages` -> {pkg: [granted sensitive perms]}."""
    result: Dict[str, List[str]] = {}
    pkg, cur_user = None, None
    for line in dump.splitlines():
        m = _PKG_LINE.match(line)
        if m:
            pkg, cur_user = m.group(1), None
            continue
        m = _USER_LINE.match(line)
        if m:
            cur_user = m.group(1)
            continue
        m = _PERM_LINE.match(line)
        if m and pkg and m.group(2) == "true" and m.group(1) in SENSITIVE:
            # runtime perms are listed under "User N:"; install-time ones before it
            if cur_user is None or cur_user == user:
                result.setdefault(pkg, [])
                if m.group(1) not in result[pkg]:
                    result[pkg].append(m.group(1))
    return result


def appop_holders(dev: Device, op: str) -> List[str]:
    out = dev.shell("cmd", "appops", "query-op", "--user", dev.user, op, "allow")
    if "Unknown command" in out or "Error" in out:
        return []
    return sorted({l.strip() for l in out.splitlines() if re.match(r"^\s*[A-Za-z0-9_.]+\s*$", l)})


def audit(dev: Device) -> dict:
    user = dev.user
    states = probe.package_states(dev, user)
    perms = granted_runtime_permissions(dev.shell("dumpsys", "package", "packages", timeout=180), user)
    apps = []
    for pkg, plist in sorted(perms.items()):
        st = states.get(pkg)
        if not st or st["state"] != "enabled":
            continue
        apps.append({
            "pkg": pkg,
            "system": st["system"],
            "access": sorted({SENSITIVE[p] for p in plist}),
            "permissions": sorted(plist),
        })
    # third-party apps first, then by how much they can see
    apps.sort(key=lambda a: (a["system"], -len(a["access"]), a["pkg"]))
    special = {
        "accessibility_services": probe.colon_list_packages(dev.setting("secure", "enabled_accessibility_services")),
        "notification_listeners": probe.colon_list_packages(dev.setting("secure", "enabled_notification_listeners")),
        "device_admins": probe.device_admins(dev),
    }
    for op, desc in SPECIAL_APPOPS.items():
        holders = [p for p in appop_holders(dev, op) if not states.get(p, {}).get("system")]
        special[op.lower()] = holders
    network = {
        "private_dns_mode": dev.setting("global", "private_dns_mode") or "default",
        "private_dns_host": dev.setting("global", "private_dns_specifier"),
    }
    return {"apps": apps, "special_access": special, "network": network,
            "notes": {
                "special_access": "Accessibility services and notification listeners can read what is on screen / in notifications. Each one should be something the owner recognises.",
                "fix": "Revoke with: python3 -m shape perm revoke <pkg> <permission>",
            }}
