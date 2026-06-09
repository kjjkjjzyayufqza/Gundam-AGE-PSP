# Level-5 Resource Architecture

Date: 2026-06-09

This document describes the observed Gundam AGE PSP resource architecture as it
is used by the local extraction tools.

## Scope

The input is an already-unpacked PSP resource tree. This repository does not
dump the game, decrypt an ISO, or redistribute extracted assets.

Typical local root:

```text
<PSP_RESOURCE_ROOT>
```

## High-Level Flow

```text
psp resource tree
  -> area folders
  -> XPCK archives
  -> archive entries
  -> Level-5 compressed subpayloads
  -> texture/model/material/resource decoding
  -> PNG/OBJ/MTL/glTF/manifests
```

## Area Folders

Observed indexed areas:

| Area | Role |
|---|---|
| `chr` | character, mobile suit, NPC, vehicle-style model archives |
| `map` | static stage/map model archives and sky companions |
| `btl` | battle packages; can contain nested XPCK entries |
| `eff` | effect/event resource packages; many contain models and textures |
| `evt` | event packages |
| `anm` | animation or animation-adjacent packages |
| `menu`, `gmp`, `spr`, `sky` | UI, map/sky, sprite, and supporting resources |

The asset index classifies these by path and filename family, not by game
metadata tables.

## Archive Layer

Most useful files are Level-5 `XPCK` archives. Extensions are not enough to
prove archive type; tools verify the `XPCK` magic.

Common extensions:

| Extension | Observed use |
|---|---|
| `.xc` | common model/resource archive |
| `.xb` | battle package archive |
| `.xa` | animation/event package archive |
| `.xv` | variant/effect archive |
| `.xk`, `.xq`, `.npcbin`, `.bin` | supporting XPCK candidates |

An XPCK archive contains:

- header;
- entry table;
- compressed filename table;
- data payload region.

Nested XPCK entries can appear inside larger packages, especially battle/event
archives.

## Resource Name Layer

Many archives contain `RES.bin`. Sampled `RES.bin` payloads are Level-5
compressed and decompress to resource data beginning with `CHRP00`.

`CHRP00` strings are important because they expose:

- material owners;
- texture projection names;
- mesh/material names;
- map part names;
- collision/helper names.

Material binding currently uses these strings together with `.txp` CRC32 words.

## Texture Layer

Texture entries use `IMGP` inside `.xi` files.

The extractor:

1. decodes the palette block;
2. decodes the tile table;
3. decodes the indexed pixel block;
4. rebuilds indexed 8x8 tiles;
5. applies PSP 16-byte x 8-row deswizzle;
6. applies the palette;
7. writes PNG.

The default layout is `psp-swizzled`. The older `tiled` path remains only for
comparison and reproduces the earlier colored-but-black-speckled problem.

## Model Layer

Model entries use `XMPR` inside `.prm` files.

Observed nested model blocks:

```text
XMPR
  XPRM
    XPVB  vertex buffer and attribute layout
    XPVI  index data
```

Current exports:

- OBJ for topology/material inspection;
- MTL for PNG material links;
- glTF for textured static review;
- sidecar weight manifests for weighted character meshes.

## Material Layer

Material-related files:

| File | Current meaning |
|---|---|
| `.mtr` | `MTRP00` material parameter block |
| `.atr` | `ATRP01` render/attribute block |
| `.txp` | texture parameter block; first words match CRC32 of resource strings |

Binding priority:

1. TXP owner CRC32 -> `CHRP00` string.
2. Same numbered TXP/XI stem, for example `013.txp -> 013.xi`.
3. Mesh-name/resource-order fallback.
4. Leave unresolved and count in reports.

Remaining visible map issues are mostly in this layer.

## Skeleton and Animation Layer

Character archives can contain `.mbn` bind/skeleton data. Weighted character
exports use this context for glTF skin data. Static maps should remain
unweighted and now skip MBN loading.

Animation candidates use `.mtn2` and related metadata. The optional local
`StudioElevenAnimationProbe` wraps `Tiniifan/StudioElevenLib` for XMTN parsing,
but full animation export is not part of the current stable milestone.

## Output Layer

Generated outputs are ignored by Git:

```text
outputs/
  previews/
  pipeline/
  map_validation/
  map_survey/
  manifests/
```

Important generated index files:

- `outputs/manifests/AGE_ASSET_INDEX.md`
- `outputs/manifests/age_asset_index.compact.json`
- `outputs/manifests/age_asset_index.json`




