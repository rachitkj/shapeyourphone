# Bloat lists

Each JSON file is a list of packages that commonly ship preinstalled and that
can be switched off without breaking the phone. shape only ever acts on entries
that are actually installed and enabled on the connected phone, so lists from
other brands are harmless.

## Tiers

| tier | meaning | applied by |
|---|---|---|
| `safe` | Ads, telemetry, preinstall "app installers". Nothing the owner would notice is gone. | `shape plan --tier safe` |
| `recommended` | OEM duplicates of Google apps and promo apps most people never open. | `shape plan --tier recommended` (includes `safe`) |
| `optional` | Real apps some people use (browsers, Bixby, game launchers). Only on the owner's explicit say-so. | `shape plan --tier all`, or `--include <pkg>` |

## Entry format

```json
{"pkg": "com.miui.msa.global", "name": "MIUI System Ads", "tier": "safe",
 "why": "Serves ads inside Xiaomi system apps.",
 "breaks": "Nothing visible."}
```

`breaks` should say honestly what stops working. If you are not sure, say so.

## Contributing

Add entries you have tested on a real phone, and mention the phone model and
OS version in your PR. Never add anything that is in `shape/data/protected.json`.
