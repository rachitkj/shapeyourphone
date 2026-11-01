"""Named, reversible system tweaks. Each expands to plan actions."""

from __future__ import annotations

from typing import List

from .adb import Device

PRIVATE_DNS_PRESETS = {
    "adguard": ("dns.adguard-dns.com", "Blocks ads and trackers (AdGuard)"),
    "mullvad": ("adblock.dns.mullvad.net", "Blocks ads and trackers (Mullvad)"),
    "cloudflare": ("one.one.one.one", "Fast and private, no blocking (Cloudflare)"),
    "cloudflare-family": ("family.cloudflare-dns.com", "Blocks malware and adult content (Cloudflare)"),
    "quad9": ("dns.quad9.net", "Blocks malware domains (Quad9)"),
}

TWEAKS = {
    "animations": "animations <scale>          0 = off, 0.5 = snappy, 1 = default",
    "dark-mode": "dark-mode <yes|no|auto>",
    "font-scale": "font-scale <factor>         e.g. 0.9, 1.0, 1.15, 1.3",
    "screen-timeout": "screen-timeout <seconds>",
    "private-dns": "private-dns <adguard|mullvad|cloudflare|cloudflare-family|quad9|HOSTNAME|off>",
    "restrict-background": "restrict-background <pkg>  stop an app running in the background",
    "notifications-off": "notifications-off <pkg>    block an app's notifications",
    "notifications-on": "notifications-on <pkg>",
}


def actions_for(dev: Device, name: str, args: List[str]) -> List[dict]:
    def need(n: int) -> None:
        if len(args) < n:
            raise ValueError("usage: shape tweak " + TWEAKS.get(name, name))

    if name == "animations":
        need(1)
        scale = str(float(args[0])).rstrip("0").rstrip(".") if float(args[0]) != 0 else "0"
        why = "Animation speed %sx" % scale
        return [{"op": "setting", "ns": "global", "key": k, "value": scale, "why": why}
                for k in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale")]
    if name == "dark-mode":
        need(1)
        if args[0] not in ("yes", "no", "auto"):
            raise ValueError("dark-mode takes yes, no or auto")
        return [{"op": "nightmode", "mode": args[0], "why": "Dark mode: %s" % args[0]}]
    if name == "font-scale":
        need(1)
        f = float(args[0])
        if not 0.7 <= f <= 2.0:
            raise ValueError("font scale should be between 0.7 and 2.0")
        return [{"op": "setting", "ns": "system", "key": "font_scale", "value": str(f), "why": "Text size %sx" % f}]
    if name == "screen-timeout":
        need(1)
        ms = int(float(args[0]) * 1000)
        if ms < 10000:
            raise ValueError("screen timeout under 10 seconds is not useful")
        return [{"op": "setting", "ns": "system", "key": "screen_off_timeout", "value": str(ms),
                 "why": "Screen turns off after %ss" % args[0]}]
    if name == "private-dns":
        need(1)
        v = args[0]
        if v == "off":
            return [{"op": "setting", "ns": "global", "key": "private_dns_mode", "value": "off", "why": "Private DNS off"}]
        host, why = PRIVATE_DNS_PRESETS.get(v, (v, "Private DNS via %s" % v))
        if "." not in host:
            raise ValueError("private-dns needs a preset name or a hostname like dns.example.com")
        return [
            {"op": "setting", "ns": "global", "key": "private_dns_specifier", "value": host, "why": why},
            {"op": "setting", "ns": "global", "key": "private_dns_mode", "value": "hostname", "why": why},
        ]
    if name == "restrict-background":
        need(1)
        pkg = args[0]
        return [
            {"op": "appop", "pkg": pkg, "appop": "RUN_ANY_IN_BACKGROUND", "mode": "ignore", "why": "Stop %s running in the background" % pkg},
            {"op": "standby", "pkg": pkg, "bucket": "restricted", "why": "Put %s in the restricted battery bucket" % pkg},
        ]
    if name in ("notifications-off", "notifications-on"):
        need(1)
        pkg, off = args[0], name.endswith("off")
        why = "%s notifications from %s" % ("Block" if off else "Allow", pkg)
        if dev.sdk >= 33:
            return [{"op": "perm-revoke" if off else "perm-grant", "pkg": pkg,
                     "perm": "android.permission.POST_NOTIFICATIONS", "why": why}]
        return [{"op": "appop", "pkg": pkg, "appop": "POST_NOTIFICATION", "mode": "ignore" if off else "allow", "why": why}]
    raise ValueError("unknown tweak %r. Available:\n  %s" % (name, "\n  ".join(TWEAKS.values())))
