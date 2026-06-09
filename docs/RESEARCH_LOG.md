# Gundam AGE PSP Research Log

This is the dated working log for evidence, analysis, decisions, commands, and
validation. Stable conclusions and user-facing instructions are consolidated
in `ASSET_EXTRACTION_RESEARCH.md`.

## 2026-06-08

### 22:37 +08:00 - Continuation audit

- Re-read the authoritative task statement in
  `E:\research\Gundam_Breaker_Mobile\USER_INTENT_FOR_GAME_ASSET_RESEARCH.md`.
- Confirmed the desired outcome is a reusable model, texture, material, archive,
  and supporting-format workflow, not only a successful single sample.
- Existing practical outputs: XPCK extraction, IMGP to PNG with PSP 16-byte by
  8-row deswizzle, XMPR to OBJ, TXP/MTL material binding, and a manual
  StudioElevenLib MTN2-to-posed-OBJ path.
- Remaining workflow gap selected for this iteration: automatic discovery,
  compatibility checking, and posing of sibling character animation archives.

### 22:41 +08:00 - GitHub source comparison

- `Ploaj/Metanoia` identifies Level-5 PRM slot 7 as bone weights and slot 8 as
  bone indices. The AGE PSP sample family uses active slot 7 and inactive slot
  8; its one-hot bytes therefore select entries from the XMPR node table
  implicitly.
- The full 24,103-PRM survey contains only two slot 7/8 patterns:
  19,927 PRMs have neither slot active; 4,176 have slot 7 as
  `(count=12, offset=0, size=8, type=2)` and slot 8 absent.
- Metanoia inverts MTN2 quaternions. Tiniifan's current Blender add-on instead
  converts the raw animation quaternion through the current pose-bone matrix.
  For the sampled AGE model's identity bind rotations, the StudioEleven path
  uses the raw quaternion directly.
- Decision: keep `studioeleven` as the default rotation convention and expose
  an explicit `inverse` diagnostic mode. Do not silently choose one conflicting
  external convention.

### 22:44 +08:00 - Implementation plan

- Created
  `docs/superpowers/plans/2026-06-08-character-animation-pipeline.md`.
- Execution mode: inline, because this thread already requests continuous
  implementation rather than a plan-only handoff.

### 22:49 +08:00 - Automated animation pipeline validation

- Added `from-character` to `age_asset_pipeline.py`. It discovers same-prefix
  `_sNNN.xc`/`_vNNN.xc` archives, parses MTN2 with the GitHub
  `StudioElevenLib` wrapper, compares XMTN/XMPR node hashes, chooses an
  automatic representative frame, and exports only compatible poses.
- `fn024000_p000.xc`: 39 files, 1 texture, 3 PRMs, 3 animation candidates,
  20/20 model nodes covered, selected `fn024000_s240` frame 20, transformed
  1911/1911 vertices, 0 failures.
- `fn001000_p000.xc` and `fn001001_p000.xc`: each has 22 files, 1 texture,
  1 PRM, 2 animation candidates, 5/5 node coverage, selected frame 7,
  transformed 1114/1114 vertices, and produced 0 failures.
- Structural audits found finite coordinates, valid OBJ face indices,
  existing MTL files, and resolving `map_Kd` PNG paths.

### 22:50 +08:00 - Visual classification correction

- Added `age_obj_preview.py`, using installed Matplotlib 3.10.0 only as an
  untextured OBJ topology renderer.
- `fn024000`, `fn001000`, and `fn001001` pose previews show small
  octahedron/marker clusters distributed across animation nodes. Their
  animation transforms are valid, but these assets must not be described as
  complete character models; they are more likely effects, helpers, or
  node-distributed marker geometry.
- `bs001000_p000_strip.obj` previews as a coherent craft/vehicle-like
  mechanical silhouette with 1436 vertices and 492 non-degenerate triangles.

### 22:51 +08:00 - Embedded MTN2 support

- Extended `from-character` to parse `.mtn2` files embedded in the model XPCK,
  in addition to sibling archives. Candidate manifests now record
  `source_kind=embedded_model_archive|sibling_animation_archive`.
- `bs001000_p000.xc` contains embedded animation `out_00`, 7 frames, and one
  animation node. Its seven float32 PRMs have zero XMPR node hashes, so the
  pipeline records one candidate and correctly exports zero posed models.
- Regression result: 7 `unittest` tests pass; Python syntax checks pass;
  `fn024000` still yields 3 candidates, one selected pose, and zero failures.

### 22:52 +08:00 - Texture black-speckle verification

- Visually inspected the fixed `bs001000` 256x128 atlas. Color regions,
  outlines, and mechanical details are continuous; the earlier scattered dark
  pixels are absent.
