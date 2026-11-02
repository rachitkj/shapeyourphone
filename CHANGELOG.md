# Changelog

## 0.1.0 — 2026-11-02

First public version. Tested end to end on Android 8, 11, 14 and 16
emulators in CI. **Not yet tested on physical phones.** Device reports are very welcome.

**Agent toolkit (`shape`)**
- Backup before the first change; every change is verified on the phone and logged with its undo. `undo`, `restore`, plus generated `restore.sh` / `restore.ps1` that need no Python.
- Tiered bloat lists (Google, Meta and partners, Samsung, Xiaomi, OPPO/OnePlus/realme, vivo, Motorola, carriers). Each entry says in plain words what you'd lose.
- Safety guard: core Android, telephony, stock launchers and known bootloop packages are never touched, nor is anything this particular phone depends on (keyboard, WebView, camera, dialer/SMS, accessibility tools, device admins, the owner's keep list).
- Privacy audit, named tweaks (animations, dark mode, font size, screen timeout, ad-blocking Private DNS, per-app notifications and background limits).
- `drift` / `reapply` after system updates; `clone` to set up a new phone like an old one.
- `suggest` from real usage stats; `report --share` for anonymous device reports.
- Preferences memory: `preferences.md` per phone, kept current by the agent.
- `pipx install`, and an MCP server (`shape-mcp`) for Claude Desktop and other MCP clients.

**Shape launcher**
- The whole home screen is drawn from one JSON config the agent pushes live, with no reinstall, plus history and rollback.
- Widgets: clock, text, app list/grid/row, search, next calendar event. Dock, drawer with hidden and search-only apps, gestures.
- Time rules ("hide Instagram on weekdays 9–18"), a pause screen before distracting apps, themed mono icons.
- Name-based edits: `shape launcher hide Instagram --from 22:00 --to 07:00`.
- Control channel restricted to adb; no AndroidX or other dependencies; Android 8+.
