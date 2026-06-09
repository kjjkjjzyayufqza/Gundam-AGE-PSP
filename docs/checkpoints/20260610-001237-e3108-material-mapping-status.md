---
status: in-progress
branch: master
timestamp: 2026-06-10T00:12:37.0850161+08:00
files_modified: []
---

## Working on: e3108 material mapping status

### Summary

Gundam AGE PSP 3108.xc map can extract all mesh and texture assets, but correct mesh-to-texture/material mapping has not been located as an explicit stored mapping file inside the archive. Current working mapping is external project data in 	ools/data/mesh_texture_mappings.json.

### Decisions Made

- Keep 	ools/data/mesh_texture_mappings.json as source-of-truth override until archive-native mapping is decoded.
- Treat PRM/TXP/MTR/ATR/RES evidence separately: PRM proves mesh -> material; TXP proves material/texproj hash owner; neither currently proves user-verified mesh -> XI texture mapping.
- MTR/ATR inspected for key stems appeared mostly identical and did not expose obvious texture index for the corrected pairs.
- RES.bin/CHRP00 has strings and CRC relationships; likely remaining place for object graph mapping, but current parser only extracts strings/CRC, not full structure.

### Remaining Work

1. Decode RES.bin CHRP00 object graph enough to recover mesh/material/texproj/texture-slot relationships.
2. Compare decoded native relationships against user-verified corrections: chara->024, chara01->026, chara02->025, d->037 tentative, g01->028, g02->027.
3. If CHRP00 does not contain it, inspect higher-level map package/linkage files or runtime references outside 3108.xc.
4. Keep updating mesh_texture_mappings.json with user-verified corrections meanwhile.

### Notes

- Current e3108 export: 63 meshes, 48 textures, 63 MTL records, 0 unresolved after external mapping.
- User-verified corrections already applied and re-exported in outputs/pipeline/e3108/models/e3108_strip.gltf.
- Previous assumption that TXP numbered stem equals XI texture is false for several character/mecha entries.
- map_validation pipeline was consolidated/removed from CLI; use ge_start.py asset and map survey only.