- Pixel audit after PSP 16-byte by 8-row deswizzle:
  `bs001000/000.png` has 0 pure-black and 0 alpha-zero pixels out of 32768;
  `bs001000/001.png` has 0/1024 for both; `fn024000/000.png` also has 0/1024.

### 22:53 +08:00 - Additional GitHub search

- Searched GitHub repositories and Exa for a Gundam AGE PSP-specific
  XPCK/XMPR/IMGP extractor. No dedicated converter was found.
- GitHub code search was unavailable because the configured MCP requires
  authentication; this limitation is recorded instead of treating the search
  as exhaustive.
- Inspected `SIEBEN5106/Gundam-AGE-PSP-Texture-Pack` at commit `237c825`.
  It is a PPSSPP replacement-texture corpus covering all MS and weapons, not
  an extraction tool, so it is retained only as a future visual comparison
  source.

### 22:53 +08:00 - Authoritative goal re-alignment

- Re-read
  `E:\research\Gundam_Breaker_Mobile\USER_INTENT_FOR_GAME_ASSET_RESEARCH.md`
  after the user restated that it is the research target.
- Re-prioritized usable static model + texture + material extraction.
  Animation remains supporting-format research only and must not substitute
  for a validated static asset result.

### 22:55 +08:00 - Complete mobile-suit sample located

- Aggregated the 3,673-archive survey by `chr` directory prefix. The `ms`
  family has 523 archives, 436 archives with PRM, 1,180 PRMs, and 897,180
  decoded vertices; 1,178 PRMs use `s16_normx3`.
- `ms000001` is a generic skeleton/action exception, not representative of the
  model-bearing `ms*` family.
- Selected `ms008000_p000.xc`: 87 files, 5 XI, 12 PRM, 5 MTR/ATR/TXP sets,
  45 MBN bones, and 10,473 vertices.
- Its unanimated OBJ preview is a coherent full mechanical humanoid, proving
  that normalized signed-16-bit positions are usable bind-pose positions, not
  geometry that must first be animated.

### 23:00 +08:00 - GitHub MBN semantics and animation correction

- StudioEleven's Blender importer writes PRM positions directly into the mesh,
  creates the MBN armature separately, and then assigns vertex groups.
  Metanoia follows the same static-position interpretation.
- Renamed the manifest semantic from
  `animation_dependent_local_position` to `skinned_bind_pose_position`.
- Implemented MBN bind SRT parsing and the standard
  `animated_global * inverse(bind_global)` skinning matrix, with a unit test.
- Complete-model previews using `ms000001_p300` and `ms008000_p210` still
  separate parts despite 24/24 node overlap and 10,473 transformed vertices.
  This proves the remaining problem is XMTN/Blender pose-channel space, not
  static model extraction.
- Decision: pose export remains explicitly experimental. `from-character`
  now defaults to `--animation-policy none`.

### 23:02 +08:00 - Recommended static workflow audit

- Command:
  `python tools\age_asset_pipeline.py from-character
  <PSP_RESOURCE_ROOT>\chr\ms008000\ms008000_p000.xc
  --out-dir outputs\pipeline\ms008000_static_recommended
  --name ms008000_p000 --triangulation strip --overwrite`.
- Result: 5 PNG textures, 12 meshes, 5 materials, 0 animation candidates,
  0 failures.
- OBJ audit: 10,473 finite vertices, 3,738 legal faces, bounds
  `[-0.915344, -0.477844, -0.625458]` to
  `[0.915344, 0.999969, 0.383026]`.
- MTL audit: the MTL exists and all five `map_Kd` paths resolve.
- Texture audit: four 128x128 PNGs and one 128x64 PNG; each has 16 colors,
  zero pure-black pixels, and zero alpha-zero pixels.
- Visual audit:
  `outputs\previews\ms008000_static_recommended.png` is a coherent full
  mobile-suit silhouette.
- Regression result: 9 unit tests pass and all modified Python files compile.

### 23:16 +08:00 - Phase summary and weight-export gap

- Re-read the authoritative intent file at
  `E:\research\Gundam_Breaker_Mobile\USER_INTENT_FOR_GAME_ASSET_RESEARCH.md`.
  The active deliverable remains a reproducible static asset workflow:
  model, texture, material data, archive/resource manifests, and documentation.
- Current reliable output is static bind-pose extraction, not animation:
  `ms008000_p000.xc` produces a coherent complete mobile-suit OBJ, MTL,
  five PSP-deswizzled PNG textures, material binding manifests, and validation
  evidence. `from-character` defaults to `--animation-policy none`.
