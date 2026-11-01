"""MCP server for shapeyourphone (stdio, JSON-RPC 2.0, no dependencies).

Lets Claude Desktop or any MCP client drive a phone through tools instead of a
shell. Every tool wraps a `shape` CLI command, so the safety guard, change log
and undo apply exactly as on the command line.

Tools that change the phone take `owner_approved`. Called without it they
return a preview (the plan / the diff) and change nothing; call again with
`owner_approved: true` only after the phone's owner has agreed.

Claude Desktop config:
  {"mcpServers": {"shapeyourphone": {"command": "shape-mcp"}}}
or, from a clone:
  {"mcpServers": {"shapeyourphone": {"command": "python3", "args": ["-m", "shape.mcp"],
                                      "env": {"PYTHONPATH": "/path/to/shapeyourphone"}}}}
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from typing import Any, Callable, Dict, List, Optional

from . import __version__
from . import cli
from .state import DATA_DIR

KNOWN_PROTOCOLS = ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"]

INSTRUCTIONS = """shapeyourphone changes a real Android phone over adb. Before anything else in a new
session, call the `playbook` tool and follow it. Hard rules: change the phone only through
these tools; never set owner_approved=true until the phone's owner has seen the preview and
said yes; never try to work around a BLOCKED package; keep the owner's preferences file
current with `preferences_write`."""

APPROVAL = {"type": "boolean", "description": "true only after the phone's owner saw the preview and agreed. Omit to get a preview."}
DEVICE = {"type": "string", "description": "adb serial, only needed when several phones are connected"}
APPS = {"type": "array", "items": {"type": "string"}, "description": "app names as the owner says them ('Instagram'), packages, or @dialer/@sms/@browser/@camera/@settings"}


def _tmp_json(obj: Any) -> str:
    fd, path = tempfile.mkstemp(suffix=".json", prefix="shape-mcp-")
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, indent=2)
    return path


def _yes(a: dict) -> List[str]:
    return ["--yes"] if a.get("owner_approved") is True else []


class Tool:
    def __init__(self, name: str, description: str, props: Dict[str, dict], argv: Callable[[dict], List[str]],
                 required: Optional[List[str]] = None, read_only: bool = False, approval: bool = False,
                 destructive: bool = False):
        self.name, self.description, self.argv = name, description, argv
        self.read_only, self.approval = read_only, approval
        props = dict(props)
        if approval:
            props["owner_approved"] = APPROVAL
        props["device"] = DEVICE
        self.schema = {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}
        self.annotations = {"readOnlyHint": read_only, "destructiveHint": destructive, "openWorldHint": False}

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "inputSchema": self.schema, "annotations": self.annotations}


def _edit_argv(a: dict) -> List[str]:
    return ["launcher", a["command"], *a.get("args", [])] + _yes(a)


TOOLS: List[Tool] = [
    Tool("playbook", "Read this first: how to run a session with the phone's owner, and the safety rules.", {}, lambda a: [], read_only=True),
    Tool("doctor", "Check adb, the connected phone and the Shape launcher.", {}, lambda a: ["doctor"], read_only=True),
    Tool("phones", "Phones already set up on this computer.", {}, lambda a: ["phones"], read_only=True),
    Tool("init", "First step with a new phone: save its profile and a full backup, create its preferences file.", {}, lambda a: ["init"]),
    Tool("scan", "Find bloat (tiered safe/recommended/optional, with what each loses) and unknown preinstalled apps.",
         {}, lambda a: ["scan"], read_only=True),
    Tool("privacy", "Which apps can use location, camera, mic, contacts; accessibility services, device admins.",
         {"include_system": {"type": "boolean"}}, lambda a: ["privacy"] + (["--all"] if a.get("include_system") else []), read_only=True),
    Tool("plan_debloat", "Write a reviewable debloat plan file. Show it to the owner, then apply_plan.",
         {"tier": {"type": "string", "enum": ["safe", "recommended", "all"]},
          "include": {"type": "array", "items": {"type": "string"}}, "exclude": {"type": "array", "items": {"type": "string"}},
          "method": {"type": "string", "enum": ["disable", "remove"]}},
         lambda a: ["plan", "--tier", a.get("tier", "recommended"), "--method", a.get("method", "disable")]
         + (["--include", *a["include"]] if a.get("include") else []) + (["--exclude", *a["exclude"]] if a.get("exclude") else [])),
    Tool("apply_plan", "Apply a plan file (from plan_debloat or clone). Every change is logged with its undo.",
         {"plan_path": {"type": "string"}}, lambda a: ["apply", a["plan_path"]] + _yes(a), required=["plan_path"], approval=True),
    Tool("tweak", "Named reversible tweak: animations <scale>, dark-mode yes|no|auto, font-scale <x>, screen-timeout <s>, "
                  "private-dns adguard|mullvad|cloudflare|cloudflare-family|quad9|<host>|off, restrict-background <pkg>, "
                  "notifications-off <pkg>, notifications-on <pkg>.",
         {"name": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}}},
         lambda a: ["tweak", a["name"], *a.get("args", [])] + _yes(a), required=["name"], approval=True),
    Tool("change_permission", "Grant or revoke one app permission (e.g. android.permission.CAMERA).",
         {"action": {"type": "string", "enum": ["grant", "revoke"]}, "package": {"type": "string"}, "permission": {"type": "string"}},
         lambda a: ["perm", a["action"], a["package"], a["permission"]] + _yes(a), required=["action", "package", "permission"], approval=True),
    Tool("change_packages", "Disable, remove (for this user, reversible) or re-enable specific packages.",
         {"action": {"type": "string", "enum": ["disable", "remove", "enable"]}, "packages": {"type": "array", "items": {"type": "string"}}},
         lambda a: ["pkg", a["action"], *a["packages"]] + _yes(a), required=["action", "packages"], approval=True, destructive=True),
    Tool("keep_packages", "Record packages the owner never wants touched (or remove them from that list).",
         {"packages": {"type": "array", "items": {"type": "string"}}, "remove": {"type": "boolean"}},
         lambda a: ["keep", *a["packages"]] + (["--remove"] if a.get("remove") else []), required=["packages"]),
    Tool("list_changes", "Every change made to this phone, with ids for undo.", {"include_undone": {"type": "boolean"}},
         lambda a: ["changes"] + (["--all"] if a.get("include_undone") else []), read_only=True),
    Tool("undo", "Undo specific changes by id, or the last N.",
         {"ids": {"type": "array", "items": {"type": "integer"}}, "last": {"type": "integer"}},
         lambda a: (["undo", *[str(i) for i in a.get("ids", [])]] + (["--last", str(a["last"])] if a.get("last") else []))
         if a.get("owner_approved") is True else ["changes"], approval=True),
    Tool("restore_everything", "Undo every change, newest first (also hands the home screen back and removes Shape).",
         {}, lambda a: ["restore"] + _yes(a), approval=True, destructive=True),
    Tool("drift", "Changes the phone has reverted on its own, e.g. after a system update.", {}, lambda a: ["drift"], read_only=True),
    Tool("reapply", "Re-apply drifted changes.", {}, lambda a: ["reapply"] + _yes(a), approval=True),
    Tool("report", "Before/after summary. share=true gives anonymous markdown for a GitHub device report.",
         {"share": {"type": "boolean"}}, lambda a: ["report"] + (["--share"] if a.get("share") else []), read_only=True),
    Tool("preferences_read", "The owner's preferences file (their wishes in plain words). Read it at the start of every session.",
         {}, lambda a: ["prefs"], read_only=True),
    Tool("preferences_write", "Replace the owner's preferences file with updated markdown. Keep their words; add, don't erase.",
         {"content": {"type": "string"}}, lambda a: [], required=["content"]),
    Tool("suggest", "Suggestions from real usage (most-used apps not in reach, heavy use, unused apps). Changes nothing.",
         {"days": {"type": "integer"}}, lambda a: ["suggest", "--days", str(a.get("days", 30))], read_only=True),
    Tool("clone", "Set this phone up like another saved phone (see `phones`): same changes, notes, keep list and home screen.",
         {"from": {"type": "string"}}, lambda a: ["clone", "--from", a["from"]] + _yes(a), required=["from"], approval=True),
    Tool("launcher_install", "Install the Shape launcher and make it the home screen (the old launcher stays installed).",
         {}, lambda a: ["launcher", "install"] if a.get("owner_approved") is True else ["launcher", "status"], approval=True),
    Tool("launcher_status", "Launcher version, whether it's the home screen, active rules.", {}, lambda a: ["launcher", "status"], read_only=True),
    Tool("launcher_apps", "Installed apps: name → package.", {}, lambda a: ["launcher", "apps"], read_only=True),
    Tool("launcher_get_config", "The home-screen config currently on the phone (JSON). Format: docs/launcher-config.md.",
         {}, lambda a: ["launcher", "pull"], read_only=True),
    Tool("launcher_set_config", "Replace the whole home-screen config (validated first; preview shows a summary).",
         {"config": {"type": "object"}}, lambda a: ["launcher", "push", _tmp_json(a["config"])] + _yes(a), required=["config"], approval=True),
    Tool("launcher_edit", "Small home-screen edits by app name. command + args mirror the CLI, e.g. "
                          "hide ['Instagram','--days','weekdays','--from','09:00','--to','18:00'] · unhide ['Instagram'] · "
                          "search-only ['TikTok'] · dock ['WhatsApp','Spotify'] · home-apps ['Maps','--style','grid'] · "
                          "theme ['--icons','grayscale','--background','wallpaper'] · gesture ['doubleTap','Spotify'] · "
                          "rename ['WhatsApp','Chats'] · pause ['Instagram','--seconds','10'] · rule-remove ['Night'] · usage-access [].",
         {"command": {"type": "string", "enum": ["hide", "unhide", "search-only", "dock", "home-apps", "theme", "gesture",
                                                 "rename", "pause", "rule-remove", "usage-access"]},
          "args": {"type": "array", "items": {"type": "string"}}},
         _edit_argv, required=["command"], approval=True),
    Tool("launcher_rules", "Time rules on the home screen (● = active now).", {}, lambda a: ["launcher", "rules"], read_only=True),
    Tool("launcher_preview", "What a config would look like at a given time, e.g. at='fri 22:30'. Changes nothing.",
         {"config": {"type": "object"}, "at": {"type": "string"}},
         lambda a: ["launcher", "preview", _tmp_json(a["config"])] + (["--at", a["at"]] if a.get("at") else []), required=["config"], read_only=True),
    Tool("launcher_history", "Every home-screen config pushed to this phone.", {}, lambda a: ["launcher", "history"], read_only=True),
    Tool("launcher_rollback", "Go back to an earlier home screen (default: the previous one).",
         {"to": {"type": "string"}}, lambda a: (["launcher", "rollback"] + ([a["to"]] if a.get("to") else []))
         if a.get("owner_approved") is True else ["launcher", "history"], approval=True),
    Tool("launcher_uninstall", "Give the home screen back to the previous launcher and remove Shape.",
         {}, lambda a: ["launcher", "uninstall"] + _yes(a), approval=True, destructive=True),
]
BY_NAME = {t.name: t for t in TOOLS}


def playbook_text() -> str:
    text = (DATA_DIR / "playbook.md").read_text()
    return ("You are connected through MCP: every `shape <command>` in this playbook is one of your tools "
            "(e.g. `shape scan` → scan, `shape launcher hide` → launcher_edit). Never run shell commands on the phone.\n\n" + text)


def run_tool(name: str, args: dict) -> dict:
    tool = BY_NAME.get(name)
    if tool is None:
        raise KeyError(name)
    if name == "playbook":
        return {"content": [{"type": "text", "text": playbook_text()}], "isError": False}
    argv = ["--device", args["device"]] if args.get("device") else []
    out = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        old_stdin = sys.stdin
        sys.stdin = io.StringIO("")  # never let a confirm() prompt read the JSON-RPC stream
        try:
            if name == "preferences_write":
                code = _write_prefs(args)
            else:
                code = cli.main(argv + tool.argv(args))
        except SystemExit as e:  # argparse usage errors
            code = e.code if isinstance(e.code, int) else 2
        finally:
            sys.stdin = old_stdin
    text = out.getvalue().strip() or "(no output)"
    pending = tool.approval and args.get("owner_approved") is not True
    if pending:
        text += "\n\n[preview only — nothing was changed. Show this to the owner; call again with owner_approved=true if they agree.]"
    return {"content": [{"type": "text", "text": text}], "isError": code not in (0, 2)}


def _write_prefs(args: dict) -> int:
    dev = cli.get_dev(argparse_namespace(args))
    ps = cli.ensure_init(dev, quiet=True)
    ps.path("preferences.md").write_text(args["content"].rstrip() + "\n")
    print("Saved %s" % ps.path("preferences.md"))
    return 0


def argparse_namespace(args: dict):
    import argparse
    return argparse.Namespace(device=args.get("device"))


def handle(msg: dict) -> Optional[dict]:
    """One JSON-RPC message in, one response out (None for notifications)."""
    mid = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params") or {}

    def ok(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    if mid is None:  # notification (e.g. notifications/initialized)
        return None
    if method == "initialize":
        asked = params.get("protocolVersion", KNOWN_PROTOCOLS[-1])
        return ok({
            "protocolVersion": asked if asked in KNOWN_PROTOCOLS else KNOWN_PROTOCOLS[-1],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "shapeyourphone", "version": __version__},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [t.spec() for t in TOOLS]})
    if method == "tools/call":
        name = params.get("name", "")
        if name not in BY_NAME:
            return err(-32602, "unknown tool: %s" % name)
        args = params.get("arguments") or {}
        missing = [r for r in BY_NAME[name].schema["required"] if r not in args]
        if missing:
            return err(-32602, "missing argument(s): %s" % ", ".join(missing))
        try:
            return ok(run_tool(name, args))
        except Exception as e:  # noqa: BLE001 — report tool failures to the client, keep serving
            return ok({"content": [{"type": "text", "text": "error: %s" % e}], "isError": True})
    return err(-32601, "method not found: %s" % method)


def main() -> None:
    # MCP messages are UTF-8 regardless of the OS console encoding
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", newline="\n" if stream is sys.stdout else None)
    print("shapeyourphone MCP server %s on stdio" % __version__, file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error: %s" % e}}
        else:
            resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
