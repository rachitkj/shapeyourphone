# Agent instructions

This repo lets an AI agent customise an Android phone over adb, reversibly.
When the user wants anything done to their phone, follow **PROMPT.md**.

Hard rules (repeated from PROMPT.md because they matter):
- Change the phone only via `python3 -m amos ...` — never raw destructive adb commands.
- Ask the owner before applying; re-run with `--yes` only after they agree.
- Never work around a BLOCKED package.
- Keep `devices/<phone>/preferences.md` current.

Developing amos itself: `python3 -m unittest discover -s tests -t tests`
(stdlib only, Python 3.9+; tests use a fake phone in tests/fakephone.py).
