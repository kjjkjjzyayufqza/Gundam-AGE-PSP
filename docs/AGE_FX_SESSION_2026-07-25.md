# Session findings: Gundam AGE-FX identification & full part export

**Date:** 2026-07-25  
**Workspace:** `E:\research\Gundam-AGE-PSP`  
**Unpack root:** `D:\PPSSPP\AGE解包\资源解包`  
**User goal:** Find **Gundam AGE-FX** (机体, not particle FX), export models + textures + **bones/weights**, inventory all body parts and weapons.

Related short inventories (keep in sync when parts change):

- `outputs/age_fx_ms/AGE_FX_PARTS.md` — part/weapon table + re-export commands  
- `outputs/age_fx_ms/AGE_FX_PARTS_INVENTORY.json` — machine-readable  
- `docs/AGE_ITEM_HASH_INDEX.md` — item/wear LE IDs from user dumps  
- `docs/AGE_FX_NATIVE_INDEX_RESEARCH.md` — **particle** `psp/eff` catalogs (different meaning of “FX”)

---

## 1. Goal clarification (critical)

| User said | Wrong interpretation | Correct interpretation |
|-----------|----------------------|------------------------|
| “age-fx” / AGE-FX | `psp/eff` particle/effect packages (`effect_config.cfg.bin`) | **Mobile suit** ガンダムＡＧＥ－ＦＸ |
| Want models | Effect batch export (`outputs/fx`, 649 packs) | Character packages under `psp/chr/ms*` |
| With bones/weights | N/A for most eff markers | `age_start.py character` → glTF JOINTS/WEIGHTS + `*.weights.json` |

**Anchors confirmed by user during session:**

- `ms008000` = **AGE-2 Dark Hound** (黑狼 / ダークハウンド) — black suit, **not** AGE-FX  
- Early candidates `ms042*`, `ms104*`, `ms041*`, etc. — **rejected** as not AGE-FX  
- Final visual confirm: **`ms010000` is AGE-FX**

---

## 2. Timeline of approaches (what worked / failed)

### 2.1 Failed: treat “FX” as `psp/eff`

- Built `tools/age_fx_index.py`, `age_start.py fx-index`  
- Documented native catalogs in `docs/AGE_FX_NATIVE_INDEX_RESEARCH.md`  
- Exported large tree under `outputs/fx/`  
- **User correction:** want the **suit**, not effects  

### 2.2 Failed: linear `dbMSText` name index → `ms*` package

- `dbMSText.bin` short names: AGE-1…AGE-2…AGE-3… then  
  - **#43** `ガンダムＡＧＥ－ＦＸ`  
  - **#44** `ガンダムＡＧＥ－ＦＸ（ＦＸバースト）`  
- Dark Hound is name ~#22 and package **`ms008000`**  
- Aligning name order to full `ms*_p000` list **predicted `ms042000` for AGE-FX**  
- Hypothesis written to `outputs/manifests/ms_name_to_package_hypothesis.json`  
- **User rejected** those models → **linear map is invalid** for AGE-FX  

### 2.3 Failed: early visual candidates

Exported + Blender-previewed and rejected (user):

| Package | Why tried | Result |
|---------|-----------|--------|
| `ms042000` (+ variants) | Linear name→package hypothesis | Not AGE-FX |
| `ms041*` | Near 042 | Not AGE-FX |
| `ms104000` | White/blue + wings look | Not AGE-FX |
| `ms008000` | Known control | Dark Hound only |
| `ms108/110/118/125` | Other full MS | Not AGE-FX |
| First previews | Camera framing bugs | Looked like “legs only” |

### 2.4 Partial: item/wear hash dumps (user-provided)

User bytes are **LE u32 item IDs** (AGE System / shops / database), **not** XPCK filename CRCs.

Documented in `docs/AGE_ITEM_HASH_INDEX.md`. Summary:

| Bytes (on-disk LE) | u32 | Meaning (user) |
|--------------------|-----|----------------|
| `BD 35 BA 0B` | `0x0BBA35BD` | AGE-1 red arm |
| `60 ED D0 F9` | `0xF9D0ED60` | AGE-1 red leg |
| `CE 41 75 73` | `0x737541CE` | AGE-1 red exclusive fist |
| `6E 79 E4 DD` | `0xDDE4796E` | body/core slot |
| `A3 85 AE 3B` | `0x3BAE85A3` | hand |
| `7E 5D C4 C9` | `0xC9C45D7E` | leg |
| `AB A8 2A A6` | `0xA62AA8AB` | leg (alt) |
| `C7 1E 9C B9` | `0xB99C1EC7` | ビームランス (melee) |
| `B5 60 AF AD` | `0xADAF60B5` | ビームハンマー (melee) |
| `54 A0 7D 04` | `0x047DA054` | シーラ・クロノス leg |
| `B2 98 D4 A7` | `0xA7D498B2` | long equip-record head (ends near fist ID) |

**Native list files:**

| File | Role |
|------|------|
| `cmn/res/item/item_config.cfg.bin` | Short CORE/WEAR/WEAPON catalog (`ITEM_*` CRC tags) |
| `cmn/res/menu/agesystem_config_0.01a.cfg.nat` | Full AGE System index (~305 IDs, ~32-byte records) |
| `cmn/res/menu/database.cfg.bin` | Loadouts: core/arm/leg ID combos |
| `cmn/txt/jp/menu/dbMSText.bin` | Unit display names + long descriptions |
| `cmn/res/shp/shop-sh*.cfg.nat` | Shop stock (lance/hammer etc.) |

**agesystem record sketch** (wear example around AGE-1 red arm/leg):

```text
tag0  flags=00170005  tag2  typ=00000003  item_id  field_a  field_b  trailer=007D000A
```

Weapons often use `flags=00170003`, trailer `007D0007`.  
Secondary fields **did not** CRC-match `DefaultLib.ms*` strings or folder names in this session — **item ID → `ms*` package join is still open**.

User note to retain: **AGE-2 飞翼手** is important for later wear mapping (not fully resolved this session).

### 2.5 Succeeded: funnel mesh signature + visual confirm

1. Scan every full `ms*000` RES for `DefaultLib.*_fn*` funnel meshes.  
2. **Only `ms010000`** among full bodies references:

   ```text
   ms010100_01, ms010200_01, ms010200_fn1,
   ms010300_01, ms010300_fn1,
   ms010400_01, ms010400_fn1
   ```

3. Export + multi-view Blender preview → white/blue AGE-FX silhouette (V-fin, binders, C-Funnel hardpoints).  
4. **User confirmed: “是这个了”.**

Supporting text hits (names only, not package IDs):

- `dbMSText.bin`, `mselectText.bin`, `game_common_pack.bin`  
- Story events under `cmn/txt/jp/evt/ev10_*`, `ev11_*`  
- Period packs `ph411_*` dialogue mentioning AGE-FX  

---

## 3. Confirmed package identity

| Field | Value |
|-------|--------|
| Unit (EN) | Gundam AGE-FX |
| Unit (JP) | ガンダムＡＧＥ－ＦＸ |
| Burst mode name | ガンダムＡＧＥ－ＦＸ（ＦＸバースト） |
| **Character package** | **`ms010000`** |
| Full archive | `psp/chr/ms010000/ms010000_p000.xc` |
| Control package | `ms008000` = Dark Hound (confirmed earlier) |

Story / battle co-presence:

| Asset | Packages |
|-------|----------|
| `psp/btl/ga_ws_18_0040.xb` | `ms010000` + **`fn010000`** |
| `psp/btl/ga_ws_18_0041.xb` | `ms010000` + **`fn002000`** |
| `psp/evt/ev11/ev11_0200/*` | `ms010000`, `fn010000` |
| `psp/evt/ev11/ev11_0800/*` | `ms010000`, `fn010000`, `fn002000` |

---

## 4. Full body / part map

### 4.1 Meshes inside `ms010000_p000.xc` (8 PRMs)

| Mesh name | Role | Verts (export) | Notes |
|-----------|------|---------------:|-------|
| `ms010000_model.ms010100` | Head + upper core | 966 | Joints include head |
| `ms010000_model.ms010200` | Arms / hands | 1265 | Hand bones `r_hand01`, `l_hand01` |
| `ms010000_model.ms010200_fn1` | Arm C-Funnel hardpoints | 264 | Geometry mount, not remote funnel |
| `ms010000_model.ms010300` | Legs | 1405 | Full L/R leg chains |
| `ms010000_model.ms010300_fn1` | Leg hardpoints | 532 | |
| `ms010000_model.ms010400` | Backpack / wing binders | 1217 | Separate joint tree from torso |
| `ms010000_model.ms010400_2` | Backpack secondary | 744 | |
| `ms010000_model.ms010400_fn1` | Backpack hardpoints | 617 | |