- The texture black-speckle issue is closed for sampled XI files. The cause
  was missing PSP 16-byte by 8-row indexed-pixel deswizzling after rebuilding
  the IMGP tile table.
- GitHub research has been used and recorded. Existing public Level-5 tools
  informed XPCK, XI/IMGP, XPVB/XPVI/XMPR, MBN, and animation parsing. No
  dedicated Gundam AGE PSP extractor has been found so far.
- Current weight status: `age_xmpr_tool.py` decodes XPVB slot 7 as
  `implicit_node_weights_u8` and records XMPR `node_hashes` in JSON manifests.
  This proves the source data contains per-vertex weight bytes for sampled
  skinned 16-bit meshes.
- Current gap: OBJ cannot carry skin weights, and the pipeline does not yet
  emit a per-vertex weight sidecar or a weight-preserving model format such as
  glTF/DAE/FBX. The next implementation step should therefore add a
  deterministic weight manifest next to the OBJ, then validate it on `ms*` and
  `ue*` samples before considering a full glTF skin export.

### 23:24 +08:00 - Weight sidecar implemented and validated

- Used GitHub search again for existing AGE/Level-5 model exporters with
  XPVB/XPVI/XMPR weight support. Repository search found no dedicated Gundam
  AGE PSP extractor beyond previously recorded tools.
- Rechecked local GitHub clones:
  `Tiniifan/studio_eleven` maps XMPR weights and bone indices into Blender
  vertex groups; `StudioElevenLib` reads XPVB slot 7/8 as weights/bone
  indices for float-style Level-5 meshes; `Metanoia` has a DAE writer that
  serializes vertex weights. These informed the local sidecar schema, but no
  existing tool directly handles AGE PSP's 8-byte slot 7 implicit node weights.
- Added `age_xmpr_weights_v1` sidecar generation to `age_xmpr_tool.py`.
  `export-obj` now writes `<obj>.weights.json` by default, with optional
  `--weights-json`. Each weighted vertex records its OBJ vertex index, source
  mesh vertex index, position/UV, raw `raw_u8` weight byte, `weight_raw128`,
  per-vertex `weight_normalized`, slot index, and XMPR node hash.
- Integrated the sidecar into `age_asset_pipeline.py`; pipeline manifests now
  include a compact `models.weights` summary instead of embedding all per-
  vertex records.
- Validation samples:
  `ms008000_p000.xc` -> 5 textures, 12 meshes, 5 materials, 10473 weighted
  vertices, 10473 weight records, 0 unmapped records.
  `ms007000_p000.xc` -> 4 textures, 9 meshes, 4 materials, 7898 weighted
  vertices, 7898 weight records, 0 unmapped records.
  `ue001000_p000.xc` -> 5 textures, 5 meshes, 5 materials, 3562 weighted
  vertices, 3566 weight records, 0 unmapped records. This proves the sidecar
  preserves multi-influence vertices and is not assuming one-hot weights.
  `map\b0000.xc` -> 18 textures, 74 meshes, 43 materials, 0 weighted vertices,
  0 weight records, 0 unmapped records. This is the negative control for
  static map meshes.
  `ue000001_p000.xc` -> 0 textures, 0 meshes, 0 materials; survey shows this
  was a sample-selection miss, not a parser failure.
- Regression result: 11 unit tests pass, including new weight-manifest tests;
  modified Python files compile.

### 23:33 +08:00 - Static weighted glTF export

- GitHub repository search for a ready-to-use Python glTF skin-weight writer
  or Level-5 XMPR glTF exporter did not find a directly reusable tool. The
  local exporter therefore stays dependency-light and uses the decoded XPVB
  data already validated in this workspace.
- Added `tools\age_gltf_tool.py`. It writes glTF 2.0 JSON plus an external
  `.bin` buffer directly from decoded XMPR/XPVB meshes. It does not parse or
  execute action files.
- glTF attributes:
  `POSITION`, `TEXCOORD_0`, `JOINTS_0`, `WEIGHTS_0`, and, when needed,
  `JOINTS_1` / `WEIGHTS_1`. Material texture references reuse the PNG paths
  from the MTL/material binding pipeline.
- For weighted meshes, the exporter creates identity joint nodes named by
  XMPR node hashes. This preserves skin weights in a common model format while
  keeping the bind-pose geometry stable. It is intentionally not claiming that
  AGE PSP MBN inverse-bind matrices or animation channel space are solved.
- Integrated glTF export into `age_asset_pipeline.py`. Static model export now
  writes OBJ, MTL, `*.weights.json`, `*.gltf`, and `*.bin`.
