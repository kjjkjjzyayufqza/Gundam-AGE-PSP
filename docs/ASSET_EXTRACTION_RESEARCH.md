# Gundam AGE PSP Asset Extraction Research

## Goal

Build a documented, reproducible local workflow for extracting Gundam AGE PSP
static assets into common formats, especially PNG textures and OBJ models with
MTL material bindings. The authoritative goal statement is:

- `E:\research\Gundam_Breaker_Mobile\USER_INTENT_FOR_GAME_ASSET_RESEARCH.md`

Input data inspected in this pass:

- `<AGE_PSP_WORK_ROOT>`
- `<UNPACKED_RESOURCE_ROOT>`

All created files are under:

- `E:\research\Gundam-AGE-PSP`

## Current Status

| Area | Status | Evidence |
|---|---|---|
| CPK | Already unpacked by user | Source tree contains `PSP_GAME` and `资源解包` |
| XPCK archives | Confirmed and parsed | `.xc`, `.xb`, `.xa`, `.xv` begin with `XPCK`; tool lists names, offsets, sizes |
| Texture export | Working for sampled `.xi` / `IMGP` files | `ms008000_p000.xc` exports five coherent 16-color PNGs; indexed data is PSP 16-byte x 8-row deswizzled |
| Level-5 compression | Implemented for observed methods | no compression, LZ10, Huffman4, Huffman8, RLE, zlib |
| Resource tables | Partly decoded | `RES.bin` decompresses to `CHRP00` and readable part/resource names |
| Material/resource params | Initial binding working | `age_param_probe.py` records raw params; `age_material_bind.py` links PRM material names to TXP/MTR/ATR via CRC32-confirmed CHRP00 strings |
| Model data | Working for a complete sampled mobile suit | `ms008000_p000.xc` exports 12 PRMs as a coherent 10,473-vertex OBJ in bind pose; float32x3/float32x4 samples also export |
| Weight sidecar | Working for sampled skinned meshes | `*.weights.json` records XPVB slot 7 raw weights, normalized weights, OBJ vertex indices, and XMPR node hashes; `ms008000`, `ms007000`, and `ue001000` have zero unmapped weight records |
| Static weighted glTF | Working for sampled skinned and static meshes | `*.gltf` plus `*.bin` exports POSITION, TEXCOORD_0, material textures, JOINTS_0/WEIGHTS_0, and MBN bind skin nodes where hashes match; no action files are executed |
| Static model catalog | Working from full survey | `docs/STATIC_MODEL_CATALOG.md` summarizes 2,391 PRM-bearing archives, 24,103 PRMs, 5,567,120 decoded vertices, and 1,032 weighted archives |
| Map textured validation | Partly working for sampled map families | `age_map_validation.py` batch-exports fifteen real map samples across `b`, `sky`, `t`, `e`, `p`, and `m`; `psp-swizzled` renders coherent thumbnails while `tiled` visibly scrambles `b0000` and `e3108`, but several non-sky samples still retain unresolved visual materials |
| Animation pose | Experimental, not a required static-output step | Node matching and MBN bind parsing work, but complete `ms008000` pose previews still separate parts; static bind-pose OBJ is the reliable output |
| One-command workflow | Working for sampled archives/directories | Default `from-character` exports static XPCK contents, PNG, OBJ/MTL, glTF/bin, weight sidecar, and manifests; animation requires explicit `--animation-policy best|all` |
| Visual validation | Working for the primary static sample | `ms008000_static_recommended.png` shows a coherent full mechanical humanoid; OBJ references all five existing PNGs |

Texture extraction is currently practical. Model extraction is now split into
two confidence levels:

- Confirmed for sampled float32 XPVB buffers: vertex positions and UV0 decode,
  including float32x3 and map-style float32x4 streams where xyz are used.
- Confirmed for sampled skinned PSP 16-bit XPVB buffers: signed normalized
  bind-pose x3 positions, unsigned normalized x2 UVs, and implicit 8-byte node
  weights. `ms008000` proves that the unanimated values already form a
  meaningful, usable static mesh. The current OBJ export is paired with a
  deterministic `*.weights.json` sidecar because OBJ itself cannot store skin
  weights. `age_gltf_tool.py` also exports static glTF with JOINTS/WEIGHTS
  attributes and static MBN bind nodes where available, so the weights are
  carried in a common model format without executing animation data.
- Still experimental: face/topology reconstruction and additional unnamed
  XPVB attribute semantics.
- Visual classification matters: `fn024000`, `fn001000`, and `fn001001`
  previews are distributed marker-like octahedra. `bs001000_p000` previews as
  a craft/vehicle-like model. `ms008000_p000` is the confirmed complete
  mobile-suit sample.

## External References Used

- XPCK is a Level-5 archive format used by `.xc` and related extensions:
  <https://yokai.chaoticpumpk.in/file-formats/xc/>
- Kuriimu2 is a plugin-based game modding toolkit with Level-5 XPCK source:
  <https://github.com/FanTranslatorsInternational/Kuriimu2>
- Kuriimu XPCK support source confirms the shifted XPCK header/entry layout:
  <https://raw.githubusercontent.com/IcySon55/Kuriimu/master/src/archive/archive_level5/XpckSupport.cs>
- Kuriimu2 Level-5 compression source confirms the method bits and size field:
  <https://raw.githubusercontent.com/FanTranslatorsInternational/Kuriimu2/master/plugins/Level5/plugin_level5/Compression/Level5Compressor.cs>
- A Gundam AGE translation discussion notes that `.xi` uses unsupported
  `IMGP` textures with 4/8-bit indexed PSP palettes:
  <https://www.reddit.com/r/Gundam/comments/1cv3tlx/gundam_age_universe_accel_translation_project/>
- StudioEleven / StudioElevenLib Level-5 tools by Tiniifan:
  <https://github.com/Tiniifan/studio_eleven> and
  <https://github.com/Tiniifan/StudioElevenLib>
- Pingouin Level-5 archive manager:
  <https://github.com/Tiniifan/Pingouin>
- Level5ResourceEditor:
  <https://github.com/Tiniifan/Level5ResourceEditor>
- Level-5 material helper:
  <https://github.com/Tiniifan/level5_material>
- Metanoia, a historical Level-5 model/image tool referenced by StudioEleven:
  <https://github.com/Ploaj/Metanoia>
- Gundam AGE PPSSPP HD texture pack, used only as a visual/reference corpus:
  <https://github.com/SIEBEN5106/Gundam-AGE-PSP-Texture-Pack>
- PPSSPP GE documentation records PSP vertex component formats, including
  signed 8/16-bit/f32 positions and unsigned 8/16-bit/f32 texture coordinates:
  <https://www.ppsspp.org/docs/psp-hardware/gpu/ge-overview/>
- PPSSPP image format documentation records PSP CLUT texture formats and
  RGBA8888 byte layout:
  <https://www.ppsspp.org/docs/psp-hardware/gpu/image-formats/>
- YAPSPD documents the PSP `VTYPE` bit layout for texture, color, normal,
  position, weight, index, morph count, and through-mode flags:
  <https://uofw.github.io/upspd/docs/hardware/psp_doc.pdf>

