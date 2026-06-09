# Level-5 Asset Workflow Notes

Date: 2026-06-09

Scope: Gundam AGE PSP archive, model, texture, map extraction. Current focus is
static maps, map textures, and a future model/texture index list.

## Current State

- Character model basics are done for current research scope: weights, UVs,
  bones, static model export, and texture export are usable.
- Texture black speckles were traced to PSP image swizzle. The exporter now
  defaults to `psp-swizzled` and sampled character/map textures render
  coherently.
- Most maps are extractable. Latest full non-`chr` map survey:
  - `285` samples
  - `0` failed exports
  - `198` visually clean
  - `54` plain unresolved visual-material cases
  - `33` effect-only unresolved cases
- Large clean controls already pass:
  `t5201`, `t0901`, `e2104`, `b3003`.
- Large priority problem samples:
  `e1101`, `b3205`, `b0101`, `b3104`, `t0201`, `e3108`.
- Preview screenshots are now stored in:
  - `outputs/previews/map_large_focus_viewer_20260609.png`
  - `outputs/previews/map_e110x_family_viewer_20260609.png`
  - `outputs/previews/map_large_extra_viewer_20260609_full.png`
- Additional large sample batch:
  `outputs/map_validation/large_extra_20260609/`.
  It covers `b2003`, `m01`, `b8501`, `t0703`, `t0704`, `t0401`,
  `t1102`, `t1106`, `b3201`, `e2107`, `b0601`, and `b0803`.
  Most texture decode is coherent; remaining visible gaps are small material
  binding misses, not a global texture-layout failure.

## One Entry Point

Preferred entry is:

```powershell
python .\tools\age_start.py --help
```

This is a thin wrapper. Real implementation remains in focused modules:

- `tools/age_xpck_tool.py`
- `tools/age_asset_pipeline.py`
- `tools/research/age_map_report.py`
- `tools/research/age_map_survey.py`
- `tools/age_imgp_tool.py`
- `tools/age_xmpr_tool.py`
- `tools/age_gltf_tool.py`
- `tools/age_material_bind.py`

Extract one XPCK archive:

```powershell
python .\tools\age_start.py xpck extract "<PSP_RESOURCE_ROOT>\map\e1101.xc" --out .\outputs\extract\e1101 --overwrite
```

Export one archive to textures, OBJ, MTL, glTF, and manifests:

```powershell
python .\tools\age_start.py asset "<PSP_RESOURCE_ROOT>\map\e1101.xc" --out-dir .\outputs\pipeline\e1101 --name e1101 --overwrite
```

Export and compare selected maps with normal asset output:

```powershell
python .\tools\age_start.py asset "<PSP_RESOURCE_ROOT>\map\e3108.xc" --out-dir .\outputs\pipeline\e3108 --name e3108 --overwrite
```

Run large map survey:

```powershell
python .\tools\age_start.py map survey --input-root "<PSP_RESOURCE_ROOT>\map" --out-root .\outputs\map_survey\all_non_chr --exclude "*chr*.xc" --cleanup-samples --overwrite
```

## File Architecture

Top-level game data currently used by this repo comes from already-unpacked PSP
files supplied outside this repo. The tooling does not download or dump game
data.

Common paths observed:

- `psp\chr\...`: character/mobile-suit archives.
- `psp\map\...`: static map archives.
- `psp\btl\...`: battle packages that can contain nested archives.

Important Level-5/AGE PSP file types:

| Type | Role |
|---|---|
| `.xc`, `.xb`, `.xa`, `.xv`, `.xk` | `XPCK` archive containers |
| `RES.bin` | Level-5 compressed resource/name table; decoded payload often starts with `CHRP00` |
| `.xi` | `IMGP` texture |
| `.prm` | `XMPR` model mesh container with `XPVB` vertex data and `XPVI` index data |
| `.mbn` | skeleton/bind data for character meshes; skipped for unweighted static maps |
| `.mtr` | `MTRP00` material parameter block |
| `.atr` | `ATRP01` render/attribute block |
| `.txp` | texture parameter block; first two words match CRC32 of resource strings |
| `.mtn2` | animation/motion candidate |

Map extraction path:

1. `.xc` archive -> XPCK parser.
2. Entries are written under `extracted/`.
3. `RES.bin` is decompressed to recover `CHRP00` names.
4. `.xi` textures are converted to PNG.
5. `.prm` meshes are decoded to OBJ/glTF.
6. `.mtr` / `.txp` / `CHRP00` strings build material-to-texture binding.
7. `MTL map_Kd` points OBJ materials to exported PNGs.
8. Validation writes JSON, Markdown, and HTML viewer.

## Compression / Encryption

No separate cryptographic encryption has been proven in sampled AGE PSP assets.
The required reversible step is Level-5 compression/decompression inside XPCK
filename tables, `RES.bin`, and IMGP blocks.

Known compression cases:

- XPCK filename table: Level-5 compressed or raw.
- `RES.bin`: Level-5 compressed; decoded data commonly begins with `CHRP00`.
- `IMGP` `.xi`: palette, tile table, and pixel blocks can each use Level-5
  compression variants.

Manual decompression entry:

```powershell
python .\tools\age_xpck_tool.py decompress-l5 .\some_payload.bin --out .\payload.dec.bin --overwrite
```

Normal users should not need manual decompression. `age_start.py asset` calls
the needed decode paths.

## Texture Decode

