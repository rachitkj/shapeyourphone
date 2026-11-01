# Launcher config reference (v1)

The amos launcher draws its whole home screen from one JSON file. The agent
edits it, checks it with `amos launcher validate`, previews it with
`amos launcher preview --at "fri 22:30"`, and sends it with
`amos launcher push`. The phone redraws immediately, with no reinstall. Every
pushed version is kept, so `amos launcher rollback` always works.

Examples: [`config/default.json`](../config/default.json) and
[`config/examples/`](../config/examples).

## Top level

| key | type | default | notes |
|---|---|---|---|
| `version` | `1` | required | |
| `name` | string | | Shown in `amos launcher history`. |
| `theme` | object | see below | |
| `home` | list of widgets | clock + spacer | Drawn top to bottom. |
| `dock` | object | dialer, SMS, browser, camera | Row of apps at the bottom. |
| `drawer` | object | see below | Full app list (swipe up). |
| `labels` | `{package: "Name"}` | `{}` | Rename apps everywhere. |
| `gestures` | object | see below | |
| `rules` | list | `[]` | Time-based changes. |

## App references
Wherever an app is expected you can use:
- a package name: `"com.whatsapp"`
- a specific activity: `"com.whatsapp/.Main"`
- the phone's default app for a role: `"@dialer"`, `"@sms"`, `"@browser"`, `"@camera"`, `"@settings"`

Use `amos launcher apps` to list installed apps with their names. Apps that
aren't installed are skipped quietly, and the validator warns about them.

## `theme`

| key | values | default |
|---|---|---|
| `background` | `#RGB`, `#RRGGBB`, `#AARRGGBB`, or `"wallpaper"` | `#0B0B0C` |
| `dim` | 0–1, darkens the wallpaper | `0.25` |
| `foreground` / `secondary` / `accent` | colors | `#F2F2F2` / `#8A8A8E` / `#7CC4FF` |
| `font` | `sans`, `light`, `thin`, `medium`, `condensed`, `serif`, `mono` | `sans` |
| `textSize` | 10–40 (sp) | `18` |
| `iconStyle` | `color`, `mono` (themed icons on Android 13+, otherwise grayscale), `grayscale`, `none` (text only) | `color` |
| `iconSize` | 16–96 (dp) | `40` |
| `padding` | 0–64 (dp) | `24` |

## Widgets (`home`)

| type | keys |
|---|---|
| `clock` | `format` (e.g. `"HH:mm"`, `"h:mm"`), `size`, `showDate`, `dateFormat` (e.g. `"EEEE d MMMM"`), `align` |
| `text` | `text` (required), `size`, `align`, `color` (`foreground`/`secondary`/`accent`/`#hex`) |
| `spacer` | `height` (dp), or `flex` (share of leftover space, e.g. `1` pushes later widgets down) |
| `apps` | `apps` (list), `style` (`list`/`grid`/`row`), `columns`, `labels`, `size`, `align` |
| `search` | `hint`. Tapping it opens the drawer with the keyboard up. |
| `calendar` | `hours` (how far ahead), `size`, `align`. Shows the next event. Needs `amos perm grant io.github.rachitkj.amos android.permission.READ_CALENDAR`. |

`align` is `start`, `center` or `end`. Unknown widget types are skipped, so an
older launcher keeps working with a newer config.

## `dock`
`{"apps": [...], "labels": false}`. Keep it to 6 apps or fewer.

## `drawer`

| key | default | notes |
|---|---|---|
| `style` | `list` | or `grid` |
| `columns` | `4` | for grid |
| `showSearch` | `true` | |
| `autoLaunch` | `false` | Opens the app as soon as the search matches exactly one. |
| `hidden` | `[]` | Never shown anywhere: home, dock, drawer or search. |
| `searchOnly` | `[]` | Left out of the list, but found by search. Useful for making distracting apps take deliberate effort. |

## `gestures`
Keys: `swipeUp`, `swipeDown`, `doubleTap`, `longPress`.
Actions: `drawer`, `search`, `notifications`, `quickSettings`,
`homeSettings`, `none`, or `app:<package>`.
Defaults: swipe up opens the drawer, swipe down opens notifications, long press opens home settings.

## `rules`
```json
{"name": "Work hours", "days": ["mon","tue","wed","thu","fri"], "from": "09:00", "to": "18:00",
 "hide": ["com.instagram.android"],
 "set": {"theme": {"background": "#000000"}}}
```
- `days` defaults to every day. `from`/`to` are 24-hour `HH:MM`. Leave both out for all day.
- A window that crosses midnight (`22:00`–`07:00`) belongs to the day it starts on.
- `hide` adds apps that are hidden everywhere while the rule is active.
- `set` is merged into the config. Objects merge key by key, and anything else (lists, values) is replaced. For example, `"home": [...]` swaps the whole home screen.
- Active rules apply in list order, so later rules win.
- The launcher checks rules every minute while visible and whenever you return home.

These rules are implemented twice, in `amos/launcher_config.py` and in
`launcher/.../config/Rules.kt`. Both run `tests/vectors/rules.json` in CI.