- Structural validation:
  `ms008000_p000.xc` -> 12 glTF meshes, 5 textures, 12 skins, 32 identity
  joint nodes, 10473 weighted vertices, max 1 influence, JOINTS/WEIGHTS
  present, `.bin` length matches `buffers[0].byteLength`.
  `ue001000_p000.xc` -> 5 glTF meshes, 5 textures, 5 skins, 24 identity joint
  nodes, 3562 weighted vertices, max 2 influences, JOINTS/WEIGHTS present,
  `.bin` length matches JSON byte length.
  `map\b0000.xc` -> 74 glTF meshes, 18 textures, 0 skins, 0 weighted vertices,
  no JOINTS/WEIGHTS as expected for static map meshes, `.bin` length matches.
- Regression result: 12 unit tests pass, including the new glTF test; modified
  Python files compile.

### 23:41 +08:00 - Static model catalog and broader samples

- Added `tools\research\age_static_model_catalog.py`. It reads the full
  `psp_xc_model_survey_all.json` survey and writes:
  `outputs\manifests\psp_static_model_catalog.json` and
  `docs\STATIC_MODEL_CATALOG.md`.
- Catalog result: 2,391 PRM-bearing archives, 24,103 PRMs, 5,567,120 decoded
  vertices, 1,032 archives with active XPVB slot 7 weights, and 4,176 weighted
  PRMs. This catalog step does not extract binary assets.
- Largest static categories by decoded vertices:
  map 311 archives / 6,989 PRMs / 1,942,282 vertices / 0 weighted archives;
  mobile_suit 453 archives / 1,261 PRMs / 901,274 vertices / 436 weighted
  archives; human_or_npc 407 archives / 1,995 PRMs / 718,347 vertices / 406
  weighted archives; ue_unit 151 archives / 863 PRMs / 584,951 vertices / 142
  weighted archives; vehicle_or_ship 3 archives / 20 PRMs / 3,042 vertices.
- Additional static pipeline validation, still with animation disabled:
  `ue033100_p000.xc` -> 9 textures, 13 meshes, 9 materials, 7,429 weighted
  vertices, 7,956 weight records, 13 glTF skins.
  `hu254200_p000.xc` -> 2 textures, 5 meshes, 2 materials, 2,664 weighted
  vertices, 3,470 weight records, 5 glTF skins.
  `bs002000_p000.xc` -> 2 textures, 7 meshes, 2 materials, 0 weighted
  vertices, 0 weight records, textured unskinned glTF.
- Regression result: 14 unit tests pass, including new catalog tests; modified
  Python files compile.

### 23:46 +08:00 - glTF uses static MBN bind nodes when available

- Updated `age_gltf_tool.py` so static glTF skins use `.mbn` bind transforms
  and inverse-bind matrices when XMPR node hashes match MBN bone IDs. Missing
  hashes still fall back to identity nodes. No action files are parsed or
  executed.
- Pipeline now passes the extracted model directory as `mbn_root`; standalone
  CLI accepts `--mbn-root`.
- Validation:
  `ms008000_p000.xc` -> 12 meshes, 12 skins, 30 unique joint nodes, 45 MBN
  bind nodes available, 0 missing MBN hashes, 10,473 weighted vertices.
  `hu254200_p000.xc` -> 5 meshes, 5 skins, 19 unique joint nodes, 23 MBN bind
  nodes available, 0 missing MBN hashes, 2,664 weighted vertices.
  `ue033100_p000.xc` -> 13 meshes, 13 skins, 51 unique joint nodes, 13 MBN
  bind nodes available, 51 missing MBN hashes, 7,429 weighted vertices. This
  suggests some UE skeleton data may live in a companion/global archive.
- Added unit coverage for MBN-backed glTF joint node matrices.
- Regression result: 15 unit tests pass; modified Python files compile.

### 23:53 +08:00 - Companion skeleton archive support

- Added `tools\research\age_mbn_survey.py` to scan XPCK archives for `.mbn` bone IDs
  without extracting binary assets.
- Survey command:
  `python tools\research\age_mbn_survey.py <PSP_RESOURCE_ROOT> --extensions
  .xc --hash-file outputs\manifests\ue033100_missing_mbn_hashes.txt --json
  outputs\manifests\psp_xc_mbn_survey_ue033100_missing.json`.
- MBN survey result: 3,673 `.xc` archives scanned, 2,426 archives with MBN,
  41,596 MBN records, 12,766 unique bone hashes. All 51 missing
  `ue033100_p000` hashes were found. Best match:
  `chr\ue000012\ue000012_p000.xc` contains all 51 missing hashes.
