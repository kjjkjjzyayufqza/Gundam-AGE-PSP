//! IMGP (`.xi`) indexed texture decoding for Gundam AGE PSP.
//!
//! Ported from `tools/age_imgp_tool.py`. The payload is a 0x58-byte header
//! followed by three Level-5 blocks: palette, tile table, indexed pixels.
//! Pixels are rebuilt through the tile table and then deswizzled from the PSP
//! 16-byte x 8-row layout before palette lookup.

use crate::level5;
use anyhow::{Result, bail};

pub const MAGIC: &[u8; 4] = b"IMGP";
const HEADER_SIZE: usize = 0x58;
const SWIZZLE_BLOCK_WIDTH: usize = 16;
const SWIZZLE_BLOCK_HEIGHT: usize = 8;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PixelLayout {
    /// PSP 16-byte x 8-row swizzle (the AGE PSP default).
    PspSwizzled,
    Linear,
    Tiled8x8,
}

#[derive(Clone, Debug)]
pub struct Header {
    pub version: String,
    pub format_code: u8,
    pub bit_depth: u8,
    pub pitch_width: u16,
    pub width: u32,
    pub height: u32,
    pub data_start: usize,
    pub color_count: u16,
    pub palette_count: u16,
    pub palette_block_size: usize,
    pub table_block_size: usize,
    pub pixel_block_offset: usize,
    pub pixel_block_size: usize,
}

#[derive(Clone, Debug)]
pub struct BlockInfo {
    pub palette_method: level5::Method,
    pub table_method: level5::Method,
    pub pixel_method: level5::Method,
    pub tile_entry_size: usize,
    pub tile_count: usize,
}

/// A decoded RGBA texture.
#[derive(Clone)]
pub struct Texture {
    pub width: u32,
    pub height: u32,
    pub bit_depth: u8,
    /// Row-major RGBA8, `width * height` entries.
    pub pixels: Vec<[u8; 4]>,
    pub blocks: BlockInfo,
}

impl Texture {
    pub fn rgba_bytes(&self) -> Vec<u8> {
        let mut out = Vec::with_capacity(self.pixels.len() * 4);
        for p in &self.pixels {
            out.extend_from_slice(p);
        }
        out
    }

    pub fn has_transparency(&self) -> bool {
        self.pixels.iter().any(|p| p[3] < 255)
    }
}

fn u16_at(data: &[u8], offset: usize) -> u16 {
    u16::from_le_bytes([data[offset], data[offset + 1]])
}

fn u32_at(data: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes([
        data[offset],
        data[offset + 1],
        data[offset + 2],
        data[offset + 3],
    ])
}

pub fn parse_header(data: &[u8]) -> Result<Header> {
    if data.len() < HEADER_SIZE {
        bail!("too small for an IMGP header ({} bytes)", data.len());
    }
    if &data[0..4] != MAGIC {
        bail!("not an IMGP texture (magic {:02X?})", &data[0..4]);
    }

    let mut data_start = u32_at(data, 0x1C) as usize;
    if data_start == 0 || data_start >= data.len() {
        data_start = HEADER_SIZE;
    }

    let version = String::from_utf8_lossy(&data[4..8])
        .trim_end_matches('\0')
        .to_string();

    Ok(Header {
        version,
        format_code: data[0x0A],
        bit_depth: data[0x0D],
        pitch_width: u16_at(data, 0x0E),
        width: u16_at(data, 0x10) as u32,
        height: u16_at(data, 0x12) as u32,
        data_start,
        color_count: u16_at(data, 0x38),
        palette_count: u16_at(data, 0x3A),
        palette_block_size: u32_at(data, 0x40) as usize,
        table_block_size: u32_at(data, 0x44) as usize,
        pixel_block_offset: u32_at(data, 0x48) as usize,
        pixel_block_size: u32_at(data, 0x4C) as usize,
    })
}

