# Tooling

Date: 2026-06-09

Core reusable Python tools are flat in `tools/`. Normal users should start with
`tools/age_start.py`.

## Entry Point

```powershell
python .\tools\age_start.py --help
```

Command groups:

| Command | Purpose |
|---|---|
| `xpck extract` | extract one XPCK archive |
| `asset` | export one archive to textures/models/material manifests |
| `character` | export character archive; animation is opt-in |
| `map validate` | export selected map archives and build reports/viewer |
| `map survey` | large-sample map scan |
| `index` | build model/texture archive index |

## Core Tools: `tools/`

| Module | Purpose |
|---|---|
| `age_xpck_tool.py` | XPCK parse/extract and Level-5 decompression |
| `age_imgp_tool.py` | IMGP/XI texture decode to PNG |
| `age_xmpr_tool.py` | XMPR/PRM mesh decode and OBJ/weight sidecars |
| `age_material_bind.py` | RES/TXP/material-to-texture binding |
| `age_gltf_tool.py` | glTF writer for static and weighted meshes |
| `age_pose_export.py` | experimental posed OBJ helper |
| `age_asset_pipeline.py` | one-archive export pipeline |
| `age_asset_index.py` | archive-level model/texture/material index builder |

## Research Package: `tools/research/`

| Module | Purpose |
|---|---|
| `age_map_validation.py` | batch map export, JSON/MD report, HTML viewer |
| `age_map_survey.py` | large map survey runner |
| `age_model_survey.py` | XMPR/XPVB/XPVI survey over XPCK archives |
| `age_static_model_catalog.py` | catalog from model survey JSON |
| `age_mbn_survey.py` | MBN skeleton/bind-data coverage survey |
| `age_param_probe.py` | MTR/ATR/TXP/RES parameter probe |
| `age_model_probe.py` | focused model inspection helper |
| `age_obj_preview.py` | quick untextured OBJ preview renderer |

## Tests

Unit tests live in `tools/tests/`.

Run:

```powershell
python -m unittest discover -s .\tools\tests
```

## Ignored Local Tools

`tools/StudioElevenAnimationProbe/` is intentionally ignored. It is a local
.NET wrapper around `Tiniifan/StudioElevenLib` for XMTN parsing experiments.

The repository should link to the upstream project and document how the wrapper
was used; it should not upload the local wrapper or its build outputs.

## Ignored Third-Party Clones

`external_tools/` is ignored. Local third-party clones are useful for research
but should not be committed. See [THIRD_PARTY_REFERENCES.md](THIRD_PARTY_REFERENCES.md)
for upstream links and usage notes.