- Extended `age_gltf_tool.py` to accept multiple `--mbn-root` paths and merge
  static bind poses. Extended `age_asset_pipeline.py` with
  `--skeleton-archive`; the archive is extracted under `outputs\pipeline\...\skeletons`
  and used only for static MBN bind nodes.
- Validation:
  `ue033100_p000.xc` with `--skeleton-archive ue000012_p000.xc` -> 13 meshes,
  13 skins, 56 unique joint nodes, 82 MBN bind nodes available, 0 missing MBN
  hashes, 7,429 weighted vertices, max 2 influences. Animation candidates
  remain 0.
- Regression result: 17 unit tests pass; modified Python files compile.

### 23:57 +08:00 - Survey-driven skeleton selection

- Enhanced `age_mbn_survey.py` with `archive_match_candidates` and
  `greedy_archive_cover`. The UE033100 MBN survey now ranks skeleton archive
  candidates and records a minimal cover set.
- For UE033100, top candidate and greedy cover are both
  `chr\ue000012\ue000012_p000.xc`: 51/51 requested hashes, 100% coverage,
  69 MBN files.
- Added `--skeleton-survey` to `age_asset_pipeline.py`. It reads
  `greedy_archive_cover`, extracts the recommended skeleton archive(s), and
  uses them as extra MBN roots for static glTF skin export.
- Validation:
  `ue033100_p000.xc --skeleton-survey psp_xc_mbn_survey_ue033100_missing.json`
  -> one skeleton archive auto-selected (`ue000012_p000.xc`), 0 missing MBN
  hashes, 82 MBN bind nodes, 56 unique joint nodes, 7,429 weighted vertices,
  animation candidates 0.
- Regression result: 19 unit tests pass; modified Python files compile.

## 2026-06-09

### 00:21 +08:00 - Phase summary checkpoint

- Research target remains `E:\research\Gundam_Breaker_Mobile\USER_INTENT_FOR_GAME_ASSET_RESEARCH.md`:
  build a reproducible static asset workflow for AGE PSP that exports texture
  + model + material + weight data, without executing action files.
- Confirmed closed loop:
  XPCK extraction works; IMGP/XI textures export cleanly after PSP deswizzle
  fix; XMPR exports OBJ + MTL + PNG; XMPR weights export as JSON sidecar;
  static glTF exports weighted meshes.
- Static bind data status:
  local `.mbn` bind nodes are wired into glTF when hashes match. Companion
  skeleton lookup works through MBN survey. `ue033100_p000` now resolves all 51
  previously missing hashes through `ue000012_p000.xc`.
- Broad coverage status:
  static catalog covers 2,391 PRM archives / 24,103 PRMs / 5,567,120 decoded
  vertices. Weighted assets confirmed across mobile suits, human/NPC, and UE
  units. Map assets export as unskinned textured meshes.
- Current gap:
  skeleton companion discovery is proven, but not yet batch-applied across more
  UE-family archives. Real animation playback/import remains deferred on
  purpose.
- GitHub-backed tooling already used and documented:
  `studio_eleven`, `StudioElevenLib`, `Metanoia`, `openTri`; no AGE PSP
  end-to-end extractor found, so local tools remain primary path.

### 00:32 +08:00 - Scope checkpoint: map-model conversion next

- Current static-model status is strong enough to treat character-family output
  as usable for this phase: sampled MS, UE, and human/NPC archives already
  export texture + model + UV + weight + bind-bone data.
- The next focused task is map-model conversion quality, not animation. Map
  archives already export textured static meshes, but texture correctness is
  still uncertain.
- Working hypothesis: the remaining map issue may be in one or more of these
  areas: texture decode, texture/material binding, UV interpretation, or
  triangle-strip reconstruction.
- Next comparison step should use more map samples plus emulator/reference
  evidence before changing decode logic or making stronger claims.

### 00:42 +08:00 - Map batch validation and swizzle comparison

- Added `tools\research\age_map_validation.py`. It batch-runs map `.xc` archives through
  the existing static pipeline and writes:
  `map_validation_report.json`, `MAP_VALIDATION_REPORT.md`, and
  `map_validation_viewer.html`.
- Added unit coverage in `tools\tests\test_age_map_validation.py` for summary
  aggregation and viewer/report output.
- Validated seven representative map-family samples:
  `b0000`, `b0000sky`, `b0501`, `t5101`, `e3108`, `p0012`, and `m01`.