fn read_block(
    data: &[u8],
    start: usize,
    size: usize,
    label: &str,
) -> Result<(level5::Method, Vec<u8>)> {
    if start > data.len() || start + size > data.len() {
        bail!("IMGP {label} block range is outside the file (start=0x{start:X}, size={size})");
    }
    level5::decompress(&data[start..start + size])
        .map_err(|e| anyhow::anyhow!("IMGP {label} block: {e}"))
}

/// Tile table entries are u16 unless the block is the 0x0453-tagged u32 variant.
fn parse_tile_table(table: &[u8]) -> (Vec<u32>, usize) {
    if table.len() >= 2 && u16_at(table, 0) == 0x0453 {
        let mut entries = Vec::new();
        let mut off = 8;
        while off + 4 <= table.len() {
            entries.push(u32_at(table, off));
            off += 4;
        }
        return (entries, 4);
    }
    let mut entries = Vec::new();
    let mut off = 0;
    while off + 2 <= table.len() {
        entries.push(u16_at(table, off) as u32);
        off += 2;
    }
    (entries, 2)
}

fn build_ordered_tiles(
    entries: &[u32],
    pixel_data: &[u8],
    tile_size: usize,
    entry_size: usize,
) -> Vec<u8> {
    let empty_marker: u32 = if entry_size == 4 { 0xFFFF_FFFF } else { 0xFFFF };
    let mut out = Vec::with_capacity(entries.len() * tile_size);
    for &entry in entries {
        if entry == empty_marker {
            out.extend(std::iter::repeat_n(0u8, tile_size));
            continue;
        }
        let start = entry as usize * tile_size;
        match pixel_data.get(start..start + tile_size) {
            Some(tile) => out.extend_from_slice(tile),
            None => out.extend(std::iter::repeat_n(0u8, tile_size)),
        }
    }
    out
}

fn palette_to_rgba(palette: &[u8], color_count: u16) -> Vec<[u8; 4]> {
    let max_colors = (color_count as usize).min(palette.len() / 4);
    let mut colors: Vec<[u8; 4]> = (0..max_colors)
        .map(|i| {
            let b = &palette[i * 4..i * 4 + 4];
            [b[0], b[1], b[2], b[3]]
        })
        .collect();
    if colors.is_empty() {
        colors.push([0, 0, 0, 0]);
    }
    colors
}

fn indexed_row_bytes(width: u32, bit_depth: u8) -> usize {
    (width as usize * bit_depth as usize + 7) / 8
}

/// Convert PSP-swizzled indexed bytes into linear row-major order.
fn psp_deswizzle(swizzled: &[u8], width: u32, height: u32, bit_depth: u8) -> Vec<u8> {
    let row_bytes = indexed_row_bytes(width, bit_depth);
    let height = height as usize;
    let mut linear = vec![0u8; row_bytes * height];

    let block_cols = (row_bytes + SWIZZLE_BLOCK_WIDTH - 1) / SWIZZLE_BLOCK_WIDTH;
    let block_rows = (height + SWIZZLE_BLOCK_HEIGHT - 1) / SWIZZLE_BLOCK_HEIGHT;
    let mut src = 0usize;

    for block_y in 0..block_rows {
        for block_x in 0..block_cols {
            for y in 0..SWIZZLE_BLOCK_HEIGHT {
                let dst_y = block_y * SWIZZLE_BLOCK_HEIGHT + y;
                if dst_y < height {
                    let col_start = block_x * SWIZZLE_BLOCK_WIDTH;
                    let copy = SWIZZLE_BLOCK_WIDTH.min(row_bytes.saturating_sub(col_start));
                    if copy > 0 {
                        let dst = dst_y * row_bytes + col_start;
                        let available = swizzled.len().saturating_sub(src).min(copy);
                        if available > 0 {
                            linear[dst..dst + available]
                                .copy_from_slice(&swizzled[src..src + available]);
                        }
                    }
                }
                src += SWIZZLE_BLOCK_WIDTH;
            }
        }
    }

    linear
}

