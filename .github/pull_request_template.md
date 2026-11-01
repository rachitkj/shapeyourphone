## What and why

<!-- One or two sentences. Link the issue if there is one. -->

## Checklist
- [ ] Every change to a phone goes through `shape/changes.py` ops (verified, logged, undoable)
- [ ] Rule semantics changed? Updated both `shape/launcher_config.py` and `Rules.kt`, plus `tests/vectors/rules.json`
- [ ] `PROMPT.md` changed? Copied to `shape/data/playbook.md`
- [ ] Bloat entries: tested on a real phone (model / Android version below), honest `breaks`
- [ ] `python3 -m unittest discover -s tests -t tests` passes

Tested on: <!-- phone model, Android version, or "emulator only" -->