AGE PSP `.xi` textures are `IMGP`.

Current decode:

1. Decode palette block.
2. Decode tile table.
3. Decode indexed pixel block.
4. Rebuild 8x8 indexed tiles.
5. Apply PSP 16-byte x 8-row deswizzle.
6. Apply palette.
7. Write PNG.

Default:

```text
--texture-layout psp-swizzled
```

`tiled` is only for old comparison. It reproduces the earlier colored-but-black
speckled texture problem.

## Model Decode

AGE PSP `.prm` files are `XMPR`.

Current decode:

- `XPVB`: vertex buffer, UVs, weights, bone indices.
- `XPVI`: indices.
- OBJ export: topology/material inspection.
- glTF export: textured review with static or weighted meshes.
- Weight sidecar: `*.weights.json`.

Map rule:

- Static maps should have `0` weighted vertices and `0` skins.
- If a map is unweighted, `age_gltf_tool.py` now skips MBN loading. This fixed
  false failures on `fe*` maps with bad/cyclic MBN data.

## Material Binding

Current material binding order:

1. Direct `TXP` owner CRC32 match against `CHRP00` resource strings.
2. Numbered `TXP`/`XI` same-stem match, for example `013.txp -> 013.xi`.
3. Mesh-name/resource-order fallback.
4. Unresolved material remains plain in MTL/glTF and is counted in reports.

Current unresolved large-map classes:

- `b0101`: mesh-name candidate exists, but no in-archive `.xi` target.
- `e1101`, `b3104`, `t0201`, `e3108`: TXP owner confirmed, no usable texture
  candidate yet.
- `b3205`: resource-string-only plain material, no TXP owner.

## GitHub Repositories Used

Public GitHub tools were downloaded/read under `external_tools/github/` and are
recorded in `docs/ASSET_EXTRACTION_RESEARCH.md`.

Used references:

| Repo | Use |
|---|---|
| `Tiniifan/studio_eleven` | Blender importer behavior; PRM vertex handling; MBN armature behavior |
| `Tiniifan/StudioElevenLib` | XPCK, XPVB, XPVI, XMPR, IMGC, and XMTN reference implementation; local animation probe wraps this library |
| `Tiniifan/Pingouin` | XPCK GUI archive-manager reference; not used as CLI |
| `Tiniifan/Level5ResourceEditor` | Checked but AGE PSP `CHRP00` differs from its target `XRES` workflow |
| `Tiniifan/level5_material` | Checked; incompatible with AGE PSP `MTRP00` samples |
| `Ploaj/Metanoia` | Historical Level-5 XI/PRM/animation reference; confirms weight/index slot semantics |
| `albe/openTri` | PSP swizzle reference; directly informed black-speckle fix |
| `SIEBEN5106/Gundam-AGE-PSP-Texture-Pack` | Texture reference corpus, not an extractor |
| `FanTranslatorsInternational/Kuriimu2` and older `Kuriimu` code | XPCK and Level-5 compression reference |

## Output Layout

Recommended generated-output layout:

| Path | Meaning |
|---|---|
| `outputs/previews/` | PNG screenshots and quick visual previews |
| `outputs/pipeline/<sample>/` | One archive full export |
| `outputs/map_survey/<batch>/` | Large survey JSON/MD; use `--cleanup-samples` to avoid retaining every sample |
| `outputs/manifests/` | Stable JSON manifests from probes/catalogs |
| `outputs/tmp/` | Disposable experiments |

Do not treat `outputs/` as source. It can be regenerated from original game
data and scripts.

## Asset Index/List

The first model/texture list is now generated.

Files:

- `outputs/manifests/AGE_ASSET_INDEX.md`
- `outputs/manifests/age_asset_index.compact.json`
- `outputs/manifests/age_asset_index.json`

Command:

```powershell
python .\tools\age_start.py index "<PSP_RESOURCE_ROOT>" --json .\outputs\manifests\age_asset_index.json --compact-json .\outputs\manifests\age_asset_index.compact.json --markdown .\outputs\manifests\AGE_ASSET_INDEX.md --pipeline-root .\outputs --exclude "*/map/*chr*.xc"
```

Current totals:

- `4529` XPCK archives indexed.
- `0` parse errors.
- `2364` archives contain model `.prm` files.
- `2710` archives contain texture `.xi` files.
- `2343` archives contain both models and textures.
- `23880` model files indexed.
- `9170` texture files indexed.
- `46760` material parameter files indexed.
- `117` existing pipeline exports linked from current `outputs/`.

Minimum useful fields:

- archive path
- archive stem
- archive group (`chr`, `map`, `b`, `t`, `e`, `p`, `sky`, `fe`, etc.)
- contained `.prm` files
- contained `.xi` files
- material files: `.mtr`, `.atr`, `.txp`
- `RES.bin` / `CHRP00` strings
- mesh count
- texture count
- resolved material count
- unresolved material names
- exported OBJ path
- exported glTF path
- exported texture PNG paths
- confidence/source for material binding

Current implementation:

1. `tools/age_asset_index.py` scans XPCK directory metadata without extracting
   binary assets.
2. It records model, texture, material, skeleton, animation, resource, and
   nested-XPCK entry lists per archive.
3. It links existing `_asset_pipeline_manifest.json` files from `outputs/` so
   already-exported OBJ/glTF/PNG paths are discoverable.
4. It emits full JSON, compact JSON, and Markdown.