- Batch summary:
  `b0000` -> 18 textures, 43 materials, 18 resolved `map_Kd`, 74 meshes.
  `b0000sky` -> 1 texture, 1 material, 1 resolved `map_Kd`, 1 mesh.
  `b0501` -> 13 textures, 16 materials, 12 resolved `map_Kd`, 56 meshes.
  `t5101` -> 13 textures, 20 materials, 13 resolved `map_Kd`, 49 meshes.
  `e3108` -> 48 textures, 53 materials, 48 resolved `map_Kd`, 63 meshes.
  `p0012` -> 10 textures, 12 materials, 10 resolved `map_Kd`, 25 meshes.
  `m01` -> 9 textures, 11 materials, 9 resolved `map_Kd`, 26 meshes.
- All sampled map exports remain unskinned static output: zero weights and zero
  skins in the emitted glTF summaries.
- Textured viewer evidence now exists under:
  `outputs\map_validation\batch_20260609\map_validation_viewer.png`,
  plus direct two-sample comparison screenshots:
  `outputs\map_validation\batch_20260609_swizzled_compare\map_validation_viewer.png`
  and
  `outputs\map_validation\batch_20260609_tiled_compare\map_validation_viewer.png`.
- The direct swizzle-vs-tiled comparison materially strengthens the current
  texture conclusion: `psp-swizzled` keeps `b0000` labels readable and
  `e3108` architectural textures coherent, while `tiled` visibly scrambles
  both samples. Remaining map uncertainty now leans more toward unresolved
  material bindings, UV coverage, or inferred topology than texture layout.

### 00:53 +08:00 - Map risk narrowed: swizzle confirmed, unresolved visuals remain

- Extended `age_map_validation.py` so reports now classify:
  unresolved collision-like materials, aux-like materials, visual unresolved
  materials, effect-like visual unresolved materials, plain visual unresolved
  materials, and absent-UV collision/non-collision meshes.
- Re-ran the first seven-sample batch and added an extra eight-sample
  `b/sky` batch:
  `b0101`, `b0104sky`, `b0201`, `b0301sky`, `b0601`, `b0804sky`, `b1001`,
  `b1401sky`.
- Combined sampled-map result is now 15 archives.
- Strong negative result on UV risk:
  all sampled absent-UV meshes are collision-like helpers. `15/15` samples have
  zero non-collision absent-UV meshes.
- Strong positive result on sky maps:
  `5/5` sampled sky archives have zero unresolved visual materials.
- Remaining map issue is now better localized:
  among 10 sampled non-sky archives, 5 have only effect-like unresolved visual
  materials, while 5 still have at least one plain unresolved visual material.
- Current highest-value unresolved plain visual material set:
  `b0000.b0000g16-`, `b0000.b0000g17-`,
  `b0101.b0101g07-a-`, `b0101.b0101g10-a-z0_a-`, `b0101.b0101g11-`,
  `b0601.b0601g10-`, `b0601.b0601g12-a-`,
  `e3108.e3108b25-`, `e3108.e3108g05-`,
  `p0012.p0012g03-`, `p0012.p0012g04-`.
- This materially changes the map diagnosis: PSP texture swizzle is no longer
  the leading problem. Remaining work should focus on unresolved material
  binding semantics for specific non-sky materials, then topology/render
  verification.

### 00:57 +08:00 - Map unresolved-material severity ranking

- Extended `age_map_validation.py` again so reports now record plain unresolved
  face counts and face ratios, not just material counts.
- This produced a much better priority signal for remaining map work.
- Current sampled plain unresolved face coverage:
  `b0101` -> 2477 / 7121 faces (`34.78%`)
  `p0012` -> 526 / 2525 faces (`20.83%`)
  `b0601` -> 745 / 6392 faces (`11.66%`)
  `e3108` -> 186 / 8573 faces (`2.17%`)
  `b0000` -> 8 / 2136 faces (`0.37%`)
- `b0501`, `t5101`, `m01`, `b0201`, and `b1001` now look lower-risk from a
  plain-material perspective because their remaining unresolved visuals are
  effect-like only.
- New practical priority order for map binding research:
  `b0101` first, then `p0012`, then `b0601`, then `e3108`, with `b0000`
  treated as a small residual case rather than a main blocker.

### 01:03 +08:00 - Mesh-name fallback reduced one map effect material

- Added `apply_mesh_name_texture_candidates()` to `age_material_bind.py`.
- The new fallback only activates when TXP ownership already points at the
  material but no same-stem `.xi` and no direct texture-name candidate were
  found.
- It backfills texture candidates from mesh names that already match
  resource-order image candidates.
- Real-data validation on `b0101` resolved `b0101.b0101s01-tm-a-` to
  `textures/000.png` with
  `texture_image_binding_confidence = mesh_name_resource_order_candidate`.
- Sampled `b0101` improved from `13 -> 14` resolved materials and from
  `5 -> 4` unresolved visual materials.
