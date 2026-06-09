# Data Distribution

Date: 2026-06-09

This document records current archive distribution from the local PSP resource
tree. Counts come from `outputs/manifests/AGE_ASSET_INDEX.md`.

## Index Command

```powershell
python .\tools\age_start.py index "<PSP_RESOURCE_ROOT>" `
  --json .\outputs\manifests\age_asset_index.json `
  --compact-json .\outputs\manifests\age_asset_index.compact.json `
  --markdown .\outputs\manifests\AGE_ASSET_INDEX.md `
  --pipeline-root .\outputs `
  --exclude "*/map/*chr*.xc"
```

The index parses XPCK directory metadata only. It does not extract binary
assets.

## Global Counts

| Metric | Count |
|---|---:|
| XPCK archives indexed | 4529 |
| Parse errors | 0 |
| Archives with `.prm` models | 2364 |
| Archives with `.xi` textures | 2710 |
| Archives with both models and textures | 2343 |
| `.prm` model entries | 23880 |
| `.xi` texture entries | 9170 |
| material parameter entries | 46760 |
| linked pipeline exports | 117 |

## Category Summary

| Category | Archives | Models | Textures | Materials | Model+Texture |
|---|---:|---:|---:|---:|---:|
| `eff` | 622 | 11385 | 2726 | 25756 | 611 |
| `mobile_suit` | 542 | 1261 | 985 | 2954 | 451 |
| `human_or_npc` | 523 | 1995 | 879 | 2959 | 407 |
| `map` | 285 | 6766 | 2704 | 10261 | 273 |
| `ue_unit` | 321 | 863 | 720 | 2222 | 150 |
| `evt` | 1243 | 1081 | 367 | 1236 | 147 |

## Map Data

Map survey status:

| Metric | Count |
|---|---:|
| non-`chr` map samples | 285 |
| failed exports | 0 |
| visually clean | 198 |
| plain unresolved visual materials | 54 |
| effect-only unresolved materials | 33 |

Large clean controls:

- `t5201`
- `t0901`
- `e2104`
- `b3003`

Large priority problem maps:

- `e1101`
- `b3205`
- `b0101`
- `b3104`
- `t0201`
- `e3108`

## Index File Roles

| File | Role |
|---|---|
| `AGE_ASSET_INDEX.md` | human-readable summary tables |
| `age_asset_index.compact.json` | preferred machine-readable list for lookup |
| `age_asset_index.json` | full list with raw XPCK entry offsets/sizes |

Use compact JSON for normal lookup. Use full JSON when debugging archive entry
offsets or extractor errors.