## GitHub Tools Used

Per the project requirement, existing GitHub tools were downloaded and tried
before extending local scripts. Local clones are under
`external_tools\github\`; generated game assets remain under `outputs\`.

| Tool | Local revision | What was used | Result on Gundam AGE PSP samples |
|---|---|---|---|
| [Tiniifan/studio_eleven](https://github.com/Tiniifan/studio_eleven) | `a06f35d` | Blender importer, `formats/mbn.py`, XMPR mesh creation, animation channel conversion, and image helpers inspected | Confirms PRM positions are inserted directly as bind-pose mesh vertices; MBN builds the armature separately; exact XMTN pose-channel conversion remains to be reproduced |
| [Tiniifan/StudioElevenLib](https://github.com/Tiniifan/StudioElevenLib) | `6d3e59a` | CLI `StudioEleven.exe`; `XPVBReader`, `XPVIReader`, `XMPRReader`, `IMGCReader`; `AnimationManager` called directly by the local .NET probe | Source directly informed `age_xmpr_tool.py`; `IMGCReader` was used for tile-table comparison; the local wrapper successfully parses AGE PSP XMTN/V2 `.mtn2` files into location, rotation, and scale tracks |
| [Tiniifan/Pingouin](https://github.com/Tiniifan/Pingouin) | `55f20de` | README/source inspected | GUI archive manager supports `XPCK`; no CLI path was useful for this automated workflow |
| [Tiniifan/Level5ResourceEditor](https://github.com/Tiniifan/Level5ResourceEditor) | `662bc83` | README/source inspected | Targets 3DS-style `RES.bin`/`XRES`; AGE PSP `CHRP00` resource payload differs |
| [Tiniifan/level5_material](https://github.com/Tiniifan/level5_material) | `667d19c` | Ran `level5_material.py -d` on AGE `000.mtr` | Failed with invalid header; AGE PSP `MTRP00` is not this tool's expected `.mtr` |
| [Ploaj/Metanoia](https://github.com/Ploaj/Metanoia) | `225b4ee` | `Level5_XI.cs` and Level-5 PRM/animation source inspected | Historical XI reference; confirms PRM slot 7 weights and slot 8 indices, and supplies an alternate inverse-quaternion convention for diagnostics |
| [albe/openTri](https://github.com/albe/openTri) | `c61d458` | `triImage.c` and `triTexman.c` PSP swizzle/unswizzle source inspected | Confirms PSP image swizzle is byte-width based and uses 16-byte x 8-row blocks; this directly informed the IMGP black-speckle fix |
| [SIEBEN5106/Gundam-AGE-PSP-Texture-Pack](https://github.com/SIEBEN5106/Gundam-AGE-PSP-Texture-Pack) | `237c825` | README, repository layout, and PPSSPP replacement-texture scope inspected | Reference corpus, not an extractor; confirms all MS and weapon textures were captured/upscaled, but provides no XPCK/XMPR/IMGP converter |

Concrete command results:

- `StudioEleven.exe arc-open ...bs001000_p000.xc` and
  `...ga_ws_13_0020.xb` identify both files as `XPCK`, but `ls /` and `ls .`
  currently fail with `Virtual directory '' not found`.
- `StudioEleven.exe mesh-info outputs\samples\bs001000_p000_xc\000.prm`
  fails with an index-out-of-range error because AGE PSP `XPVI` is only a
  12-byte primitive header in sampled files, not the compressed index payload
  expected by StudioElevenLib.
- `StudioEleven.exe res-info outputs\samples\bs001000_p000_xc\RES.dec.bin`
  fails on the PSP `CHRP00` resource payload.
- `level5_material.py -d outputs\samples\bs001000_p000_xc\000.mtr` fails
  because the AGE file starts with PSP `MTRP00`, not the expected material
  header.
- `StudioElevenAnimationProbe` successfully parsed sampled `fn024000_s240`,
  `fn024000_s241`, and `fn024000_v360` `.mtn2` files through
  `StudioElevenLib.Level5.Animation.AnimationManager`; the samples contain 24,
  24, and 109 frames respectively, each with three SRT tracks.
- A 2026-06-08 GitHub/Exa search for a Gundam AGE PSP XPCK/XMPR/IMGP
  converter found no dedicated extractor. GitHub code search could not run
  because the configured MCP lacked authentication; repository search and
  Exa found only the PPSSPP texture pack above.

Raw command logs are kept in `outputs\manifests\studioeleven_arcopen_*.txt`
for later comparison.

## File Architecture Observed

The extracted game tree has many Level-5-style resources:

| Extension | Count in `资源解包` | Current interpretation |
|---|---:|---|
| `.xc` | 3673 | XPCK archive; usually character/map/model resource package |
| `.xb` | 135 | XPCK archive; battle package with nested `.xc/.xa/.xv` |
| `.xa` | 365 | XPCK archive; animation/effect package in sampled data |
| `.xv` | 189 | XPCK archive; camera/motion package in sampled data |
| `.xi` | 744 | `IMGP` texture files inside XPCK archives |
| `.prm` | inside `.xc` | `XMPR` model candidate |
| `.mtr`, `.atr`, `.txp` | inside `.xc` | material/attribute/texture parameter candidates |
| `RES.bin` | inside `.xc/.xa/.xv` | Level-5-compressed resource table |
| `.mtn2`, `.mtninf` | inside animation packages | motion/animation candidates |

Example: `<PSP_RESOURCE_ROOT>\btl\ga_ws_13_0020.xb`
is an XPCK archive containing six nested XPCK files:

- `fn036000_v130.xc`
- `fn036000_p000.xc`
- `ga_ws_13_0020.xa`
- `esga0105a.xc`
- `ms000001_v130.xv`
- `ms000001_v130.xc`

Example: `bs001000_p000.xc` contains `000.xi`, `001.xi`, several
`*.prm`, `*.mbn`, `*.mtr`, `*.atr`, `*.txp`, `*.cmn`, and `RES.bin`.

## Resource and Material Parameters

`RES.bin` is Level-5 compressed in sampled character packages. After
decompression, the payload starts with `CHRP00` and contains useful strings for
binding model parts, materials, and textures.

Sample `CHRP00` strings:

| Source | Strings observed |
|---|---|
| `bs001000_p000_xc\RES.dec.bin` | `DefaultLib.bs001000_01-`, `DefaultLib.bs001000_01-s0-`, `bs001000_01`, `bs001000_02`, `bs001000_output.d_gene`, `bs001000_output.d_body`, `bs001000_output.d_wing`, `bs001000_output.d_obj`, `bs001000_output.d_leg`, `bs001000_output.d_head`, `bs001000_output.d_hand` |
| `fn024000_p000_xc\RES.dec.bin` | `DefaultLib.fn024000`, `fn024000_01`, `fn024000_output.fn024000_03`, `fn024000_output.fn024000_01`, `fn024000_output.fn024000_02`, `fnl01` through `fnl20` |
| `map_b0000_xc\RES.bin` | `b0000.b0000g11-mt-`, `b0000.b0000g11-mt-_texproj0`, `b0000g11`, `g0001` through `g0013`, collision/helper strings such as `col_01` |

Small parameter files observed:

| File type | Sample size | Current interpretation |
|---|---:|---|
| `.mtr` | 44-48 bytes | `MTRP00` material parameter block; older GitHub `level5_material` parser is not compatible |
| `.atr` | 40 bytes | `ATRP01` attribute/render parameter block |
| `.txp` | 36 bytes | texture parameter block with two 32-bit hash/id words and two float UV scale candidates at offset `0x1C`; sampled values are `[1.0, 1.0]` |
| `.cmn` | 12 bytes | compact per-part/common parameter; fields still unnamed |

`age_param_probe.py` exports these observations to JSON without assigning
unsupported field names. Current manifests:

- `outputs\manifests\bs001000_param_probe.json`: 17 files, 0 failures.
- `outputs\manifests\fn024000_param_probe.json`: 12 files, 0 failures.

`age_material_bind.py` builds a higher-level binding manifest. Confirmed
relationship: the first two 32-bit words in `.txp` are CRC32 values of
`CHRP00` strings. Once a `.txp` owner is identified, matching numbered stems
such as `001.txp -> 001.xi` are used as the preferred texture-image binding.

Observed TXP CRC32 matches:

| File | CRC32 match | Meaning |
|---|---|---|
| `bs001000_p000_xc\000.txp` | `0x075B1F34 -> DefaultLib.bs001000_01-` | material owner |
| `bs001000_p000_xc\000.txp` | `0x75326165 -> DefaultLib.bs001000_01-_texproj0` | texture projection |
| `bs001000_p000_xc\001.txp` | `0x21EEAE34 -> DefaultLib.bs001000_01-s0-` | material owner |
| `bs001000_p000_xc\001.txp` | `0xCCD63170 -> DefaultLib.bs001000_01-s0-_texproj0` | texture projection |
| `fn024000_p000_xc\000.txp` | `0xE6E53075 -> DefaultLib.fn024000` | material owner |
| `fn024000_p000_xc\000.txp` | `0x31DFFA01 -> DefaultLib.fn024000_texproj0` | texture projection |
| `map_b0000_xc\013.txp` | `0x4DA67084 -> b0000.b0000g11-mt-` | material owner |
| `map_b0000_xc\013.txp` | `0x9FF761FC -> b0000.b0000g11-mt-_texproj0` | texture projection |

Current material binding validation:

| Source | Materials | Meshes bound | Texture name candidates | Image file candidates |
|---|---:|---:|---|---|
| `bs001000_p000_xc` | 2 | 7/7 | `bs001000_01`, `bs001000_02` | `DefaultLib.bs001000_01- -> 000.xi`, `DefaultLib.bs001000_01-s0- -> 001.xi` by TXP/XI stem match |
| `fn024000_p000_xc` | 1 | 3/3 | `fn024000_01` | `DefaultLib.fn024000 -> 000.xi` by TXP/XI stem match |
| `map_b0000_xc` | 43 | 74/74 | map material strings such as `b0000.b0000g11-mt-` | 18 `map_Kd` texture paths resolved by TXP/XI stem match; remaining material records have no matching `.xi` in the archive |

The one-command pipeline also writes an MTL file next to the OBJ when texture
and material export are enabled. `usemtl` names come from PRM material names.
`map_Kd` paths point to exported PNGs. The pipeline prefers direct TXP/XI
numbered-stem matches and only falls back to resource-order texture candidates.

Current MTL validation:

| Pipeline | OBJ | MTL | Example `map_Kd` |
|---|---|---|---|
| `bs001000_from_dir_strip` | `models\bs001000_p000_strip.obj` | `models\bs001000_p000.mtl` | `DefaultLib.bs001000_01- -> ..\textures\000.png` |
| `fn024000_from_dir_strip` | `models\fn024000_p000_strip.obj` | `models\fn024000_p000.mtl` | `DefaultLib.fn024000 -> ..\textures\000.png` |
| `map_b0000_from_xpck_strip` | `models\map_b0000_strip.obj` | `models\map_b0000.mtl` | `b0000.b0000g11-mt- -> ..\textures\013.png` |

## XPCK Format

Confirmed against local files and Kuriimu source.

Header is little-endian:

| Offset | Type | Meaning |
|---:|---|---|
| `0x00` | char[4] | `XPCK` |
| `0x04` | u8 | file count low byte |
| `0x05` | u8 | low nibble is file count high nibble; high nibble is variant/flags |
| `0x06` | u16 | file info offset divided by 4 |
| `0x08` | u16 | compressed filename table offset divided by 4 |
| `0x0A` | u16 | data offset divided by 4 |
| `0x0C` | u16 | file info size divided by 4 |
| `0x0E` | u16 | compressed filename table size divided by 4 |
| `0x10` | u32 | data size divided by 4 |

Each file entry is 12 bytes:

| Field | Meaning |
|---|---|
| u32 | CRC/hash |
| u16 | offset into decompressed filename table |
| u16 + u8 | data offset divided by 4 |
| u16 + u8 | file size |

The filename table uses Level-5 compression. Local samples use LZ10 or no
compression.

## IMGP Texture Format

`IMGP` is not handled by Kuriimu's older `IMGA/IMGC/IMGV` plugins, but local
samples have a consistent enough structure for PNG export.

Confirmed fields:

| Offset | Meaning |
|---:|---|
| `0x00` | `IMGP` magic |
| `0x04` | version string, observed `00` |
| `0x0A` | format code, observed `0x10` for 8bpp and `0x15` for 4bpp |
| `0x0D` | bit depth, observed 4 or 8 |
| `0x0E` | pitch/padded width candidate |
| `0x10` | output width |
| `0x12` | output height |
| `0x1C` | data start, observed `0x58` |
| `0x38` | palette color count, observed 16 or 256 |
| `0x3A` | palette count, observed 1 |
| `0x40` | compressed palette block size |
| `0x44` | compressed tile table block size |
| `0x48` | compressed pixel block offset relative to data start |
| `0x4C` | compressed pixel block size |

The three blocks are:

1. Palette block: Level-5 compressed 4-byte colors.
2. Tile table: Level-5 compressed `u16` entries, with `0xFFFF` as an empty
   8x8 tile.
3. Pixel block: Level-5 compressed unique indexed 8x8 tile data.

The exporter now rebuilds the indexed byte stream from the tile table, then
applies PSP 16-byte x 8-row deswizzle before palette lookup. The earlier
exporter stopped after the tile-table rebuild and rendered the data as
row-major 8x8 tiles. That produced colored but visibly speckled textures:
sample `000.xi` had no true black pixels and no alpha-zero pixels, but the PSP
swizzled byte order scattered dark palette indices across the image.

`age_imgp_tool.py` defaults to `--pixel-layout psp-swizzled`. Use
`--pixel-layout tiled` only to reproduce the earlier no-deswizzle output, and
`--pixel-layout linear` for raw row-major experiments.

Validation:

| File | Exported size | Blocks | Result |
|---|---:|---|---|
| `bs001000_p000_xc\000.xi` | 256x128, 8bpp | Huffman4 palette/table + LZ10 pixels | 256-color mecha texture atlas; fixed by PSP 16x8 deswizzle |
| `bs001000_p000_xc\001.xi` | 32x32, 4bpp | uncompressed palette/table + LZ10 pixels | 16-color glow texture; fixed by PSP 16x8 deswizzle |
| `fn024000_p000_xc\000.xi` | 32x32, 8bpp | LZ10 palette + RLE table/pixels | 1-color placeholder-like texture |

## XMPR / XPVB Model Data

`.prm` files contain the probable model data.

Observed hierarchy:

- `XMPR` at file start
- `XPRM` sub-block near `0x40`
- `XPVB` inside `XPRM`
- `XPVI` later in the same `.prm`
- trailing Shift-JIS/ASCII part names such as `bs001000_output.d_body`

StudioElevenLib's `XMPRReader`, `XPVBReader`, and `XPVIReader` match the broad
container layout, but AGE PSP differs in important payload details.

Confirmed `XPVB` header fields:

| Offset in XPVB | Type | Meaning |
|---:|---|---|
| `0x00` | char[4] | `XPVB` |
| `0x04` | u16 | compressed attribute table offset |
| `0x06` | u16 | unknown block offset / attribute table end |
| `0x08` | u16 | compressed vertex buffer offset |
| `0x0A` | u16 | vertex stride |
| `0x0C` | u32 | vertex count |

The attribute table is 10 entries of 4 bytes:
`count, offset, size, type`. The vertex buffer is Level-5 compressed.

Sample float32 layout for `bs001000_p000_xc`:

| Slot | Meaning in current exporter | Attribute |
|---:|---|---|
| 0 | position float3 | `count=3`, `offset=12`, `size=12`, `type=2` |
| 1 | packed 4-byte value, likely color/weight-like | `count=8`, `offset=8`, `size=4`, `type=2` |
| 4 | UV0 float2 | `count=2`, `offset=0`, `size=8`, `type=2` |

Sample map float32 layout for `map_b0000_xc`:

| Slot | Meaning in current exporter | Attribute |
|---:|---|---|
| 0 | position float4, exported as xyz; sampled w values are `0.0` | `count=4`, `offset=0`, `size=16`, `type=2` |
| 4 | absent | `count=0`, `offset=0`, `size=0`, `type=0` |

Sample PSP 16-bit fixed layout for `ms008000_p000_xc` and `fn024000_p000_xc`:

| Slot | Meaning in current exporter | Attribute |
|---:|---|---|
| 0 | signed normalized int16 x3 (`value / 32768.0`); usable skinned bind-pose position | `count=15`, `offset=12`, `size=6`, `type=2` |
| 4 | unsigned normalized int16 x2 (`value / 32768.0`, V inverted); UV-like range | `count=14`, `offset=8`, `size=4`, `type=2` |
| 7 | 8-byte implicit node weights; sampled vertices are one-hot with `0x80` as full weight | `count=12`, `offset=0`, `size=8`, `type=2` |

Sample probe for `bs001000_p000_xc`:

| File | XPVB offset | XPVB data offset | Repeated candidate fields | XPVI offset |
|---|---:|---:|---|---:|
| `000.prm` | `0x54` | `0x2C` | `field04_hi=0x28`, `field08_hi=0x18` | `0x230` |
| `001.prm` | `0x54` | `0x2C` | same family | `0xAB0` |
| `006.prm` | `0x54` | `0x2C` | same family | `0x6CC` |

`age_xmpr_tool.py` now records geometry diagnostics in every model manifest:
bounds, unique-position count/ratio, inferred face count, exported face count,
non-degenerate and degenerate face counts, max triangle area, and a
`position_semantic` label. By default, OBJ export skips degenerate inferred
faces because PSP triangle strips often use them as strip connectors. Use
`--keep-degenerate-faces` only when auditing the raw inference.

Current validation:

| Source | Meshes | Decoded vertex records | Inferred strip faces | Exported non-degenerate faces | Geometry diagnostic |
|---|---:|---:|---:|---:|---|
| `bs001000_p000_xc` | 7 | 1436 | 1422 | 492 | `position_semantic=likely_position`; float32 positions have plausible model bounds |
| `ms008000_p000_xc` | 12 | 10473 | 10449 | 3738 | `position_semantic=skinned_bind_pose_position`; coherent full mobile-suit bind pose |
| `fn024000_p000_xc` | 3 | 1911 | 1905 | 320 | same skinned position format, but the asset itself is marker/effect-like |
| `map_b0000_xc` | 74 | 6099 | 5951 | 2136 | `position_semantic=likely_position`; includes 53 float32x3 meshes and 21 float32x4-as-xyz meshes |

Untextured preview evidence:

| Output | Preview result |
|---|---|
| `outputs\previews\bs001000_p000_strip.png` | Coherent craft/vehicle-like mechanical silhouette; 1436 vertices and 492 triangles |
| `outputs\previews\ms008000_static_recommended.png` | Coherent full mechanical humanoid; 10473 vertices and 3738 triangles |
| `outputs\previews\fn024000_character_auto_recheck.png` | Twenty distributed octahedron/marker clusters, not a complete character mesh |
| `outputs\previews\fn001000_character_auto_f7.png` | Small marker cluster |
| `outputs\previews\fn001001_character_auto_f7.png` | Small marker cluster |

### Weight Sidecar

`age_xmpr_tool.py export-obj` and `age_asset_pipeline.py` now write a
per-vertex weight sidecar next to every OBJ:

- `models\<name>_<triangulation>.weights.json`

The sidecar format is `age_xmpr_weights_v1`. It stores only decoded source
weight records, not animation output:

| Field | Meaning |
|---|---|
| `obj` | OBJ path that the sidecar indexes into |
| `weight_source_attribute_slot` | XPVB attribute slot, currently `7` |
| `node_table_source` | `XMPR node_hashes` |
| `mesh[].node_hashes` | per-PRM node hash table from XMPR |
| `mesh[].obj_vertex_start` | 1-based first OBJ vertex for this mesh |
| `mesh[].vertices[].index` | 0-based vertex index within the PRM mesh |
| `mesh[].vertices[].obj_vertex_index` | 1-based OBJ vertex index |
| `weights[].slot` | slot within the 8-byte implicit weight record |
| `weights[].node_hash` | matching XMPR node hash, or `null` if the slot is outside the node table |
| `weights[].raw_u8` | original source byte |
| `weights[].weight_raw128` | `min(raw_u8, 128) / 128.0` |
| `weights[].weight_normalized` | per-vertex normalized influence |

Validation after adding the sidecar:

| Sample | Textures | Meshes | Materials | Weighted vertices | Weight records | Unmapped records |
|---|---:|---:|---:|---:|---:|---:|
| `ms008000_p000.xc` | 5 | 12 | 5 | 10473 | 10473 | 0 |
| `ms007000_p000.xc` | 4 | 9 | 4 | 7898 | 7898 | 0 |
| `ue001000_p000.xc` | 5 | 5 | 5 | 3562 | 3566 | 0 |
| `map\b0000.xc` | 18 | 74 | 43 | 0 | 0 | 0 |

`ue001000_p000.xc` has more weight records than weighted vertices, so the
sidecar is not merely assuming one-hot weights. `map\b0000.xc` is a useful
negative control: its float32 map meshes export geometry, textures, and
materials while correctly recording zero skin weights.

### Static Weighted glTF

`age_gltf_tool.py` writes static glTF 2.0 plus an external `.bin` buffer. It
does not parse or execute `.mtn2`, `_s*`, or `_v*` action files. For skinned
meshes, it uses static `.mbn` bind transforms when the XMPR node hashes match
MBN bone IDs, and falls back to identity nodes only for missing hashes. It
writes the decoded source weights into glTF skin attributes:

- `POSITION`
- `TEXCOORD_0` when UV0 exists
- `JOINTS_0` / `WEIGHTS_0`
- `JOINTS_1` / `WEIGHTS_1` only when more than four influences are present

The MBN skin nodes are a static bind-pose preservation mechanism, not action
execution. They keep bind-pose geometry stable in viewers while carrying
source weight data in a common model format. Material texture references reuse
the PNG paths already proven by the MTL writer.

Current structural validation:

| Sample | glTF meshes | Textures | Skins | Unique joint nodes | MBN nodes | Missing MBN hashes | Weighted vertices | Max influences |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ms008000_p000.xc` | 12 | 5 | 12 | 30 | 45 | 0 | 10473 | 1 |
| `ue033100_p000.xc` | 13 | 9 | 13 | 51 | 13 | 51 | 7429 | 2 |
| `ue033100_p000.xc` + `ue000012_p000.xc` skeleton archive | 13 | 9 | 13 | 56 | 82 | 0 | 7429 | 2 |
| `hu254200_p000.xc` | 5 | 2 | 5 | 19 | 23 | 0 | 2664 | 3 |
| `map\b0000.xc` | 74 | 18 | 0 | 0 | 0 | 0 | 0 | 0 |

