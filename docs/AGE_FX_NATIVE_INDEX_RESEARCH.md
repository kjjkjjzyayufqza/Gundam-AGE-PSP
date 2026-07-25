# AGE FX Native Index / List Research

Date: 2026-07-25

> **Name collision (read first):**  
> This document is about **particle / battle effect** packages under `psp/eff`
> (`effect_config.cfg.bin`). It is **not** the mobile suit **Gundam AGE-FX**.  
> Suit findings: **`ms010000`** — see `docs/AGE_FX_SESSION_2026-07-25.md` and
> `outputs/age_fx_ms/AGE_FX_PARTS.md`.

Goal: locate the **game's own** index/list artifacts that enumerate age-fx
(effect) packages so complete models (`.prm`) and textures (`.xi`) can be
extracted, and distinguish those native tables from the project research index
(`age_asset_index`).

## Search coverage

Local unpacked root used for this pass (auto-discovered under `D:\PPSSPP`):

```text
D:\PPSSPP\AGE解包\资源解包\
  cmn\
  psp\
    eff\          # 649 .xc effect/event packages
    chr\, map\, btl\, evt\, ...
```

Patterns and locations checked:

| Root / pattern | Result |
|---|---|
| `cmn/res/eff/*` | **Hit** — game-native effect config binaries |
| `cmn/*_common_pack.bin` | XPCK packs of shared configs; not a flat FX model catalog |
| `cmn/bin.xr` | Not present under this unpack |
| `psp/eff/**/*.xc` | Full on-disk FX archive tree (649 packages) |
| XPCK filename tables inside each `.xc` | **Hit** — per-archive native member list |
| `RES.bin` → `CHRP00` inside packages | Per-archive name/material strings, not global FX catalog |
| Project `outputs/manifests/age_asset_index*` | Research scanner only; not game-native |
| `docs/STATIC_MODEL_CATALOG.md` `eff` category | Path-based survey summary, not native list |

Also searched for a single global “fx list” text/binary outside `cmn/res/eff`
under the unpack root; no separate master file superseded `effect_config.cfg.bin`.

## Candidates and classification

### 1. `cmn/res/eff/effect_config.cfg.bin` — **global logical FX catalog (primary)**

| Field | Value |
|---|---|
| Path | `<UNPACK>/cmn/res/eff/effect_config.cfg.bin` |
| Size (this dump) | 26576 bytes |
| Magic/header | Little-endian `u32` header; not XPCK. Leading count `489`. String table offset `0x5370`. |
| Role | **True game-native FX catalog** for battle/common effects: effect IDs → `.xc` archive names under base path `#/eff/`. |

Structure (observed):

1. Header words: entry-related count, **string table absolute offset**, two layout words.
2. Binary CFG records keyed by CRC32 of field tags:
   - `EFFECT_CONFIG_BASE_FILE_PATH` → `347c948d`
   - `EFFECT_CONFIG_BEGIN` / `EFFECT_CONFIG` / `EFFECT_CONFIG_END`
   - `EFFECT_CONFIG_INDEX_BEGIN` / `EFFECT_CONFIG_INDEX` / `EFFECT_CONFIG_INDEX_END`
3. String table starting at the header offset, beginning with `#/eff/`, then
   interleaved effect IDs (`eb000010`, `esga0125b`, …) and archive names
   (`eb000010.xc`, …).
4. Each `EFFECT_CONFIG` record stores a **name string offset**, **CRC32 of the
   effect id** (validated), and an **archive string offset** when present.

How it maps to extractable assets:

```text
effect_config.cfg.bin
  -> effect_id + archive_name (.xc)
  -> resolve under psp/eff/**/archive_name
  -> XPCK filename table (native)
       -> .prm models
       -> .xi textures
       -> .mtr/.atr/.txp materials
```

Live inventory (this dump):

- Unique `.xc` names in config string table: **177**
- Resolved on disk under `psp/eff`: **176** (`bs0010001.xc` referenced but missing)
- Effect config is **not exhaustive** of every file under `psp/eff` (disk has **649** `.xc`, including `eff/evt/...` packs and variants not named in this catalog)

### 2. `cmn/res/eff/effect_define_field.cfg.bin` — **field-effect subset catalog**

| Field | Value |
|---|---|
| Path | `<UNPACK>/cmn/res/eff/effect_define_field.cfg.bin` |
| Size | 1424 bytes |
| Role | Smaller native CFG using the same tag vocabulary; focuses on field `em*.xc` packages. |

Same extraction path as (1). Treated as a secondary native list, not a replacement.

### 3. `cmn/res/eff/load_effect_chara_info.cfg.bin` — **non-catalog helper**

| Field | Value |
|---|---|
| Path | `<UNPACK>/cmn/res/eff/load_effect_chara_info.cfg.bin` |
| Role | Character effect load helper. No usable global archive-name string table for FX inventory. |

