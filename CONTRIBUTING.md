# Contributing

The most useful contributions right now:

1. **Real-device reports.** Run a session on your phone and open an issue with
   the model, Android version and OEM skin (`shape doctor` prints them), what
   worked, and any command that failed along with its output.
2. **Bloat list entries** you have tested. See `shape/data/bloat/README.md`. Say what
   breaks, honestly.
3. **Protected packages.** If disabling something broke a phone, add it to
   `shape/data/protected.json` with the reason.

Ground rules:
- Every change to a phone must go through `shape/changes.py` ops so it is
  verified and reversible. No fire-and-forget adb commands.
- Rule semantics live in two places (`shape/launcher_config.py` and
  `launcher/.../config/Rules.kt`). Change both, and add a case to
  `tests/vectors/rules.json`.
- Python stays standard-library only. The launcher stays dependency-free.

Tests: `python3 -m unittest discover -s tests -t tests` and
`cd launcher && ./gradlew testDebugUnitTest lintDebug assembleDebug`.