For all sampled glTF outputs, the external `.bin` file size matches
`buffers[0].byteLength` in the glTF JSON.

### Skinned 16-bit meshes and experimental animation

The sampled `ms008000_p000.xc` establishes the reliable static interpretation:

- The archive contains 87 files: 5 XI textures, 12 PRMs, 5 MTR/ATR/TXP
  material sets, and 45 MBN bones.
- Its 10,473 normalized signed-16-bit vertices form a complete mobile suit
  directly in bind pose.
- All 3,738 exported inferred faces have legal OBJ indices, every coordinate
  is finite, and all five `map_Kd` paths resolve.
- The five PNGs contain 16 colors each and have zero pure-black and zero
  alpha-zero pixels after PSP deswizzling.

The earlier `fn024000_p000.xc` sample provides useful node associations:

- XMPR node tables contain 6 or 7 32-bit node hashes per mesh.
- XPVB slot 7 contains 8 weight bytes. Sampled values are one-hot `0x80`,
  selecting the corresponding XMPR node hash.
- The archive contains 24 `.mbn` records. Their IDs match the node hashes;
  23 nodes are direct children of root `D5891C87`.
- Matching `_s240`, `_s241`, and `_v360` archives contain XMTN/V2 `.mtn2`
  animations with `BoneLocation`, `BoneRotation`, and `BoneScale` tracks for
  those hashes.