fn render_linear(
    index_bytes: &[u8],
    width: u32,
    height: u32,
    bit_depth: u8,
    palette: &[[u8; 4]],
) -> Result<Vec<[u8; 4]>> {
    let expected = width as usize * height as usize;
    let fallback = [255u8, 0, 255, 255];
    let mut pixels = Vec::with_capacity(expected);

    match bit_depth {
        8 => {
            for &index in index_bytes.iter().take(expected) {
                pixels.push(*palette.get(index as usize).unwrap_or(&fallback));
            }
        }
        4 => {
            let limit = indexed_row_bytes(width, 4) * height as usize;
            for &byte in index_bytes.iter().take(limit) {
                for index in [byte & 0x0F, (byte >> 4) & 0x0F] {
                    if pixels.len() == expected {
                        break;
                    }
                    pixels.push(*palette.get(index as usize).unwrap_or(&fallback));
                }
                if pixels.len() == expected {
                    break;
                }
            }
        }
        other => bail!("unsupported IMGP bit depth {other}; expected 4 or 8"),
    }

    pixels.resize(expected, [0, 0, 0, 0]);
    Ok(pixels)
}

fn render_tiles(
    ordered: &[u8],
    width: u32,
    height: u32,
    bit_depth: u8,
    palette: &[[u8; 4]],
) -> Result<Vec<[u8; 4]>> {
    let tile_size = 64 * bit_depth as usize / 8;
    let tile_cols = ((width + 7) / 8) as usize;
    let tile_rows = ((height + 7) / 8) as usize;
    let fallback = [255u8, 0, 255, 255];
    let mut pixels = vec![[0u8, 0, 0, 0]; width as usize * height as usize];

    for tile_index in 0..tile_cols * tile_rows {
        let start = tile_index * tile_size;
        let Some(tile) = ordered.get(start..start + tile_size) else {
            break;
        };
        let local: Vec<u8> = match bit_depth {
            8 => tile[..64].to_vec(),
            4 => {
                let mut v = Vec::with_capacity(64);
                for &byte in &tile[..32] {
                    v.push(byte & 0x0F);
                    v.push((byte >> 4) & 0x0F);
                }
                v
            }
            other => bail!("unsupported IMGP bit depth {other}; expected 4 or 8"),
        };

        let tile_x = tile_index % tile_cols;
        let tile_y = tile_index / tile_cols;
        for y in 0..8 {
            let dst_y = tile_y * 8 + y;
            if dst_y >= height as usize {
                continue;
            }
            for x in 0..8 {
                let dst_x = tile_x * 8 + x;
                if dst_x >= width as usize {
                    continue;
                }
                let index = local[y * 8 + x] as usize;
                pixels[dst_y * width as usize + dst_x] = *palette.get(index).unwrap_or(&fallback);
            }
        }
    }

    Ok(pixels)
}

/// Decode an IMGP `.xi` payload into an RGBA texture.
pub fn decode(data: &[u8], layout: PixelLayout) -> Result<Texture> {
    let header = parse_header(data)?;
    if header.width == 0 || header.height == 0 {
        bail!("IMGP has a zero dimension ({}x{})", header.width, header.height);
    }

    let palette_start = header.data_start;
    let table_start = header.data_start + header.palette_block_size;
    let pixel_start = header.data_start + header.pixel_block_offset;

    let (palette_method, palette) =
        read_block(data, palette_start, header.palette_block_size, "palette")?;
    let (table_method, table) = read_block(data, table_start, header.table_block_size, "tile table")?;
    let (pixel_method, pixel_data) =
        read_block(data, pixel_start, header.pixel_block_size, "pixel")?;

    let (entries, entry_size) = parse_tile_table(&table);
    let tile_size = 64 * header.bit_depth as usize / 8;
    if tile_size == 0 {
        bail!("unsupported IMGP bit depth {}", header.bit_depth);
    }
    let ordered = build_ordered_tiles(&entries, &pixel_data, tile_size, entry_size);
    let rgba_palette = palette_to_rgba(&palette, header.color_count);

    let pixels = match layout {
        PixelLayout::PspSwizzled => {
            let linear = psp_deswizzle(&ordered, header.width, header.height, header.bit_depth);
            render_linear(
                &linear,
                header.width,
                header.height,
                header.bit_depth,
                &rgba_palette,
            )?
        }
        PixelLayout::Linear => render_linear(
            &ordered,
            header.width,
            header.height,
            header.bit_depth,
            &rgba_palette,
        )?,
        PixelLayout::Tiled8x8 => render_tiles(
            &ordered,
            header.width,
            header.height,
            header.bit_depth,
            &rgba_palette,
        )?,
    };

    Ok(Texture {
        width: header.width,
        height: header.height,
        bit_depth: header.bit_depth,
        pixels,
        blocks: BlockInfo {
            palette_method,
            table_method,
            pixel_method,
            tile_entry_size: entry_size,
            tile_count: entries.len(),
        },
    })
}

