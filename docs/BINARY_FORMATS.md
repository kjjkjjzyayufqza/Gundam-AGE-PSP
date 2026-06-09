# Binary Format Notes

Date: 2026-06-09

All fields below are based on sampled Gundam AGE PSP files and local tooling.
Unknown fields remain unnamed.

## XPCK Archive

Magic: `XPCK`.

Header is little-endian:

| Offset | Type | Meaning |
|---:|---|---|
| `0x00` | char[4] | `XPCK` |
| `0x04` | u8 | file count low byte |
| `0x05` | u8 | low nibble is file count high bits; high nibble is variant/flags |
| `0x06` | u16 | file info offset divided by 4 |
| `0x08` | u16 | compressed filename table offset divided by 4 |
| `0x0A` | u16 | data offset divided by 4 |
| `0x0C` | u16 | file info size divided by 4 |
| `0x0E` | u16 | filename table size divided by 4 |
| `0x10` | u32 | data size divided by 4 |

Entry records are 12 bytes:

| Field | Meaning |
|---|---|
| u32 | CRC/hash |
| u16 | offset into decompressed filename table |
| u16 + u8 | data offset divided by 4 |
| u16 + u8 | file size |

Filename tables use Level-5 compression. Current code supports raw,
LZ10, Huffman4, Huffman8, RLE, and zlib paths used by sampled data.

## Level-5 Compression Header

Compressed blocks start with a 32-bit little-endian word:

```text
bits 0..2   method id
bits 3..31  decompressed size
```

Observed method IDs:

| ID | Name |
|---:|---|
| 0 | none |
| 1 | LZ10 |
| 2 | Huffman4 |
| 3 | Huffman8 |
| 4 | RLE |
| 5 | zlib |

No separate cryptographic encryption has been proven in sampled AGE PSP assets.
The reversible transform required by the tools is Level-5 compression decode.

## RES.bin / CHRP00

Sampled `RES.bin` files are Level-5 compressed. After decompression, useful
payloads begin with `CHRP00`.

Uses:

- string source for mesh names;
- material owners;
- texture projection names;
- map part/collision names.

The material binder compares `.txp` CRC32 words against these strings.

## IMGP / XI Texture

Magic: `IMGP`.

Observed fields:

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

Block order:

1. palette block;
2. tile table;
3. indexed pixel block.

Texture reconstruction:

```text
compressed blocks
  -> palette bytes + tile table + indexed pixels
  -> 8x8 tile rebuild
  -> PSP 16-byte x 8-row deswizzle
  -> palette lookup
  -> PNG
```

The PSP deswizzle fix removed the earlier black-speckle artifacts.

## XMPR / PRM Model

Magic: `XMPR`.

Observed structure:

```text
XMPR
  XPRM
    XPVB
    XPVI
  trailing strings/names
```

`XPVB` header fields:

| Offset in XPVB | Type | Meaning |
|---:|---|---|
| `0x00` | char[4] | `XPVB` |
| `0x04` | u16 | compressed attribute table offset |
| `0x06` | u16 | unknown block offset / attribute table end |
| `0x08` | u16 | compressed vertex buffer offset |
| `0x0A` | u16 | vertex stride |
| `0x0C` | u32 | vertex count |

Confirmed vertex attribute roles:

| Slot | Role |
|---:|---|
| 0 | position |
| 1 | normal candidate |
| 2 | UV0 in sampled meshes |
| 7 | bone weights |
| 8 | bone indices |

`XPVI` stores index data. Current map/model exports use triangle-strip
interpretation by default.

## Material Parameters

Observed small parameter files:

| File | Header | Current interpretation |
|---|---|---|
| `.mtr` | `MTRP00` | material parameter block |
| `.atr` | `ATRP01` | render/attribute block |
| `.txp` | compact block | texture parameter; first words are CRC32 string links |

`.txp` binding evidence:

- first word often matches a material owner string from `CHRP00`;
- second word often matches `<owner>_texproj0`;
- same numbered stem commonly binds `NNN.txp` to `NNN.xi`.

## MBN Skeleton / Bind Data

`.mbn` stores skeleton/bind-pose data used by weighted character meshes.

Important current rule:

- weighted character meshes may need MBN;
- unweighted static maps skip MBN loading entirely.

This avoids false failures on map archives with bad/cyclic MBN data.

## MTN2 Animation

`.mtn2` animation parsing is experimental. Current local probe uses
`Tiniifan/StudioElevenLib` through an ignored local .NET wrapper. Stable static
asset extraction does not depend on animation export.