- `BoneScale` commonly animates from `0.0001` to about `1.0`. This is direct
  numeric evidence that slot 0 must remain normalized; applying raw signed
  integers would incorrectly produce bounds near 32768 units.

`tools/StudioElevenAnimationProbe` is intentionally a thin wrapper around the
existing GitHub library rather than a new MTN2 parser. It references the
tested `StudioElevenLib.dll` built inside the local clone. A direct
`ProjectReference` to the current `StudioElevenLibMultiplatform.csproj` was
also tested, but the unmodified upstream project currently fails with 10
compile errors in unrelated archive/compression code, so the wrapper does not
patch or fork the dependency. `age_pose_export.py` samples the resulting JSON
tracks and parses MBN bind SRT, but full mobile-suit animation channel space is
still experimental.

Earlier pose diagnostics:

| Output | Frame | Vertices transformed | Overall bounds |
|---|---:|---:|---|
| `fn024000_p000_s240_f000_pose.obj` | 0 | 1911/1911 | min `(-8.188, 8.244, -9.200)`, max `(8.866, 23.479, 9.757)` |
| `fn024000_p000_s240_f012_pose.obj` | 12 | 1911/1911 | min `(-8.188, 8.244, -9.200)`, max `(8.866, 23.706, 8.466)` |
| `fn024000_p000_v360_f054_pose.obj` | 54 | 1911/1911 | min `(-20.449, 3.882, -10.186)`, max `(20.023, 27.611, 11.250)` |

