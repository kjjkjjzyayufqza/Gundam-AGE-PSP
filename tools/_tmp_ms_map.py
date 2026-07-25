from pathlib import Path
import re, json, struct

unpack = Path(r"D:\PPSSPP\AGE解包\资源解包")
db = (unpack / "cmn/txt/jp/menu/dbMSText.bin").read_bytes()

# Split on nulls, decode cp932, keep MS-like short titles
parts = db.split(b"\x00")
names = []
for p in parts:
    if not p:
        continue
    try:
        s = p.decode("cp932")
    except Exception:
        continue
    # short unit names typically one line without long description
    if "\n" in s or len(s) > 40:
        continue
    if re.search(r"ガンダム|ジェノアス|アデル|クラン|エグゼス|バウンサー|ティエル|シャルドール|デスペラード|ジラ|ガラ|ゼノ|エルメダ|ガフラン|バクト|ゼダス|ドラド|クロノス|ゼイドラ|ギラーガ|レギルス|シド|ヴェイガン|ジム|ザク|グフ|ドム|ズゴック|ギャン|ゲルググ|ジオング|ユニコーン|ストライク|ジン|プロヴィデンス|デスティニー|ジャスティス|エクシア|デュナメス|キュリオス|ヴァーチェ|ジンクス|リボーンズ|ダブルオー|ファラ|フォーン|グルド|ザムド|ダージ|ファルシア|ウィゲル|ダナジン|レガンナー|ゴメル|ウロッゾ|グルード|エゴス|ジルス|ザガ|アビゲル|メトル|ベラジ|オルガ|アルモ|ヘザー|セロ|コール|ノマド|ボラル|キール|ワイズ|シーラ", s):
        names.append(s)
    elif re.match(r"^[ァ-ヶーA-Za-z0-9Ａ-Ｚａ-ｚ－−・]+$", s) and 2 <= len(s) <= 24:
        # katakana unit short names
        if re.search(r"ガフ|バクト|ゼダ|ドラ|クロ|ゼイ|ギラ|シド|ガラ|ジラ|ゼノ|エル|シャル|デスペ|アデル|クラン|エグゼ|バウン|ティエ|フォーン|ファル|ダージ|グル|ザム|エゴ|レガ|ゴメ|ウロ|アビ|メト|ベラ|オル|アル|ヘザ|セロ|コール|ノマ|ボラ|キー|ワイ|シー", s):
            names.append(s)

# Better approach: extract consecutive short names block that starts at AGE-1 Normal
text = db.decode("cp932", errors="ignore")
# Find the block of short names
m = re.search(r"ガンダムＡＧＥ－１ノーマル", text)
print("found AGE-1 at", m.start() if m else None)
if m:
    block = text[m.start(): m.start()+8000]
    # pull names that look like unit titles (no newlines, short)
    # scan null-separated from original
    # re-find index of AGE-1 in parts list
    idx = None
    decoded_parts = []
    for p in parts:
        try:
            decoded_parts.append(p.decode("cp932"))
        except Exception:
            decoded_parts.append(None)
    for i, s in enumerate(decoded_parts):
        if s == "ガンダムＡＧＥ－１ノーマル":
            idx = i
            break
    print("parts index", idx)
    unit_names = []
    if idx is not None:
        for s in decoded_parts[idx:]:
            if s is None:
                continue
            if "\n" in s or len(s) > 36:
                # stop when we hit long descriptions again? Actually short names are contiguous
                # only accept short
                continue
            # stop if clearly not a unit (menu labels)
            if s in ("モビルスーツ",) or s.startswith("["):
                continue
            if re.search(r"ガンダム|ジェノアス|アデル|クラン|エグゼス|バウンサー|ティエル|シャルドール|デスペラード|ジラ|ガラ|ゼノ|エルメダ|ガフラン|バクト|ゼダス|ドラド|クロノス|ゼイドラ|ギラーガ|レギルス|シド|ヴェイガン|ジム|ザク|グフ|ドム|ズゴック|ギャン|ゲルググ|ジオング|ユニコーン|ストライク|ジン|プロヴィデンス|デスティニー|ジャスティス|エクシア|デュナメス|キュリオス|ヴァーチェ|ジンクス|リボーンズ|ダブルオー|ファルシア|フォーン|グルド|ザムド|ダージ|アビゲル|メトル|ダナジン|レガンナー|ゴメル|ウロッゾ|グルード|エゴス|ジルス|ザガ|キール|ワイズ|シーラ|ガラ|ジラ|ゼノ|エルメダ|シャルドール|デスペラード|競技用", s):
                unit_names.append(s)
            elif re.match(r"^[ァ-ヴーＡ-Ｚａ-ｚA-Za-z0-9・－−]+$", s) and 2 < len(s) < 20:
                unit_names.append(s)

print("unit names", len(unit_names))
for i, n in enumerate(unit_names, 1):
    mark = " <<<< AGE-FX" if "ＦＸ" in n or "FX" in n else ""
    mark += " <<<< DARK HOUND" if "ダークハウンド" in n else ""
    print(f"{i:3d} {n}{mark}")

# Map to full ms packages in order
chr_root = unpack / "psp/chr"
full = []
for folder in sorted(chr_root.glob("ms*")):
    p000 = folder / f"{folder.name}_p000.xc"
    if p000.is_file() and folder.name not in ("ms000001", "ms000003", "ms001000_m"):
        # skip non-standard early
        if re.match(r"ms\d{6}$", folder.name):
            full.append(folder.name)

print("\nfull ms packages", len(full))
# Align: first unit name -> first full package?
# User said ms008000 is Dark Hound. Find index of Dark Hound in names and ms008000 in full
dh_name_i = next(i for i,n in enumerate(unit_names) if "ダークハウンド" in n)
ms008_i = full.index("ms008000")
print("Dark Hound name index", dh_name_i+1, "ms008000 package index", ms008_i+1)
# offset
# If names[dh] maps to full[ms008_i], then names[j] maps to full[ms008_i + (j-dh)]

fx_name_i = next(i for i,n in enumerate(unit_names) if "ＡＧＥ－ＦＸ" in n and "バースト" not in n)
print("AGE-FX name index", fx_name_i+1, unit_names[fx_name_i])
fx_pkg_i = ms008_i + (fx_name_i - dh_name_i)
print("predicted package index", fx_pkg_i+1, "id", full[fx_pkg_i] if 0 <= fx_pkg_i < len(full) else "OOB")

# Also try burst
burst_i = next((i for i,n in enumerate(unit_names) if "バースト" in n), None)
if burst_i is not None:
    bi = ms008_i + (burst_i - dh_name_i)
    print("FX Burst index", burst_i+1, "pkg", full[bi] if 0<=bi<len(full) else "OOB")

# Build full mapping for federal gundams portion
mapping = []
for j, name in enumerate(unit_names):
    pi = ms008_i + (j - dh_name_i)
    pkg = full[pi] if 0 <= pi < len(full) else None
    mapping.append({"name_index": j+1, "name": name, "package": pkg})

Path("outputs/manifests").mkdir(parents=True, exist_ok=True)
Path("outputs/manifests/ms_name_to_package_hypothesis.json").write_text(
    json.dumps({
        "anchor": {"name": "ガンダムＡＧＥ－２ダークハウンド", "package": "ms008000"},
        "method": "dbMSText short-name order aligned to full ms*_p000 packages via Dark Hound anchor",
        "mapping": mapping,
    }, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("wrote mapping, AGE-FX entries:")
for m in mapping:
    if m["name"] and ("ＦＸ" in m["name"] or "FX" in m["name"] or "ダーク" in m["name"]):
        print(m)
