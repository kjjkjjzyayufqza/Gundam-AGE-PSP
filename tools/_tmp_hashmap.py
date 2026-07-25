from pathlib import Path
import struct, zlib, re, json, sys
sys.path.insert(0, "tools")
from age_xpck_tool import parse_xpck

unpack = Path(r"D:\PPSSPP\AGE解包\资源解包")

def u32_le_bytes(hex_bytes: str) -> int:
    return struct.unpack("<I", bytes.fromhex(hex_bytes.replace(" ", "")))[0]

# Correct interpretation: user bytes are on-disk LE order
known = {
    u32_le_bytes("BD 35 BA 0B"): "age1_red_arm (user)",
    u32_le_bytes("60 ED D0 F9"): "age1_red_leg (user)",
    u32_le_bytes("CE 41 75 73"): "age1_red_fist (user)",
    u32_le_bytes("C7 1E 9C B9"): "beam_lance (user)",
    u32_le_bytes("B5 60 AF AD"): "beam_hammer (user)",
    u32_le_bytes("54 A0 7D 04"): "shira_chronos_leg (user)",
    u32_le_bytes("6E 79 E4 DD"): "body (user)",
    u32_le_bytes("A3 85 AE 3B"): "hand (user)",
    u32_le_bytes("7E 5D C4 C9"): "leg_a (user)",
    u32_le_bytes("AB A8 2A A6"): "leg_b (user)",
    u32_le_bytes("B2 98 D4 A7"): "blob_head (user long record)",
    u32_le_bytes("DC 5C C6 87"): "field_in_long_record",
    u32_le_bytes("EB 36 04 86"): "field2_in_long_record",
}
print("KNOWN LE values:")
for k, v in known.items():
    print(f"  0x{k:08X}  bytes {struct.pack('<I', k).hex()}  {v}")

# Load item_config extracted IDs from previous parse logic
data = (unpack / "cmn/res/item/item_config.cfg.bin").read_bytes()

def crc(s):
    return zlib.crc32(s.encode()) & 0xFFFFFFFF

WEAPON, WEAR, CORE = map(crc, ["ITEM_WEAPON", "ITEM_WEAR_PARTS", "ITEM_CORE_PARTS"])
ids = []
for off in range(0, len(data) - 32, 4):
    tag = struct.unpack_from("<I", data, off)[0]
    if tag not in (WEAPON, WEAR, CORE):
        continue
    item_id = struct.unpack_from("<I", data, off + 12)[0]
    ids.append((off, tag, item_id))

print("\nitem_config id matches:")
idset = {i for _,_,i in ids}
for k, v in known.items():
    print(v, "0x%08X" % k, "IN_ITEM_CONFIG" if k in idset else "not in short item_config")

# agesystem: collect all unique u32 that look like ids (appear after pattern 03000000 or similar)
age = (unpack / "cmn/res/menu/agesystem_config_0.01a.cfg.nat").read_bytes()
# record pattern from hits: .... 03000000 <id> <u32> <u32> 0a007d00
pat = re.compile(rb"\x03\x00\x00\x00(.{4})", re.S)
found = []
for m in pat.finditer(age):
    item_id = struct.unpack("<I", m.group(1))[0]
    found.append((m.start(), item_id))
uniq = sorted(set(i for _, i in found))
print("\nagesystem ids after 03 00 00 00:", len(uniq))
for k, v in known.items():
    hits = [hex(off) for off,i in found if i == k]
    print(v, "0x%08X" % k, "hits", len(hits), hits[:3])

# Try CRC32 of ms/rf/sh folder names against known + agesystem ids
print("\n=== CRC32 folder names vs known/agesystem ===")
chr_root = unpack / "psp" / "chr"
name_crcs = {}
for p in chr_root.iterdir():
    if not p.is_dir():
        continue
    for variant in [p.name, p.name + "_p000", p.name.upper(), p.name.lower()]:
        for enc in ("ascii",):
            b = variant.encode(enc)
            name_crcs[zlib.crc32(b) & 0xFFFFFFFF] = variant
            name_crcs[zlib.crc32(b + b"\x00") & 0xFFFFFFFF] = variant + "\\0"

age_ids = set(uniq) | set(known) | idset
for c, name in sorted(name_crcs.items(), key=lambda x: x[1]):
    if c in age_ids or c in known:
        print(f"  MATCH 0x{c:08X} <- {name}")

# Also hash RES model strings DefaultLib.ms*
print("\n=== sample RES model string CRCs from ms008000 (Dark Hound) ===")
xc = unpack / "psp/chr/ms008000/ms008000_p000.xc"
from age_xpck_tool import parse_xpck, decompress_level5
arc = parse_xpck(xc)
res = next(e for e in arc.entries if e.name.upper()=="RES.BIN")
payload = xc.read_bytes()[res.absolute_offset:res.end_offset]
try:
    _, payload = decompress_level5(payload)
except Exception:
    pass
strings = re.findall(rb"[\x20-\x7e]{4,64}", payload)
for s in strings:
    t = s.decode("ascii")
    if "ms008" in t or "DefaultLib" in t or "model" in t:
        c = zlib.crc32(s) & 0xFFFFFFFF
        c0 = zlib.crc32(s + b"\x00") & 0xFFFFFFFF
        flag = ""
        if c in age_ids: flag = " **AGE_ID**"
        if c0 in age_ids: flag += " **AGE_ID0**"
        if c in known or c0 in known: flag += " **KNOWN**"
        print(f"  0x{c:08X}/0x{c0:08X} {t}{flag}")

# Search dbMSText for structure: maybe id then string
print("\n=== dbMSText.bin head ===")
dbt = unpack / "cmn/txt/jp/menu/dbMSText.bin"
db = dbt.read_bytes()
print("size", len(db), db[:32].hex())
# extract all JP strings
parts = db.split(b"\x00")
jp = []
for p in parts:
    if not p: continue
    try:
        s = p.decode("cp932")
    except Exception:
        continue
    if re.search(r"AGE|FX|ダーク|クロノス|ランス|ハンマー|レッグ|アーム|コア|ガンダム", s):
        jp.append(s)
print("interesting strings", len(jp))
for s in jp[:80]:
    print(" ", s)