These diagnostics reject the raw-int16 interpretation, but they do not prove
complete-character animation correctness. `ms008000` tests against both
`ms000001_p300` and `ms008000_p210` obtain 24/24 model-node overlap and
transform all 10,473 vertices, yet the resulting previews separate parts.
Therefore pose manifests carry
`status=experimental_animation_channel_space`, and static bind-pose output is
the recommended result.

`from-character` also parses `.mtn2` files embedded directly in the model
archive. `bs001000_p000.xc` contains one `out_00` animation with 7 frames and
one animation node. Its seven float32 PRMs expose no XMPR node hashes, so
compatibility is zero and the pipeline correctly records the candidate without
exporting a posed OBJ.

`XPVI` in AGE PSP files is not the 3DS-style block expected by
StudioElevenLib. `age_model_survey.py` scanned all `.xc` archives under
`<PSP_RESOURCE_ROOT>` and found:

- 3673 XPCK `.xc` archives scanned.
- 2391 archives with `.prm`.
- 24103 `.prm` files surveyed.
- 0 PRM parse failures.
- 24097 PRMs with `primitive_type=2`, `length=12`, `faces_offset=0`,
  `face_count=0`, and no embedded index payload.
- 6 PRMs with the same 12-byte/no-index header but `primitive_type=0`.

The dominant `XPVI` layout is:

- magic `XPVI`
- primitive type `2`
- face offset `0`
- face count `0`
- no embedded compressed index payload

For that reason, OBJ faces emitted by `--triangulation strip` are still marked
experimental even though the no-index strip pattern is now backed by full `.xc`
survey evidence. The exporter skips zero-area inferred faces by default. Use
`--triangulation points` when only confirmed vertex/UV records are desired.

## Commands

Inspect XPCK archives:

```powershell
python .\tools\age_xpck_tool.py inspect "<PSP_RESOURCE_ROOT>\chr" --limit 20 --json .\outputs\manifests\chr_xpck_20.json
```

Extract one XPCK archive:

```powershell
python .\tools\age_xpck_tool.py extract "<PSP_RESOURCE_ROOT>\chr\bs001000\bs001000_p000.xc" --out .\outputs\samples\bs001000_p000_xc --overwrite
```

Export one IMGP texture:

```powershell
python .\tools\age_imgp_tool.py export .\outputs\samples\bs001000_p000_xc\000.xi --out .\outputs\samples\bs001000_p000_xc\000.png
```

The default texture layout is PSP swizzled indexed data. To reproduce the old
black-speckled diagnostic output, pass `--pixel-layout tiled`:

```powershell
python .\tools\age_imgp_tool.py export .\outputs\samples\bs001000_p000_xc\000.xi --out .\outputs\samples\bs001000_p000_xc\000_old_tiled.png --pixel-layout tiled
```

Batch-export all `.xi` files from an extracted archive:

```powershell
python .\tools\age_imgp_tool.py batch-export .\outputs\samples\bs001000_p000_xc --out-dir .\outputs\samples\bs001000_p000_textures
```

Decompress a Level-5 payload such as `RES.bin`:

```powershell
python .\tools\age_xpck_tool.py decompress-l5 .\outputs\samples\bs001000_p000_xc\RES.bin --out .\outputs\samples\bs001000_p000_xc\RES.dec.bin --overwrite
```

Probe `.prm` model candidates:

```powershell
python .\tools\research\age_model_probe.py .\outputs\samples\bs001000_p000_xc --json .\outputs\manifests\bs001000_prm_probe.json
```

Survey model headers across XPCK archives without extracting binary assets:

```powershell
python .\tools\research\age_model_survey.py "<PSP_RESOURCE_ROOT>" --extensions .xc --json .\outputs\manifests\psp_xc_model_survey_all.json
```

Build the static model catalog from the survey:

```powershell
python .\tools\research\age_static_model_catalog.py .\outputs\manifests\psp_xc_model_survey_all.json --json .\outputs\manifests\psp_static_model_catalog.json --markdown .\docs\STATIC_MODEL_CATALOG.md --sample-limit 8
```

Survey MBN bind hashes and locate companion skeleton archives:

```powershell
python .\tools\research\age_mbn_survey.py "<PSP_RESOURCE_ROOT>" --extensions .xc --hash-file .\outputs\manifests\ue033100_missing_mbn_hashes.txt --json .\outputs\manifests\psp_xc_mbn_survey_ue033100_missing.json
```

Probe material/resource parameter files:

```powershell
python .\tools\research\age_param_probe.py .\outputs\samples\bs001000_p000_xc --json .\outputs\manifests\bs001000_param_probe.json
```

Build material binding manifests:

```powershell
python .\tools\age_material_bind.py .\outputs\samples\bs001000_p000_xc --json .\outputs\manifests\bs001000_material_bind.json
```

Inspect decoded XMPR/XPVB metadata:

```powershell
python .\tools\age_xmpr_tool.py info .\outputs\samples\bs001000_p000_xc --triangulation points
```

Export confirmed vertices/UVs to OBJ, with experimental strip faces,
degenerate inferred faces filtered out, an optional MTL reference, and the
default per-vertex weight sidecar:

```powershell
python .\tools\age_xmpr_tool.py export-obj .\outputs\samples\bs001000_p000_xc --out .\outputs\samples\bs001000_p000_models\bs001000_p000_experimental_strip.obj --json .\outputs\manifests\bs001000_p000_experimental_strip_obj.json --triangulation strip --mtllib bs001000_p000.mtl
```

The command also writes:

- `bs001000_p000_experimental_strip.weights.json`

Use `--weights-json <path>` to choose a different sidecar path.

Preserve raw degenerate strip connector faces only for audit:

```powershell
python .\tools\age_xmpr_tool.py export-obj .\outputs\samples\bs001000_p000_xc --out .\outputs\samples\bs001000_p000_models\bs001000_p000_raw_strip.obj --triangulation strip --keep-degenerate-faces
```

Export a safer vertex-cloud OBJ with no inferred faces:

```powershell
python .\tools\age_xmpr_tool.py export-obj .\outputs\samples\bs001000_p000_xc --out .\outputs\samples\bs001000_p000_models\bs001000_p000_points.obj --triangulation points
```

Export decoded meshes directly to static weighted glTF:

```powershell
python .\tools\age_gltf_tool.py .\outputs\samples\bs001000_p000_xc --out .\outputs\samples\bs001000_p000_models\bs001000_p000_strip.gltf --triangulation strip --mbn-root .\outputs\samples\bs001000_p000_xc
```

Run the one-command pipeline from a source XPCK archive:

```powershell
python .\tools\age_asset_pipeline.py from-xpck "<PSP_RESOURCE_ROOT>\chr\bs001000\bs001000_p000.xc" --out-dir .\outputs\pipeline\bs001000_from_xpck --name bs001000_p000 --triangulation points --overwrite
```

`age_asset_pipeline.py` also defaults to `--texture-layout psp-swizzled` and
writes `models\<name>_<triangulation>.weights.json`,
`models\<name>_<triangulation>.gltf`, and
`models\<name>_<triangulation>.bin` whenever model export is enabled.

Run the same pipeline on a map archive:

```powershell
python .\tools\age_asset_pipeline.py from-xpck "<PSP_RESOURCE_ROOT>\map\b0000.xc" --out-dir .\outputs\pipeline\map_b0000_from_xpck_strip --name map_b0000 --triangulation strip --overwrite
```

Run the same pipeline from an already extracted archive directory:

```powershell
python .\tools\age_asset_pipeline.py from-dir .\outputs\samples\fn024000_p000_xc --out-dir .\outputs\pipeline\fn024000_from_dir --name fn024000_p000 --triangulation points
```

Run the recommended complete static mobile-suit workflow:

```powershell
python .\tools\age_asset_pipeline.py from-character "<PSP_RESOURCE_ROOT>\chr\ms008000\ms008000_p000.xc" --out-dir .\outputs\pipeline\ms008000_static_recommended --name ms008000_p000 --triangulation strip --overwrite
```

The command defaults to `--animation-policy none`. To run the experimental
animation path, explicitly pass `--animation-policy best` together with one or
more `--animation-archive` arguments. Node overlap is required but is not
treated as proof of visual pose correctness.

The recommended static command writes:

- `models\ms008000_p000_strip.obj`
- `models\ms008000_p000.mtl`
- `models\ms008000_p000_strip.weights.json`
- `models\ms008000_p000_strip.gltf`
- `models\ms008000_p000_strip.bin`
- `textures\000.png` through `textures\004.png`
- `_asset_pipeline_manifest.json`

When a model archive needs a companion skeleton archive, pass
`--skeleton-archive`, or pass an MBN survey with `--skeleton-survey`.
Examples:

```powershell
python .\tools\age_asset_pipeline.py from-character "<PSP_RESOURCE_ROOT>\chr\ue033000\ue033100_p000.xc" --out-dir .\outputs\pipeline\ue033100_static_with_companion_skeleton --name ue033100_p000 --triangulation strip --skeleton-archive "<PSP_RESOURCE_ROOT>\chr\ue000012\ue000012_p000.xc" --overwrite
```

