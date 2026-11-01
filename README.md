# agentic-mobile-os

Your Android phone, shaped by an AI agent. Not a custom ROM, and no root needed.
It runs on the Android you already have, over adb, and **every change can be undone**.

You tell your coding agent (Claude Code, Codex, Gemini CLI…) how you want your
phone. It cleans out bloat, tightens privacy, tunes settings, and designs your
home screen. It remembers what you asked for, so the next request builds on the
last one instead of starting over.

> **Status: v0.1, not yet tested on a real phone.** The Python toolkit is
> tested against a simulated phone, and the launcher is built, linted and
> unit-tested in CI. Real-device reports are very welcome. See CONTRIBUTING.

## How to use it
1. Install adb (`brew install android-platform-tools`, `winget install Google.PlatformTools`, or `apt install adb`) and Python 3.9+.
2. On the phone, tap Settings → About phone → Build number 7 times, then turn on Developer options → USB debugging. Plug the phone in and tap Allow.
3. Clone this repo, open it in your coding agent, and say: **"Follow PROMPT.md"**.

Or drive it yourself: `python3 -m amos --help`.

## What it does

**Cleanup and privacy**
- `init` saves a full backup before anything changes.
- `scan` and `plan` use tiered bloat lists (safe / recommended / optional) for Google, Meta, Samsung, Xiaomi, OPPO/OnePlus/realme, vivo, Motorola and carriers. Each entry says in plain words what you'd lose.
- `privacy` shows who can use your camera, mic, location and contacts, plus accessibility services, notification readers and device admins.
- `tweak` covers animations, dark mode, font size, screen timeout, ad-blocking Private DNS, per-app notifications and background limits.

**A home screen that rebuilds itself to your taste** ([config reference](docs/launcher-config.md))
- A tiny launcher with no dependencies. Everything about it comes from one JSON file the agent writes: theme, widgets (clock, apps, search, next calendar event), dock, drawer and gestures.
- `launcher push` changes the home screen live, with no reinstall. Every version is kept, so `launcher rollback` always works.
- Time rules, e.g. "hide Instagram on weekdays 9–18" or "a calm evening layout". Apps can be hidden entirely or made *search-only*.
- The launcher only accepts commands from adb, so other apps on the phone can't change it.

**Safety and memory**
- It never touches core Android, telephony, the stock launcher (which also provides recents and gestures), or packages known to bootloop. It also protects whatever *this* phone depends on: its keyboard, WebView provider, camera, dialer and SMS apps, accessibility tools, device admins, and anything you said to keep.
- Every change is checked on the phone and logged with its undo. Use `undo <id>`, `restore` for everything, or the generated `restore.sh`, which needs no Python.
- `drift` and `reapply` catch changes a system update quietly reverted.
- `devices/<phone>/preferences.md` is your wishes in plain words. The agent reads it before every session and keeps it current. It stays on your computer and is never committed.

## What it can't do (without root)
It can't change the status bar, quick settings or lock screen, and it can't remove Google Play services. On Fire OS and some OEM skins, a third-party launcher can't become the home screen.

## Layout
```
amos/          Python toolkit (stdlib only)        PROMPT.md   the agent's playbook
data/          bloat lists + protected packages    docs/       launcher config reference
launcher/      Android launcher (Kotlin)           config/     default + example home screens
tests/         fake-phone tests + shared vectors   scripts/    release signing setup
```

## Developing
- Python: `python3 -m unittest discover -s tests -t tests`
- Launcher: `cd launcher && ./gradlew testDebugUnitTest assembleDebug` (JDK 17+ and the Android SDK)
- Releases: run `scripts/make-release-key.sh` once, then `git tag v0.1.0 && git push origin v0.1.0`. CI builds a signed `amos-launcher.apk`, and `amos launcher install` downloads it.

Inspired by [cleanyourtv](https://github.com/Gathin23/cleanyourtv). MIT licensed.
