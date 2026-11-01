"""Thin, testable wrapper around the adb binary.

Every device interaction goes through `Device.shell()` so tests can swap in a
fake runner (see tests/fakephone.py) and nothing touches a real phone.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Tuple

# runner(argv, timeout, stdin_bytes) -> (returncode, stdout, stderr)
Runner = Callable[[List[str], int, Optional[bytes]], Tuple[int, str, str]]


class AdbError(RuntimeError):
    pass


INSTALL_HELP = """adb (Android platform-tools) is not installed.
  macOS:   brew install android-platform-tools
  Windows: winget install Google.PlatformTools
  Linux:   sudo apt install adb   (or your distro's android-tools package)
  Any OS:  https://developer.android.com/tools/releases/platform-tools
Or point AMOS_ADB at an adb binary."""


def find_adb() -> str:
    env = os.environ.get("AMOS_ADB")
    if env:
        return env
    found = shutil.which("adb")
    if found:
        return found
    home = Path.home()
    candidates = [
        home / "Library/Android/sdk/platform-tools/adb",
        home / "Android/Sdk/platform-tools/adb",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android/Sdk/platform-tools/adb.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    raise AdbError(INSTALL_HELP)


def _subprocess_runner(argv: List[str], timeout: int, stdin: Optional[bytes]) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(argv, input=stdin, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AdbError("adb timed out after %ss: %s" % (timeout, " ".join(argv[:6])))
    return (
        p.returncode,
        p.stdout.decode("utf-8", "replace"),
        p.stderr.decode("utf-8", "replace"),
    )


def quote(argv) -> str:
    """Quote an argv list into one string for the device's /system/bin/sh."""
    return " ".join(shlex.quote(str(a)) for a in argv)


class Device:
    def __init__(self, serial: Optional[str], runner: Optional[Runner] = None, adb: Optional[str] = None):
        self.serial = serial
        self._runner = runner or _subprocess_runner
        self._adb = adb if adb is not None else (None if runner else find_adb())
        self._props: Optional[dict] = None

    # -- raw ---------------------------------------------------------------
    def adb(self, *args: str, timeout: int = 120, stdin: Optional[bytes] = None) -> Tuple[int, str, str]:
        argv = [self._adb or "adb"]
        if self.serial:
            argv += ["-s", self.serial]
        argv += list(args)
        return self._runner(argv, timeout, stdin)

    def sh(self, command: str, timeout: int = 60, check: bool = False) -> str:
        """Run a pre-quoted command string in the device shell; return stdout (stripped)."""
        rc, out, err = self.adb("shell", command, timeout=timeout)
        if check and rc != 0:
            raise AdbError("device command failed (%s): %s\n%s" % (rc, command, (err or out).strip()))
        return out.replace("\r\n", "\n").strip()

    def shell(self, *argv: str, timeout: int = 60, check: bool = False) -> str:
        return self.sh(quote(argv), timeout=timeout, check=check)

    # -- convenience -------------------------------------------------------
    def props(self) -> dict:
        if self._props is None:
            out = self.sh("getprop")
            props = {}
            for m in re.finditer(r"^\[([^\]]+)\]: \[(.*)\]$", out, re.M):
                props[m.group(1)] = m.group(2)
            self._props = props
        return self._props

    def prop(self, name: str, default: str = "") -> str:
        return self.props().get(name, default)

    @property
    def sdk(self) -> int:
        try:
            return int(self.prop("ro.build.version.sdk", "0"))
        except ValueError:
            return 0

    @property
    def user(self) -> str:
        """The Android user id the phone's owner is using (almost always 0)."""
        out = self.shell("am", "get-current-user")
        return out.strip() if out.strip().isdigit() else "0"

    def setting(self, namespace: str, key: str) -> Optional[str]:
        v = self.shell("settings", "get", namespace, key)
        return None if v in ("", "null") else v


def list_devices(runner: Optional[Runner] = None) -> List[dict]:
    """Parse `adb devices -l`."""
    runner = runner or _subprocess_runner
    adb = None if runner is not _subprocess_runner else find_adb()
    rc, out, err = runner([adb or "adb", "devices", "-l"], 30, None)
    devices = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        info = {"serial": parts[0], "state": parts[1] if len(parts) > 1 else "unknown"}
        for p in parts[2:]:
            if ":" in p:
                k, v = p.split(":", 1)
                info[k] = v
        devices.append(info)
    return devices


def pick_device(serial: Optional[str] = None, runner: Optional[Runner] = None) -> Device:
    serial = serial or os.environ.get("AMOS_DEVICE")
    devices = list_devices(runner)
    ready = [d for d in devices if d["state"] == "device"]
    if serial:
        match = [d for d in devices if d["serial"] == serial]
        if not match:
            raise AdbError("Device %s is not connected. Connected: %s" % (serial, ", ".join(d["serial"] for d in devices) or "none"))
        if match[0]["state"] != "device":
            raise AdbError(_state_help(match[0]))
        return Device(serial, runner=runner)
    if not devices:
        raise AdbError(
            "No phone found. Connect it by USB with USB debugging on, or use Wireless debugging:\n"
            "  python3 -m amos pair <ip:port> <code>   then   python3 -m amos connect <ip:port>"
        )
    if not ready:
        raise AdbError(_state_help(devices[0]))
    if len(ready) > 1:
        raise AdbError(
            "More than one phone is connected (%s). Pick one with --device SERIAL." % ", ".join(d["serial"] for d in ready)
        )
    return Device(ready[0]["serial"], runner=runner)


def _state_help(d: dict) -> str:
    if d["state"] == "unauthorized":
        return "Phone %s is connected but not authorized. Unlock it and tap 'Allow' on the USB debugging prompt (tick 'Always allow')." % d["serial"]
    if d["state"] == "offline":
        return "Phone %s is offline. Unplug and replug it, or toggle USB debugging off and on." % d["serial"]
    return "Phone %s is in state '%s'." % (d["serial"], d["state"])