Role assignment uses **glTF/MBN joint hierarchy** (not name order alone):

- Under torso (`E9308798`): head joint, **both leg chains**, arm meshes  
- Sibling backpack root (`9D9E0B65`): **ms010400** family (`r_shc*` / `l_shc*` style binders)

### 4.2 Skeleton names from RES (full body)

```text
c_gbl, c_c1, c_c1up, c_c2, c_c3, c_c1lo, c_head,
r_a1, r_a1ura, r_a2, r_a3, r_a4, r_hand01, r_shc21, r_shc11, r_shc01,
l_a1, l_a1ura, l_a2, l_a3, l_a4, l_hand01, l_shc21, l_shc01, l_shc11,
l_l1, l_l2, l_l3, r_l1, r_l2, r_l3,
l_skt01, l_skt11, r_skt01, c_skt01, r_skt11
```

Export glTF: **36 nodes**, **8 skins**, weighted vertices fully mapped (`unmapped_weight_record_count = 0` on sample).

### 4.3 On-disk modular packages

| Package folder file | Contents | Standalone dir? |
|---------------------|----------|-----------------|
| `ms010000_p000.xc` | All 8 meshes + full skeleton + 4 XI textures | yes |
| `ms010100_p000.xc` | `ms010100` + **`ms010200` + `ms010200_fn1`** | under `ms010000/` |
| `ms010300_p000.xc` | `ms010300` + `ms010300_fn1` | under `ms010000/` |
| `ms010400_p000.xc` | `ms010400` + `_2` + `_fn1` | under `ms010000/` |
| *(no `ms010200_p000.xc`)* | Arms only via full / `ms010100` | **no** |

Textures on full body: **4** PNG (`000`–`003`) after pipeline convert.

### 4.4 Weapons

| Package | Role | Bones | Evidence |
|---------|------|-------|----------|
| **`fn010000`** | Ｃファンネル primary | `l_fnl1–7`, `r_fnl1–7` | Battle 0040, multiple ev11 events |
| **`fn002000`** | C-Funnel alternate | same pattern | Battle 0041, ev11_0800 |

**Handheld / AGE System weapons (this session):**

- Text list includes **ＦＸビームザンバー**, generic beam saber names, **ロングレンジライフル**, etc.  
- **No** `rf*` / `sw*` / `gu*` package co-referenced with `ms010000` in battles/events scanned.  
- Unit EX weapon text for AGE-FX is **Ｃファンネル**.  
- Shared equippable weapons likely go through item IDs (`item_config` / agesystem), not exclusive `ms010*` archives — **join not finished**.

---

## 5. Tooling built / improved this session

| Tool | Path | Purpose |
|------|------|---------|
| FX native index (effects) | `tools/age_fx_index.py` | Parse `effect_config*` → package list (**effects**, not MS) |
| Blender headless preview | `tools/age_blender_preview.py` | glTF/OBJ → multi-view PNG (front/side/perspective) |
| CLI entry | `tools/age_start.py` | `fx-index`, `preview`, existing `character` |
| Tests | `tools/tests/test_age_fx_index.py`, `test_age_blender_preview.py` | Unit coverage for new tools |
| Temp research scripts | `tools/_tmp_hashmap.py`, `_tmp_ms_map.py`, `_tmp_parse_items.py` | Hash / name mapping probes |

**Character export path (working):**

```powershell
python tools/age_start.py character "<xc>" --out-dir <out> --name <name> --overwrite
# produces: models/*_strip.gltf + .bin + .weights.json, textures/*.png, extracted/
```

**Preview path:**

```powershell
python tools/age_start.py preview <gltf> --out-dir outputs/age_fx_ms/previews --views front,side,perspective
```

Camera framing notes (Blender worker): skin bake / armature rest, AABB + padding ~1.65 FOV — early bugs caused leg-only or empty frames; fixed before ID sheet work.

---

## 6. Export outputs (session artifacts)

Root: `outputs/age_fx_ms/`