```powershell
python .\tools\age_asset_pipeline.py from-character "<PSP_RESOURCE_ROOT>\chr\ue033000\ue033100_p000.xc" --out-dir .\outputs\pipeline\ue033100_static_with_survey_skeleton --name ue033100_p000 --triangulation strip --skeleton-survey .\outputs\manifests\psp_xc_mbn_survey_ue033100_missing.json --overwrite
```

Batch-validate textured map exports across representative families:

```powershell
python .\tools\research\age_map_validation.py "<PSP_RESOURCE_ROOT>\map\b0000.xc" "<PSP_RESOURCE_ROOT>\map\b0000sky.xc" "<PSP_RESOURCE_ROOT>\map\b0501.xc" "<PSP_RESOURCE_ROOT>\map\t5101.xc" "<PSP_RESOURCE_ROOT>\map\e3108.xc" "<PSP_RESOURCE_ROOT>\map\p0012.xc" "<PSP_RESOURCE_ROOT>\map\m01.xc" --out-root .\outputs\map_validation\batch_20260609 --overwrite
```

Generate a direct swizzle-vs-tiled comparison for two representative map
archives:

```powershell
python .\tools\research\age_map_validation.py "<PSP_RESOURCE_ROOT>\map\b0000.xc" "<PSP_RESOURCE_ROOT>\map\e3108.xc" --out-root .\outputs\map_validation\batch_20260609_swizzled_compare --texture-layout psp-swizzled --overwrite
python .\tools\research\age_map_validation.py "<PSP_RESOURCE_ROOT>\map\b0000.xc" "<PSP_RESOURCE_ROOT>\map\e3108.xc" --out-root .\outputs\map_validation\batch_20260609_tiled_compare --texture-layout tiled --overwrite
```

Build the thin StudioElevenLib animation wrapper:

```powershell
dotnet build .\tools\StudioElevenAnimationProbe\StudioElevenAnimationProbe.csproj -c Release
```

Parse an AGE PSP `.mtn2` with the existing GitHub library:

```powershell
dotnet .\tools\StudioElevenAnimationProbe\bin\Release\net9.0\StudioElevenAnimationProbe.dll .\outputs\samples\fn024000_s240_xc\000.mtn2 .\outputs\manifests\fn024000_s240_animation_studioeleven.json
```

Export a posed OBJ from the model directory and parsed animation:

```powershell
python .\tools\age_pose_export.py .\outputs\pipeline\fn024000_from_xpck_strip\extracted --animation-json .\outputs\manifests\fn024000_s240_animation_studioeleven.json --frame 12 --out .\outputs\pipeline\fn024000_from_xpck_strip\models\fn024000_p000_s240_f012_pose.obj --triangulation strip --mtllib fn024000_p000.mtl
```

Render a dependency-light, untextured OBJ topology preview:

```powershell
python .\tools\research\age_obj_preview.py .\outputs\pipeline\ms008000_static_recommended\models\ms008000_p000_strip.obj --out .\outputs\previews\ms008000_static_recommended.png
```

This preview uses installed Matplotlib only for validation; it is not a game
format parser and does not render textures or materials.

Pipeline validation:

| Command | Textures | Meshes | Materials | Notes |
|---|---:|---:|---:|---|
| `from-xpck ...bs001000_p000.xc --triangulation points` | 2 | 7 | 2 | Extracted 41 XPCK files, then exported PSP-deswizzled PNG, OBJ vertex clouds, MTL, and material bindings |
| `from-xpck ...bs001000_p000.xc --triangulation strip` | 2 | 7 | 2 | Extracted 41 XPCK files, then exported PSP-deswizzled PNG and 492 non-degenerate experimental faces plus MTL |
| `from-dir ...bs001000_p000_xc --triangulation points` | 2 | 7 | 2 | Reuses existing extracted directory |
| `from-dir ...fn024000_p000_xc --triangulation points` | 1 | 3 | 1 | Exercises PSP 16-bit normalized skinned bind-pose positions |
| `from-dir ...bs001000_p000_xc --triangulation strip` | 2 | 7 | 2 | Exports 492 non-degenerate experimental faces from 1422 inferred strip faces plus MTL |
| `from-dir ...fn024000_p000_xc --triangulation strip` | 1 | 3 | 1 | Exports 320 non-degenerate experimental faces plus MTL; asset preview is marker-like |
| `from-xpck ...map\b0000.xc --triangulation strip` | 18 | 74 | 43 | Exports 2136 non-degenerate experimental faces, 18 resolved `map_Kd` texture paths, 74/74 mesh-material bindings, zero-weight sidecar, and unskinned static glTF |
| `from-character ...ms008000_p000.xc` (default) | 5 | 12 | 5 | Recommended static output: complete 10473-vertex mobile suit, 3738 faces, five resolving `map_Kd` paths, 10473 weighted vertices, 12 glTF skins, no animation |
| `from-character ...ms007000_p000.xc` (default) | 4 | 9 | 4 | Static MS-family check: 7898 weighted vertices, 7898 weight records, zero unmapped records |
| `from-character ...ue001000_p000.xc` (default) | 5 | 5 | 5 | Static UE-family check: 3562 weighted vertices, 3566 weight records, zero unmapped records, 5 glTF skins |
| `from-character ...ue033100_p000.xc` (default) | 9 | 13 | 9 | Larger UE catalog sample: 7429 weighted vertices, 7956 weight records, 13 glTF skins |
| `from-character ...hu254200_p000.xc` (default) | 2 | 5 | 2 | Human/NPC catalog sample: 2664 weighted vertices, 3470 weight records, 5 glTF skins |
| `from-character ...bs002000_p000.xc` (default) | 2 | 7 | 2 | Vehicle/ship catalog sample: float32 static meshes, zero skin weights, textured glTF |
| `from-character ...ue000001_p000.xc` (default) | 0 | 0 | 0 | Negative sample-selection check: archive has no PRM/texture payload for static model export |
| `from-character ...fn024000_p000.xc --animation-policy best` | 1 | 3 | 1 | Parses 3 sibling animations and gets 20/20 overlap; output remains marker/effect-like |
| `from-character ...fn001000_p000.xc --animation-policy best` | 1 | 1 | 1 | Experimental run parses 2 animations, gets 5/5 overlap, and remains marker-like |
| `from-character ...fn001001_p000.xc --animation-policy best` | 1 | 1 | 1 | Same independent 5/5 experimental compatibility result and marker-like classification |
| `from-character ...bs001000_p000.xc --animation-policy best` | 2 | 7 | 2 | Parses 1 embedded animation, records zero node overlap, and intentionally exports no pose |

## Output Policy

`outputs/samples` may contain extracted game assets and generated PNGs. These
are local research artifacts only and should not be redistributed.

`external_tools/github` contains third-party public repositories cloned for
research and should be treated as local tool dependencies, not original project
source.

## Current Focus

As of 2026-06-09, the static character-family workflow is usable enough for
mobile suits, UE units, and human/NPC samples: PNG, OBJ/MTL, per-vertex weight
sidecar, and static weighted glTF are all working on validated samples.

