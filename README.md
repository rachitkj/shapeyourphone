# agentic-mobile-os

Your Android phone, shaped by an AI agent. Not a custom ROM, and no root needed.
It runs on the Android you already have, over adb, and **every change can be undone**.

> **Status: v0.1 in progress. Not yet tested on a real phone.** The Python toolkit
> works and is tested against a simulated phone. The launcher app isn't built yet.

## How to use it
1. Install adb (`brew install android-platform-tools`, `winget install Google.PlatformTools`, or `apt install adb`).
2. On the phone, tap Settings → About phone → Build number 7 times, then turn on Developer options → USB debugging. Plug the phone in.
3. Clone this repo, open it in Claude Code, Codex or Gemini CLI, and say: **"Follow PROMPT.md"**.

## What works now (`python3 -m amos …`)
- **Backup first.** `init` saves a full snapshot before any change.
- **Debloat.** `scan` and `plan` use tiered lists for Google, Meta, Samsung, Xiaomi, OPPO/OnePlus/realme, vivo, Motorola and carriers. `apply` runs a plan after the owner approves it.
- **Safety.** Core Android, telephony and stock launchers are never touched. Neither is anything this particular phone depends on: its keyboard, WebView provider, camera, dialer/SMS apps, accessibility services, or the owner's keep list.
- **Privacy.** `privacy` shows which apps can use the camera, mic, location or contacts, plus special access.
- **Tweaks.** Animations, dark mode, font size, screen timeout, ad-blocking Private DNS, per-app notifications and background limits.
- **Undo.** `undo <id>`, `restore` (everything), and a generated `restore.sh` that works without Python.
- **After updates.** `drift` and `reapply` catch changes a system update quietly reverted.
- **Preferences memory.** `devices/<phone>/preferences.md`, which the agent reads before every session and keeps up to date.
- **Launcher control (client side).** `launcher push/pull/rollback/history/preview`, plus a config format with time rules. See `config/examples/`.

## Roadmap to v0.1
- [ ] The launcher app (Kotlin): builds the home screen from a config file and reloads it live
- [ ] Android CI build and signed release APKs
- [ ] Launcher config reference (`docs/launcher-config.md`)
- [ ] Testing on real phones

## Developing
`python3 -m unittest discover -s tests -t tests`. It uses only the standard library and needs Python 3.9+.

MIT licensed.