- This did not change the `34.78%` plain unresolved face ratio for `b0101`,
  so the remaining map blocker is still the plain unresolved set
  (`g07/g10/g11`-side cases), not texture swizzle and not the already-reduced
  effect material.

### 01:07 +08:00 - Main map batch rerun shrank the plain-unresolved set again

- Re-ran the main `age_map_validation.py` batch on:
  `b0000`, `b0000sky`, `b0501`, `t5101`, `e3108`, `p0012`, and `m01`
  after the mesh-name/resource-order fallback landed in `age_material_bind.py`.
- `p0012.p0012g03-` is now resolved through mesh-name backfill
  (`a_yuka101`, `a_yuka201`), so `p0012` improved from `10 -> 11` resolved
  materials and from `2 -> 1` unresolved visual materials.
- `b0601` is no longer part of the plain-unresolved group; its remaining
  unresolved visuals are effect-like only.
- Current sampled plain unresolved face coverage is now:
  `b0101` -> 2477 / 7121 faces (`34.78%`)
  `p0012` -> 438 / 2525 faces (`17.35%`)
  `e3108` -> 186 / 8573 faces (`2.17%`)
  `b0000` -> 8 / 2136 faces (`0.37%`)
- Current sampled non-sky split is:
  `4/10` with plain unresolved visuals,
  `5/10` with effect-like-only unresolved visuals,
  `1/10` (`b0201`) with zero unresolved visuals.
- This makes the next plain-texture priority set smaller and cleaner:
  `b0101`, then `p0012`, then `e3108`, then `b0000`.
- The remaining plain unresolved cases now break into two investigation types:
  `b0101` already has mesh-name texture candidates but no in-archive `.xi`
  match, while `p0012g04`, `e3108b25/g05`, and `b0000g16/g17` still lack any
  usable texture candidate and need broader resource comparison first.

### 01:18 +08:00 - Full non-chr map survey completed

- Added `age_map_survey.py` so the repo can run large-sample map validation
  without keeping every extracted sample on disk.
- Ran the survey on all non-`chr` map archives under
  `<PSP_RESOURCE_ROOT>\map` with `psp-swizzled` layout and cleanup.
- Coverage/result:
  `285` samples total,
  `193` visually clean,
  `54` plain unresolved,
  `33` effect-like-only unresolved,
  `5` failed `fe*` archives.
- The `5` failures are all separate conversion bugs, not texture verdicts:
  `fe0001`, `fe0002`, `fe0003`, `fe0004`, and `fe5001`
  each stop on an `MBN parent cycle`.
- Successful survey samples show `0` unexpected weighted-vertex cases and
  `0` unexpected skin cases, which reinforces that map exports are staying
  static as intended.
- Group split from the survey:
  `sky` is mostly clean (`53/56` clean, `0` plain unresolved),
  `t` has the largest plain-problem count (`24`),
  `b` has `21` plain-problem archives,
  `p` has `3`,
  `e` has `6`.

### 01:21 +08:00 - Large-map-only compare set established

- Switched the next inspection set to large maps because small maps are harder
  to judge visually and create more ambiguity.
- Built a large-map risk batch:
  `e1101`, `b0101`, `b3205`, `b3104`, `t0201`, `e3108`.
- Built a large-map control batch:
  `t5201`, `t0901`, `e2104`, `b3003`.
- The large-map controls all export with `0` visual unresolved materials,
  which strengthens the current conclusion that PSP swizzle/layout decode is
  broadly correct on large archives too.
- Large-map risk results:
  `e1101` -> `81.09%` plain unresolved faces,
  `b3205` -> `43.18%`,
  `b0101` -> `34.78%`,
  `b3104` -> `33.84%`,
  `t0201` -> `6.93%`,
  `e3108` -> `2.17%`.
- Current large-map failure classes:
  `b0101` = mesh-name candidate exists but no in-archive `.xi` target;
  `e1101`, `b3104`, `t0201`, `e3108` = TXP owner confirmed but still no
  usable texture candidate;
  `b3205` = plain unresolved materials without TXP owner
  (`resource_string_only` path).
- This means next map research should stay on large-map families first and pick
  the next binding heuristic against one of those three failure classes.

### 01:24 +08:00 - e110x family compare narrowed the large-map target further

- Ran a same-family compare on `e1101` through `e1105`.
- `e1102`, `e1103`, and `e1104` are visually clean.
- `e1105` has only a small residual plain issue:
  `276 / 5099` faces (`5.41%`) on `e1105.e1105g23-a-a-`.
- `e1101` remains the real outlier:
  `5986 / 7382` faces (`81.09%`) across
  `e1101.e1101g01-`, `e1101.e1101g01-add-`, and `e1101.e1101g02-a-a-`.