### 4. Per-archive XPCK filename table — **native member list (models/textures)**

| Field | Value |
|---|---|
| Location | Inside each `.xc` / related XPCK |
| Magic | `XPCK` |
| Role | **Per-package** game-native file list (compressed name table). This is what names `000.prm`, `000.xi`, `RES.bin`, etc. |

Without this table, `effect_config` only names packages, not mesh/texture members.

### 5. Per-archive `RES.bin` → `CHRP00` — **name/material helper**

Role: mesh/material/projection strings used by material binding. Not a global FX
package index. See `docs/BINARY_FORMATS.md` and `age_material_bind.py`.

### 6. Project `age_asset_index` — **research scanner (not game-native)**

Scans directory metadata of XPCK archives and classifies by path (`eff` area).
Useful for bulk research, but **not** the game's own list. This goal's tool
`age_fx_index.py` / `age_start.py fx-index` is the native-aware inventory path.

## Inventory outcome (actionable)

Tooling added:

| Path | Purpose |
|---|---|
| `tools/age_fx_index.py` | Parse `effect_config.cfg.bin`, resolve `psp/eff` archives, list XPCK `.prm`/`.xi` members |
| `tools/age_start.py fx-index` | User-facing entry |
| `tools/tests/test_age_fx_index.py` | Synthetic CFG unit tests + live unpack integration test |

Command:

```powershell
python .\tools\age_start.py fx-index "<UNPACK_ROOT>" `
  --json .\outputs\manifests\age_fx_native_index.json `
  --markdown .\outputs\manifests\AGE_FX_NATIVE_INDEX.md
```

Optional:

- `--native-only` — only archives named by native configs (skip disk-only packs)
- `--member-limit N` — cap XPCK member inspection for faster runs
- `--no-members` — catalog packages only

Regenerated outputs (local, gitignored):

- `outputs/manifests/age_fx_native_index.json`
- `outputs/manifests/AGE_FX_NATIVE_INDEX.md`

Sample evidence from a real run (`--member-limit 80`):

| Metric | Count |
|---|---:|
| Native config archives | 177 |
| Disk `psp/eff` archives | 649 |
| Resolved on disk | 649 |
| Inspected with `.prm` models | 77 |
| Inspected with `.xi` textures | 71 |

Example package grounded in the native list:

| Field | Value |
|---|---|
| Archive | `bs0010002.xc` |
| Source | `effect_config.cfg.bin` |
| Effect id | `bs0010002` |
| Path | `<UNPACK>\psp\eff\bs0010002.xc` |
| Models | `000.prm` … `005.prm` (6) |
| Textures | `000.xi` … `003.xi` (4) |

Complete extract for one package (existing pipeline):

```powershell
python .\tools\age_start.py asset "<UNPACK>\psp\eff\bs0010002.xc" `
  --out-dir .\outputs\pipeline\bs0010002 `
  --name bs0010002 `
  --overwrite
```

For full age-fx coverage:

1. Prefer **native config** set for “what the game registers as effects”.
2. Add **disk-only** `psp/eff` rows (included by default) for complete package
   coverage (evt/variants).
3. For each package, use XPCK member lists (or `asset` pipeline) for all
   `.prm` + `.xi`.

Note: catalog evidence and live inspection show age-fx packages are overwhelmingly
**static / unweighted** meshes. Bones/weights are not part of the FX catalog
contract; use `chr` skinned pipelines for that.

## Residual unknowns

- Full field-by-field layout of every `u32` in the 0x48-byte `EFFECT_CONFIG`
  record beyond name offset, name CRC, and archive string offset.
- Exact semantics of `EFFECT_CONFIG_INDEX` rows (ordering/lookup), beyond tag
  presence and string pool.
- Why a few config archive names alias or diverge from effect ids (validated by
  CRC on the id string; archive association still taken from the record’s
  archive string offset when it ends in `.xc`).
- Cross-references from battle packages (`psp/btl`) that may load FX indirectly
  without appearing as top-level `effect_config` ids.

## Cross-check vs existing docs/tools

| Claim | Consistency |
|---|---|
| XPCK filename tables list members | Matches `age_xpck_tool.parse_xpck` / `docs/BINARY_FORMATS.md` |
| `RES.bin`/`CHRP00` is per-archive | Matches `age_material_bind` / `docs/RESOURCE_ARCHITECTURE.md` |
| `eff` is a large model area | Matches `docs/STATIC_MODEL_CATALOG.md` / `docs/DATA_DISTRIBUTION.md` |
| Project index ≠ game list | Explicitly separated; `fx-index` is the native path |

No contradiction found: prior work lacked this native CFG inventory path; it
used path scanning instead.
