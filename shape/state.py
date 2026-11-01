"""Where per-phone state lives on the computer.

devices/<key>/
  profile.json        model, Android version, OEM skin
  preferences.md      what the owner wants, in their words (agent keeps it current)
  keep.json           packages the owner said never to touch
  changes.json        every change made, with the command that undoes it
  snapshots/<ts>/     full backup taken before the first change
  plans/<ts>-*.json   proposed changes waiting for approval
  launcher/           current.json + history/ of every pushed home-screen config
  restore.sh          generated: undo everything without Python
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .adb import Device

REPO_ROOT = Path(__file__).resolve().parent.parent


def shape_home() -> Path:
    return Path(os.environ.get("SHAPE_HOME") or (REPO_ROOT / "devices"))


def now_ts() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "phone"


def device_key(dev: Device) -> str:
    ident = dev.prop("ro.serialno") or ""
    if not ident or ident.lower() == "unknown":
        ident = dev.setting("secure", "android_id") or dev.serial or "unknown"
    h = hashlib.sha1(ident.encode()).hexdigest()[:6]
    name = "%s-%s" % (dev.prop("ro.product.manufacturer", "android"), dev.prop("ro.product.model", "phone"))
    return "%s-%s" % (slug(name), h)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


class PhoneState:
    """Filesystem view of one phone's data."""

    def __init__(self, dev: Device, root: Path | None = None):
        self.dev = dev
        self.key = device_key(dev)
        self.dir = (root or shape_home()) / self.key

    @property
    def exists(self) -> bool:
        return (self.dir / "profile.json").exists()

    def path(self, *parts: str) -> Path:
        return self.dir.joinpath(*parts)

    # profile
    def profile(self) -> dict:
        return read_json(self.path("profile.json"), {}) or {}

    # keep list (owner said: never touch)
    def keep(self) -> list:
        return read_json(self.path("keep.json"), []) or []

    def set_keep(self, pkgs: list) -> None:
        write_json(self.path("keep.json"), sorted(set(pkgs)))

    def latest_snapshot(self) -> Path | None:
        snaps = sorted(self.path("snapshots").glob("*")) if self.path("snapshots").exists() else []
        return snaps[-1] if snaps else None

    def first_snapshot(self) -> Path | None:
        snaps = sorted(self.path("snapshots").glob("*")) if self.path("snapshots").exists() else []
        return snaps[0] if snaps else None


PREFERENCES_TEMPLATE = """# Preferences — {model}

<!--
The agent reads this file before every change and updates it whenever you say
how you want your phone to be. You can edit it by hand too. Plain words are fine.
-->

## About me and how I use my phone
-

## Look and feel
<!-- e.g. dark, minimal, text-only, big clock, icons in grayscale -->
-

## Apps
- Use every day:
- Keep, but out of sight:
- Never touch (also recorded in keep.json):

## Distractions and focus
<!-- e.g. hide social apps after 22:00 on weekdays -->
-

## Said no to
<!-- suggestions the owner declined, so the agent doesn't repeat them -->
-

## History
<!-- one line per session: date — what changed -->
"""