- This is useful because it argues against a blanket `e11*` texture-decode
  problem. The next large-map binding pass should treat `e1101` as a specific
  family-local target, with `e1105` as a small related residual, not as proof
  that the whole `e11*` group is broken.

### 01:27 +08:00 - Static map glTF export no longer depends on bad MBN data

- Updated `age_gltf_tool.py` so MBN bind data is only loaded when a mesh
  actually has referenced joint weights.
- This removes a false blocker for static map archives with broken or cyclic
  `.mbn` files.
- Added regression coverage in `test_age_gltf_tool.py` to assert that
  unweighted meshes skip MBN loading entirely.
- Verified on the previous failure set:
  `fe0001`, `fe0002`, `fe0003`, `fe0004`, and `fe5001`
  now all export as clean static textured maps with `0` visual unresolved
  materials and `0` skins.

### 01:29 +08:00 - Full map survey refreshed after FE fix

- Re-ran the full non-`chr` map survey after the unweighted-MBN fix.
- Updated full-survey totals:
  `285` samples total,
  `198` visually clean,
  `54` plain unresolved,
  `33` effect-like-only unresolved,
  `0` failed samples.
- `fe` is now fully clean in the survey (`5/5` clean).
- The large-map priority set does not change after this fix, which is useful:
  the FE issue was a conversion-path bug, while the remaining main map risk is
  still large-map material binding on `e1101`, `b3205`, `b0101`, `b3104`,
  `t0201`, and `e3108`.

### 21:38 +08:00 - Large-map screenshots written to previews

- Captured model-viewer screenshots for the current large-map batches:
  `outputs/previews/map_large_focus_viewer_20260609.png` and
  `outputs/previews/map_e110x_family_viewer_20260609.png`.
- Visual check: screenshots are nonblank and show real textured model-viewer
  cards. Large control maps remain coherent; risk maps still show white/gray
  unresolved material regions.
- This confirms the next work should stay on large, visually inspectable map
  samples instead of small ambiguous maps.

### 21:45 +08:00 - Stable entrypoint and workflow doc started

- Added `tools/age_start.py` as the short command entrypoint. It delegates to the
  existing focused tools instead of replacing them.
- Added `docs/LEVEL5_ASSET_WORKFLOW.md` with current date, Level-5 file
  architecture, data/source boundaries, compression/decompression path,
  extraction commands, GitHub repos used, output layout, and next list/index
  target.
- README now links the workflow doc and `tools/age_start.py`.

### 21:46 +08:00 - Additional large-map batch exported

- Selected 12 large `.xc` archives by archive size, excluding the previous
  risk/control/e110x batches:
  `b2003`, `m01`, `b8501`, `t0703`, `t0704`, `t0401`, `t1102`, `t1106`,
  `b3201`, `e2107`, `b0601`, and `b0803`.
- Exported them through the stable entrypoint:
  `python .\tools\age_start.py map validate ... --out-root .\outputs\map_validation\large_extra_20260609 --overwrite`.
- Wrote screenshots:
  `outputs/previews/map_large_extra_viewer_20260609.png` and
  `outputs/previews/map_large_extra_viewer_20260609_full.png`.
- Batch summary: all 12 exports completed. Clean/helper-only samples include
  `b2003`, `t0703`, and `e2107`; plain residuals are small on `b8501`,
  `t0704`, `t1102`, `t1106`, `b3201`, and `b0803`; `m01`, `t0401`, and
  `b0601` are effect-only unresolved.

### 21:48 +08:00 - Output cleanup policy added

- Added `outputs/README.md` to define generated-output layout and safe cleanup
  rules.
- Removed the cropped duplicate
  `outputs/previews/map_large_extra_viewer_20260609.png`; kept
  `outputs/previews/map_large_extra_viewer_20260609_full.png`.
- No validation reports, manifests, or source-like research evidence were
  deleted.

### 21:57 +08:00 - Model/texture asset index created

- Added `tools/age_asset_index.py` and wired it into `tools/age_start.py index`.
- Generated:
  `outputs/manifests/AGE_ASSET_INDEX.md`,
  `outputs/manifests/age_asset_index.compact.json`, and
  `outputs/manifests/age_asset_index.json`.
- Indexed `<PSP_RESOURCE_ROOT>` without extracting binary assets.
- Result: `4529` XPCK archives, `0` parse errors, `2364` model archives,
  `2710` texture archives, `2343` archives containing both model and texture
  files, `23880` `.prm` model entries, `9170` `.xi` texture entries, and
  `46760` material parameter entries.
- Existing pipeline exports are linked into the index when matching
  `_asset_pipeline_manifest.json` files are present under `outputs/`.





