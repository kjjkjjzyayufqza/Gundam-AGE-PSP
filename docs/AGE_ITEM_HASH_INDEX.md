# AGE Item / Wear Hash Index Notes

> Session context (AGE-FX body resolve + full part list):  
> **`docs/AGE_FX_SESSION_2026-07-25.md`** · parts: `outputs/age_fx_ms/AGE_FX_PARTS.md`

## What your bytes are

Your 4-byte sequences are **little-endian on-disk item / part IDs** used by AGE System
and item databases. They are **not** XPCK filename CRCs (those match names like `000.prm`).

| Your bytes | LE u32 | Confirmed meaning (you) | Found in |
|---|---|---|---|
| `BD 35 BA 0B` | `0x0BBA35BD` | AGE-1 red arm | `item_config` WEAR, `agesystem_config` |
| `60 ED D0 F9` | `0xF9D0ED60` | AGE-1 red leg | same |
| `CE 41 75 73` | `0x737541CE` | AGE-1 red special fist | `item_config` WEAPON |
| `C7 1E 9C B9` | `0xB99C1EC7` | ビームランス (melee) | shops, agesystem, map tbox |
| `B5 60 AF AD` | `0xADAF60B5` | ビームハンマー (melee) | shops, agesystem |
| `54 A0 7D 04` | `0x047DA054` | シーラ・クロノス leg | agesystem |
| `6E 79 E4 DD` | `0xDDE4796E` | body / core set slot | `database.cfg.bin` loadout |
| `A3 85 AE 3B` | `0x3BAE85A3` | hand | agesystem + database loadout |
| `7E 5D C4 C9` | `0xC9C45D7E` | leg | agesystem + database loadout |
| `AB A8 2A A6` | `0xA62AA8AB` | leg (alt) | agesystem |
| `B2 98 D4 A7` | `0xA7D498B2` | head of long record | agesystem |

## Long record you pasted

```
B2 98 D4 A7 80 61 EF 08 00 00 00 00 09 00 98 00 85 02 02 01 20 1C 18 15
01 00 19 00 3D 00 00 00 DC 5C C6 87 EB 36 04 86 28 00 08 00 ...
AF 43 33 33 33 3F 01 01 46 02 64 64 2D 04 5A 00 42 00  CE 41 75 73
```

- Starts with ID `B298D4A7`
- Ends with weapon ID `CE417573` (AGE-1 red fist)
- Middle fields look like **stats / slots / flags** (u16 pairs, floats like `33 33 33 3F` = 0.7f)
- This is an **item definition / equip record**, not a model path string

## Key game-native list files

| File | Role |
|---|---|
| `cmn/res/item/item_config.cfg.bin` | Short catalog: CORE / WEAR / WEAPON / OPTION / NORMAL sections (`ITEM_*` CRC tags) |
| `cmn/res/menu/agesystem_config_0.01a.cfg.nat` | Full AGE System part/weapon index (~305 IDs) |
| `cmn/res/menu/database.cfg.bin` | Loadouts: core+arm+leg combos as ID triples |
| `cmn/txt/jp/menu/dbMSText.bin` | **Display names** including `ガンダムＡＧＥ－ＦＸ` and FX Burst |
| `cmn/res/shp/shop-sh*.cfg.nat` | Shop stock includes weapon IDs (lance/hammer) |

## Display name list (dbMSText order, partial)

Federal Gundams (short titles, order in text DB):

1–18 AGE-1 variants  
19–35 AGE-2 variants (**#22 = ダークハウンド / Dark Hound**)  
36–42 AGE-3 variants  
**#43 = ガンダムＡＧＥ－ＦＸ**  
**#44 = ガンダムＡＧＥ－ＦＸ（ＦＸバースト）**  

User confirmed: `ms008000` = AGE-2 Dark Hound (black).  
Simple linear name-index→`ms*` package mapping is **wrong** for AGE-FX (it wrongly predicted `ms042000`, which you rejected).

## AGE-FX resolved (visual confirm)

**Package: `ms010000`** = ガンダムＡＧＥ－ＦＸ.

Only full MS package in `psp/chr` whose RES references funnel meshes (`*_fn1`).  
Exclusive weapon packages: **`fn010000`** / **`fn002000`** (Ｃファンネル), co-packed with `ms010000` in battles `ga_ws_18_0040/0041`.

### Body / weapon part map

| Role | Mesh / package | Path |
|------|----------------|------|
| Full body | `ms010000` | `psp/chr/ms010000/ms010000_p000.xc` |
| Head + core (+ arm meshes) | `ms010100` (+ embedded `ms010200`) | `…/ms010100_p000.xc` |
| Arms / hands | `ms010200` (+ `_fn1`) | inside full + `ms010100` only (no `ms010200` folder) |
| Legs | `ms010300` (+ `_fn1`) | `…/ms010300_p000.xc` |
| Backpack / binders | `ms010400` (+ `_2` + `_fn1`) | `…/ms010400_p000.xc` |
| C-Funnel weapon | `fn010000` | `psp/chr/fn010000/fn010000_p000.xc` |
| C-Funnel alt | `fn002000` | `psp/chr/fn002000/fn002000_p000.xc` |

Exports + previews: `outputs/age_fx_ms/` — see `AGE_FX_PARTS.md` and `AGE_FX_PARTS_INVENTORY.json`.

Weapon list search: use IDs `C71E9CB9` / `B560AFAD` inside `agesystem_config` and shop cfgs; they are **melee weapon entries**, not MS body packages.

