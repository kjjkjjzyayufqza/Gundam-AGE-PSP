from pathlib import Path
import struct, zlib, re, json

unpack = Path(r"D:\PPSSPP\AGE解包\资源解包")
data = (unpack / "cmn/res/item/item_config.cfg.bin").read_bytes()

def crc(s: str) -> int:
    return zlib.crc32(s.encode("ascii")) & 0xFFFFFFFF

TAGS = {crc(n): n for n in [
    "ITEM_CORE_PARTS_BEGIN","ITEM_CORE_PARTS","ITEM_CORE_PARTS_END",
    "ITEM_WEAR_PARTS_BEGIN","ITEM_WEAR_PARTS","ITEM_WEAR_PARTS_END",
    "ITEM_WEAPON_BEGIN","ITEM_WEAPON","ITEM_WEAPON_END",
    "ITEM_OPTION_PARTS_BEGIN","ITEM_OPTION_PARTS","ITEM_OPTION_PARTS_END",
    "ITEM_NORMAL_BEGIN","ITEM_NORMAL","ITEM_NORMAL_END",
]}
WEAPON, WEAR, CORE, OPT, NORM = map(crc, [
    "ITEM_WEAPON","ITEM_WEAR_PARTS","ITEM_CORE_PARTS","ITEM_OPTION_PARTS","ITEM_NORMAL"
])

# From observed samples, item id sits 12 bytes after section tag for wear/weapon bodies.
records = []
for off in range(0, len(data) - 32, 4):
    tag = struct.unpack_from("<I", data, off)[0]
    if tag not in (WEAPON, WEAR, CORE, OPT, NORM):
        continue
    # Sample wear: tag, f1, f2, item_id  OR tag @ -something
    # age1 arm: d25f8b8b 11555555 5501ffff bd35ba0b
    # Wait LE: 8b8b5fd2 is WEAR. Bytes d2 5f 8b 8b = LE of 0x8b8b5fd2. Yes.
    # Then 11 55 55 55 / 55 01 ff ff / bd 35 ba 0b  => item at +12
    item_id = struct.unpack_from("<I", data, off + 12)[0]
    f1, f2 = struct.unpack_from("<II", data, off + 4)
    records.append({
        "off": off,
        "kind": TAGS[tag],
        "item_id": item_id,
        "f1": f1,
        "f2": f2,
        "raw12": data[off:off+32].hex(),
    })

by_id = {}
for r in records:
    by_id.setdefault(r["item_id"], r)

print("records", len(records), "unique", len(by_id))
for r in records:
    print(f"0x{r['off']:04x} {r['kind']:18s} id=0x{r['item_id']:08X} f1=0x{r['f1']:08X}")

known = {
    0xCE417573: "age1_red_fist",
    0xBD35BA0B: "age1_red_arm",
    0x60EDD0F9: "age1_red_leg",
    0xC71E9CB9: "beam_lance",
    0xB560AFAD: "beam_hammer",
    0x54A07D04: "shira_chronos_leg",
    0x6E79E4DD: "body",
    0xA385AE3B: "hand",
    0x7E5DC4C9: "leg_a",
    0xABA82AA6: "leg_b",
    0xB298D4A7: "blob_head",
}
print("\nKNOWN:")
for i, n in known.items():
    r = by_id.get(i)
    print(n, f"0x{i:08X}", "FOUND" if r else "MISS", r)

# Dump all IDs grouped
out = {
    "source": str(unpack / "cmn/res/item/item_config.cfg.bin"),
    "records": records,
    "unique_item_ids": sorted({r["item_id"] for r in records}),
    "known_map": {f"0x{k:08X}": v for k, v in known.items()},
}
Path("outputs/manifests").mkdir(parents=True, exist_ok=True)
Path("outputs/manifests/item_config_ids.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print("wrote outputs/manifests/item_config_ids.json")

# Parse agesystem_config: dense records with item ids
age = (unpack / "cmn/res/menu/agesystem_config_0.01a.cfg.nat").read_bytes()
print("\nagesystem size", len(age))
# find known ids and 32-byte context
for i, n in known.items():
    b = struct.pack("<I", i)
    pos = 0
    hits = 0
    while hits < 3:
        j = age.find(b, pos)
        if j < 0:
            break
        print(n, "age@", hex(j), age[max(0,j-16):j+48].hex())
        pos = j + 1
        hits += 1