| Directory / file | Description |
|------------------|-------------|
| `ms010000_p000/` | Full AGE-FX skinned export |
| `ms010100_p000/` | Head + arms pack |
| `ms010300_p000/` | Legs pack |
| `ms010400_p000/` | Backpack pack |
| `fn010000_p000/` | C-Funnel primary |
| `fn002000_p000/` | C-Funnel alt |
| `previews/` | Blender PNGs (full + parts + older rejected candidates) |
| `AGE_FX_PARTS.md` | Part inventory (user-facing) |
| `AGE_FX_PARTS_INVENTORY.json` | Machine-readable inventory |
| Older `ms008/041/042/104/…` | Rejected candidates (kept for comparison) |

Also: early wrong effect tree `outputs/fx/` (do not confuse with AGE-FX suit).

---

## 7. Identification playbook (reproducible)

1. **Do not** map `dbMSText` order linearly onto `ms*` folder order.  
2. Prefer **structural RES signatures**:  
   - AGE-FX: only full MS with `DefaultLib.ms*_fn1` funnel hardpoint meshes.  
3. Cross-check **battle/event XPCK** co-bundling (`ga_ws_18_0040/41`, `ev11_*`).  
4. Confirm with **Blender multi-view** full-body frames (not legs-only crops).  
5. Weapons for this suit: start from `fn010000` / `fn002000`, not `psp/eff`.  

---

## 8. Open work (not finished this session)

1. **Item ID → model package reverse map** for AGE System (agesystem secondary fields → `DefaultLib.ms*` / `fn*` / `rf*` / `sw*`).  
2. **AGE-FX default wear triple** (core/arm/leg item IDs) if present in `database.cfg.bin`.  
3. **Handheld default weapons** for AGE-FX if any exclusive beyond C-Funnel (FX Beam Zamber model package still unknown).  
4. **AGE-2 飞翼手** package ID (user flag as important).  
5. Optional: FX Burst as visual/mode only vs separate mesh set (`fn002000` may be burst funnel set).  
6. Clean up or quarantine rejected candidate exports if disk space matters.  
7. Disambiguate docs: rename or banner that `age_fx_index` = **effects**, not AGE-FX MS.

---

## 9. Quick re-export commands

```powershell
cd E:\research\Gundam-AGE-PSP
$env:PYTHONPATH = "tools"
$R = "D:\PPSSPP\AGE解包\资源解包\psp\chr"

python tools/age_start.py character "$R\ms010000\ms010000_p000.xc" --out-dir outputs/age_fx_ms/ms010000_p000 --name ms010000_p000 --overwrite
python tools/age_start.py character "$R\ms010000\ms010100_p000.xc" --out-dir outputs/age_fx_ms/ms010100_p000 --name ms010100_p000 --overwrite
python tools/age_start.py character "$R\ms010000\ms010300_p000.xc" --out-dir outputs/age_fx_ms/ms010300_p000 --name ms010300_p000 --overwrite
python tools/age_start.py character "$R\ms010000\ms010400_p000.xc" --out-dir outputs/age_fx_ms/ms010400_p000 --name ms010400_p000 --overwrite
python tools/age_start.py character "$R\fn010000\fn010000_p000.xc" --out-dir outputs/age_fx_ms/fn010000_p000 --name fn010000_p000 --overwrite
python tools/age_start.py character "$R\fn002000\fn002000_p000.xc" --out-dir outputs/age_fx_ms/fn002000_p000 --name fn002000_p000 --overwrite

python tools/age_start.py preview outputs/age_fx_ms/ms010000_p000/models/ms010000_p000_strip.gltf --out-dir outputs/age_fx_ms/previews --views front,side,perspective
```

---

## 10. Document index for this session

| Doc | Content |
|-----|---------|
| **This file** | Full session narrative + decisions + open work |
| `docs/AGE_ITEM_HASH_INDEX.md` | User hash dumps + AGE-FX resolve pointer |
| `docs/AGE_FX_NATIVE_INDEX_RESEARCH.md` | Particle effect native catalogs (name collision) |
| `docs/RESEARCH_LOG.md` | Dated log entry pointing here |
| `outputs/age_fx_ms/AGE_FX_PARTS.md` | Canonical part/weapon inventory |
| `outputs/age_fx_ms/AGE_FX_PARTS_INVENTORY.json` | JSON inventory |
| `outputs/manifests/ms_name_to_package_hypothesis.json` | **Invalid** linear map (kept as negative evidence) |

---

*End of session record 2026-07-25.*