The next priority is map-model conversion quality. `map_b0000.xc` already
exports as textured static geometry, but map texture correctness is still not
fully proven. The remaining issue may be texture decode, material/texture
binding, UV interpretation, or triangle-strip reconstruction. This needs
side-by-side comparison against more local map samples and emulator/reference
evidence before stronger conclusions are documented.

New map evidence narrows that uncertainty. Batch validation across fifteen map
archives now shows:

- all sampled map exports remain static as expected: zero weights and zero
  skins;
- `psp-swizzled` PNG output produces coherent thumbnails across the sampled
  `b`, `sky`, `t`, `e`, `p`, and `m` archives;
- direct `psp-swizzled` vs `tiled` comparison on `b0000` and `e3108` shows the
  tiled layout visibly scrambles textures while `psp-swizzled` preserves
  readable labels (`b0000`) and coherent architectural textures (`e3108`).
- all sampled absent-UV meshes are collision-like helper geometry: `15/15`
  samples have `0` non-collision absent-UV meshes.
- sampled sky archives are currently the cleanest group: `5/5` sky samples
  have zero unresolved visual materials.
- sampled non-sky archives split into two remaining-risk groups:
  `5/10` now have only effect-like unresolved visual materials, `4/10` still
  have at least one plain unresolved visual material, and `1/10` (`b0201`) has
  no unresolved visual materials at all.
- plain unresolved severity is now measurable by triangle coverage.
  Current sampled priority order is:
  `b0101` (`34.78%` of triangles),
  `p0012` (`17.35%`),
  `e3108` (`2.17%`),
  and `b0000` (`0.37%`).
- a new mesh-name/resource-order fallback in `age_material_bind.py` is now
  proven useful on real map data. In sampled `b0101`, it resolved
  `b0101.b0101s01-tm-a-` to `textures/000.png`, improving the archive from
  `13 -> 14` resolved materials and reducing unresolved visual materials from
  `5 -> 4`. The plain unresolved face ratio did not move, which means the next
  map pass should stay focused on the plain unresolved set rather than on
  effect-like materials.
- the same fallback also resolved `p0012.p0012g03-` by backfilling
  `a_yuka101/a_yuka201` from mesh names, improving `p0012` from `10 -> 11`
  resolved materials and reducing its plain unresolved set to just
  `p0012.p0012g04-`.
- after rerunning the main map batch with the new heuristic, `b0601` no longer
  carries any plain unresolved material. Its remaining unresolved visuals are
  effect-like only (`b0601g11-tm-`, `b0601g13-a-s0_aof35-`), so it drops below
  `e3108` and `b0000` for plain-texture investigation.
- the remaining plain unresolved cases now split into two types:
  `b0101` already has mesh-name texture candidates but no in-archive `.xi`
  match, which strengthens the cross-resource or nontrivial binding hypothesis;
  `p0012g04`, `e3108b25/g05`, and `b0000g16/g17` still have no usable texture
  candidate at all, so they need additional resource-string or external-archive
  comparison before another binding heuristic is added.
- a broader non-`chr` map survey is now available through `age_map_survey.py`.
  It covers `285` archives with cleanup-on-exit sampling and shows:
  `198/285` visually clean exports,
  `54/285` with plain unresolved visuals,
  `33/285` with effect-like-only unresolved visuals,
  and `0/285` current survey failures after the static-map glTF path stopped
  loading MBN bind data for unweighted exports.
- the full survey also confirms that successful map exports remain static:
  sampled non-`chr` map archives show `0` unexpected weighted-vertex cases and
  `0` unexpected skin cases.
- the former `fe*` survey failures are now resolved. `fe0001`, `fe0002`,
  `fe0003`, `fe0004`, and `fe5001` all export as clean static textured maps
  once MBN loading is skipped for unweighted glTF output.
- large-map-focused validation is now the preferred next step. A dedicated
  large-map batch on `e1101`, `b0101`, `b3205`, `b3104`, `t0201`, and `e3108`
  compared against large control maps `t5201`, `t0901`, `e2104`, and `b3003`
  shows the controls all land at `0` visual unresolved materials, while the
  risk set still carries plain unresolved binding gaps. That makes large maps
  much better diagnostic targets than small archives.
- current large-map plain-risk order is:
  `e1101` (`81.09%` of faces),
  `b3205` (`43.18%`),
  `b0101` (`34.78%`),
  `b3104` (`33.84%`),
  `t0201` (`6.93%`),
  and `e3108` (`2.17%`).
- a focused `e1101` family compare also strengthens the “family-specific
  binding gap” reading: `e1102`, `e1103`, and `e1104` are visually clean,
  `e1105` has only a small residual plain issue (`5.41%`), while `e1101`
  stays a severe outlier (`81.09%`). That makes `e1101` a much better next
  heuristic target than treating `e11*` as a uniform class.
- the large-map problem set also splits into three binding classes:
  `b0101` already has mesh-name candidates but no in-archive `.xi` target;
  `e1101`, `b3104`, `t0201`, and the `e3108` residuals have TXP ownership but
  still no usable texture candidate;
  `b3205` includes `resource_string_only` plain materials with no TXP owner at
  all. The next heuristic should be chosen against one of these classes, not
  against small one-off archives.

This does not prove every remaining map issue is solved, but it makes texture
layout decode a much less likely source of the remaining problems. The main
open risks now shift toward unresolved material bindings for non-sky maps and
inferred topology, not PSP texture swizzle.

## Open Work

1. Continue map-focused validation, but treat PSP texture swizzle as the
   leading confirmed layout. Compare textured map meshes against emulator or
   reference captures to separate remaining issues into material binding, UV
   mapping, or inferred topology.
2. Audit unresolved map materials more aggressively, but bias toward large-map
   archives. The full `285`-archive survey says the large-map risk set is now
   `e1101`, `b3205`, `b0101`, `b3104`, `t0201`, and `e3108`; large clean
   controls `t5201`, `t0901`, `e2104`, and `b3003` should stay in the compare
   set. Do not spend the next pass on small low-signal archives first.
3. Within that large-map set, pick the next heuristic by failure class:
   `b0101` for “candidate exists but no `.xi` target,”
   `e1101` / `b3104` / `t0201` / `e3108` for “TXP owner but no candidate,”
   and `b3205` for “resource-string-only plain material.”
4. Validate inferred face reconstruction against emulator captures or a
   textured renderer. Matplotlib previews establish broad silhouettes, but OBJ
   faces still come from no-index triangle-strip inference.
5. Decode `.mtr/.atr` fields beyond the currently identified TXP CRC32 owner
   bindings, resource texture-name candidates, and UV scale candidates.
6. Validate current PNGs against emulator captures. Palette byte order looks
   correct on sampled files, but broad visual validation is still needed.
7. Generalize companion skeleton selection. `ue033100_p000.xc` is solved by
   adding `ue000012_p000.xc`, but automatic selection rules still need to be
   derived across the UE family.
8. Generalize the validated static workflow across additional model-bearing
   `ms*`, `ue*`, equipment, and map archives, and identify how optional
   equipment archives are composed.
9. Reproduce StudioEleven's exact Blender pose-channel conversion before
   treating XMTN animation export as reliable. Node overlap and inverse-bind
   matrices alone are insufficient.




