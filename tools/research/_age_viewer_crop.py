#!/usr/bin/env python3
"""Crop and magnify a region of the UI capture so pixel-level contrast is visible."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

# The Rust crate lives at the repository root, so captures land there.
CRATE = Path(__file__).resolve().parents[2]


def main() -> int:
    source = CRATE / "ui_capture.png"
    if not source.exists():
        print(f"missing {source}")
        return 1

    image = Image.open(source).convert("RGB")
    print(f"source {image.size}")

    regions = {
        "rows": (15, 150, 350, 330),
        "header": (15, 55, 350, 145),
        "right": (1420, 55, 1690, 130),
    }
    for name, box in regions.items():
        crop = image.crop(box)
        scale = 3
        crop = crop.resize((crop.width * scale, crop.height * scale), Image.NEAREST)
        out = CRATE / f"ui_crop_{name}.png"
        crop.save(out)
        print(f"wrote {out} {crop.size}")

    # Report the darkest and brightest text-like pixels per row band so the
    # actual rendered colours are numbers, not impressions.
    for y in range(170, 320, 12):
        band = [image.getpixel((x, y)) for x in range(20, 340)]
        brightest = max(band, key=sum)
        print(f"y={y} brightest=#{brightest[0]:02X}{brightest[1]:02X}{brightest[2]:02X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
