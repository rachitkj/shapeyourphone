"""Decide whether a package may be disabled or removed on this phone.

Two layers:
  * static: shape/data/protected.json (core Android, telephony, stock launchers, OEM bootloop list)
  * dynamic: what *this* phone depends on right now — the active keyboard, the
    WebView provider, the default dialer/SMS/home apps, accessibility services
    the owner switched on, device admins — plus the owner's keep list.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Dict, Optional, Tuple

from . import probe
from .adb import Device
from .state import DATA_DIR


@lru_cache(maxsize=1)
def _static() -> Tuple[Dict[str, str], Dict[str, str]]:
    with open(DATA_DIR / "protected.json") as f:
        data = json.load(f)
    return data["packages"], data["prefixes"]


def static_reason(pkg: str) -> Optional[str]:
    pkgs, prefixes = _static()
    if pkg in pkgs:
        return pkgs[pkg]
    for pre, why in prefixes.items():
        if pkg.startswith(pre):
            return why
    return None


class Guard:
    def __init__(self, dev: Optional[Device] = None, keep: Optional[list] = None):
        self.dynamic: Dict[str, str] = {}
        for p in keep or []:
            self.dynamic[p] = "you asked to keep this"
        if dev is not None:
            self._load_dynamic(dev)

    def _load_dynamic(self, dev: Device) -> None:
        def add(pkg: Optional[str], why: str) -> None:
            if pkg and pkg not in self.dynamic:
                self.dynamic[pkg] = why

        add(probe.default_ime_package(dev), "your current keyboard")
        add(probe.webview_provider(dev), "renders web pages inside your apps (WebView provider)")
        home = probe.current_home(dev)
        add(home.split("/")[0] if home else None, "your current home screen")
        add(probe.camera_package(dev), "your camera app")
        for p in probe.role_holders(dev, "android.app.role.DIALER"):
            add(p, "your default phone app")
        for p in probe.role_holders(dev, "android.app.role.SMS"):
            add(p, "your default messaging app")
        for p in probe.colon_list_packages(dev.setting("secure", "enabled_accessibility_services")):
            add(p, "an accessibility service you turned on")
        for p in probe.colon_list_packages(dev.setting("secure", "enabled_input_methods")):
            add(p, "a keyboard you have enabled")
        for p in probe.device_admins(dev):
            add(p, "a device admin app (security/work/anti-theft)")

    def check(self, pkg: str) -> Tuple[bool, str]:
        """(allowed, reason-if-blocked)"""
        why = static_reason(pkg)
        if why:
            return False, why
        if pkg in self.dynamic:
            return False, self.dynamic[pkg]
        return True, ""
