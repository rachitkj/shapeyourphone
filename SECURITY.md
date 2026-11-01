# Security

shapeyourphone runs privileged adb commands on people's phones, so we take
security reports seriously.

## Reporting
Please **don't open a public issue**. Report privately through
[GitHub security advisories](https://github.com/rachitkj/shapeyourphone/security/advisories/new).
We aim to reply within a week.

## What's in scope
- Anything that lets **another app on the phone** read or change the Shape
  launcher's config, or reach its control channel. The `ControlProvider` is
  meant to answer only the adb shell user (uid 2000) and root.
- A way to make `shape` disable or remove a protected package, or apply a
  change that isn't recorded with a working undo.
- The MCP server applying a phone change without `owner_approved=true`.
- Release APK integrity: signing, checksums, the download in `shape launcher install`.

## By design (not vulnerabilities)
- Anyone with adb access to a phone can control it, including through `shape`.
  That's how adb works. Keep USB debugging off when you don't need it, and
  never authorize a computer you don't trust.
- Data in `devices/` or `~/.shapeyourphone/` (backups, preferences, change logs)
  is stored unencrypted on your computer, like any other file you own.