/// Encode a decoded texture as PNG bytes.
pub fn encode_png(texture: &Texture) -> Result<Vec<u8>> {
    use image::{ImageEncoder, codecs::png::PngEncoder};
    let mut out = Vec::new();
    PngEncoder::new(&mut out).write_image(
        &texture.rgba_bytes(),
        texture.width,
        texture.height,
        image::ExtendedColorType::Rgba8,
    )?;
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deswizzle_restores_row_order_for_one_block_row() {
        // 16 bytes wide, 8 rows: a single swizzle block is already linear.
        let swizzled: Vec<u8> = (0..128u8).collect();
        let linear = psp_deswizzle(&swizzled, 32, 8, 4); // 32 px @4bpp = 16 row bytes
        assert_eq!(linear, swizzled);
    }

    #[test]
    fn deswizzle_interleaves_two_horizontal_blocks() {
        // 32 row bytes => 2 blocks per row; block 0 holds rows 0..8 col 0..16.
        let mut swizzled = vec![0u8; 32 * 8];
        for (i, slot) in swizzled.iter_mut().enumerate() {
            *slot = (i / 16) as u8; // one distinct value per 16-byte chunk
        }
        let linear = psp_deswizzle(&swizzled, 64, 8, 4); // 64 px @4bpp = 32 row bytes
        // Row 0 first half comes from chunk 0, second half from chunk 8.
        assert_eq!(linear[0], 0);
        assert_eq!(linear[16], 8);
        // Row 1 first half comes from chunk 1.
        assert_eq!(linear[32], 1);
    }

    #[test]
    fn palette_lookup_expands_4bpp_low_nibble_first() {
        let palette = vec![[1, 1, 1, 255], [2, 2, 2, 255], [3, 3, 3, 255]];
        // byte 0x21 -> indices 1 then 2
        let pixels = render_linear(&[0x21], 2, 1, 4, &palette).unwrap();
        assert_eq!(pixels, vec![[2, 2, 2, 255], [3, 3, 3, 255]]);
    }

    #[test]
    fn tile_table_detects_u32_variant() {
        let mut table = vec![0u8; 16];
        table[0..2].copy_from_slice(&0x0453u16.to_le_bytes());
        table[8..12].copy_from_slice(&7u32.to_le_bytes());
        table[12..16].copy_from_slice(&9u32.to_le_bytes());
        let (entries, size) = parse_tile_table(&table);
        assert_eq!(size, 4);
        assert_eq!(entries, vec![7, 9]);
    }

    #[test]
    fn tile_table_defaults_to_u16_entries() {
        let table = [1u8, 0, 2, 0, 3, 0];
        let (entries, size) = parse_tile_table(&table);
        assert_eq!(size, 2);
        assert_eq!(entries, vec![1, 2, 3]);
    }

    #[test]
    fn empty_tile_marker_produces_zero_fill() {
        let ordered = build_ordered_tiles(&[0xFFFF], &[9u8; 32], 32, 2);
        assert_eq!(ordered, vec![0u8; 32]);
    }
}
