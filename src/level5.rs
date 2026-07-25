//! Level-5 compression decoding used throughout Gundam AGE PSP resources.
//!
//! Compressed blocks begin with a little-endian 32-bit word where the low 3
//! bits select the method and the upper 29 bits hold the decompressed size.
//! Ported from `tools/age_xpck_tool.py`.

use anyhow::{Result, bail};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Method {
    None,
    Lz10,
    Huffman4,
    Huffman8,
    Rle,
    Zlib,
}

impl Method {
    pub fn from_id(id: u8) -> Option<Self> {
        match id {
            0 => Some(Self::None),
            1 => Some(Self::Lz10),
            2 => Some(Self::Huffman4),
            3 => Some(Self::Huffman8),
            4 => Some(Self::Rle),
            5 => Some(Self::Zlib),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Lz10 => "lz10",
            Self::Huffman4 => "huffman4",
            Self::Huffman8 => "huffman8",
            Self::Rle => "rle",
            Self::Zlib => "zlib",
        }
    }
}

/// Read the Level-5 block header: `(method_id, decompressed_size)`.
pub fn peek_header(payload: &[u8]) -> Result<(u8, usize)> {
    if payload.len() < 4 {
        bail!(
            "Level-5 payload is shorter than its 4-byte header ({} bytes)",
            payload.len()
        );
    }
    let word = u32::from_le_bytes([payload[0], payload[1], payload[2], payload[3]]);
    Ok(((word & 0x7) as u8, (word >> 3) as usize))
}

/// Decompress a Level-5 block, returning the method actually used.
pub fn decompress(payload: &[u8]) -> Result<(Method, Vec<u8>)> {
    let (method_id, expected) = peek_header(payload)?;
    let Some(method) = Method::from_id(method_id) else {
        bail!("unsupported Level-5 compression method {method_id}");
    };
    let out = match method {
        Method::None => {
            let end = (4 + expected).min(payload.len());
            payload[4..end].to_vec()
        }
        Method::Lz10 => lz10(payload, expected)?,
        Method::Huffman4 => huffman(payload, expected, 4)?,
        Method::Huffman8 => huffman(payload, expected, 8)?,
        Method::Rle => rle(payload, expected)?,
        Method::Zlib => zlib(payload)?,
    };
    Ok((method, out))
}

/// Convenience wrapper that discards the method.
pub fn decompress_data(payload: &[u8]) -> Result<Vec<u8>> {
    Ok(decompress(payload)?.1)
}

fn lz10(payload: &[u8], expected: usize) -> Result<Vec<u8>> {
    let mut out: Vec<u8> = Vec::with_capacity(expected);
    let mut pos = 4usize;

    while out.len() < expected {
        if pos >= payload.len() {
            bail!("truncated LZ10 flag byte at output offset {}", out.len());
        }
        let flags = payload[pos];
        pos += 1;

        for bit in (0..8).rev() {
            if out.len() >= expected {
                break;
            }
            if flags & (1 << bit) != 0 {
                if pos + 1 >= payload.len() {
                    bail!("truncated LZ10 back-reference at output offset {}", out.len());
                }
                let b1 = payload[pos] as usize;
                let b2 = payload[pos + 1] as usize;
                pos += 2;
                let count = (b1 >> 4) + 3;
                let disp = (((b1 & 0x0F) << 8) | b2) + 1;
                if disp > out.len() {
                    bail!(
                        "invalid LZ10 displacement {disp} at output offset {}",
                        out.len()
                    );
                }
                for _ in 0..count {
                    let byte = out[out.len() - disp];
                    out.push(byte);
                    if out.len() >= expected {
                        break;
                    }
                }
            } else {
                if pos >= payload.len() {
                    bail!("truncated LZ10 literal at output offset {}", out.len());
                }
                out.push(payload[pos]);
                pos += 1;
            }
        }
    }

    out.truncate(expected);
    Ok(out)
}

fn huffman(payload: &[u8], expected: usize, bit_depth: u32) -> Result<Vec<u8>> {
    let mut pos = 4usize;
    if pos + 2 > payload.len() {
        bail!("truncated Huffman tree header");
    }
    let tree_size = payload[pos] as usize;
    let tree_root = payload[pos + 1];
    pos += 2;

    let tree_end = pos + tree_size * 2;
    if tree_end > payload.len() {
        bail!("truncated Huffman tree ({} entries)", tree_size);
    }
    let tree = &payload[pos..tree_end];
    pos = tree_end;

    let symbol_count = expected * 8 / bit_depth as usize;
    let mut symbols: Vec<u8> = Vec::with_capacity(symbol_count);
    let mut node = tree_root;
    let mut next_index: usize = 0;
    let mut bit_index: usize = 0;
    let mut code: u32 = 0;

    while symbols.len() < symbol_count {
        if bit_index % 32 == 0 {
            if pos + 4 > payload.len() {
                bail!("truncated Huffman bitstream after {} symbols", symbols.len());
            }
            code = u32::from_le_bytes([payload[pos], payload[pos + 1], payload[pos + 2], payload[pos + 3]]);
            pos += 4;
        }

        next_index += (((node & 0x3F) as usize) << 1) + 2;
        let bit = (code >> (31 - (bit_index % 32) as u32)) & 1;
        let direction: usize = if bit != 0 { 1 } else { 2 };
        let leaf = ((node >> 5 >> direction) & 1) != 0;
        let child_index = next_index
            .checked_sub(direction)
            .ok_or_else(|| anyhow::anyhow!("Huffman tree traversal underflowed"))?;
        if child_index >= tree.len() {
            bail!("Huffman tree traversal left the tree buffer");
        }
        node = tree[child_index];
        if leaf {
            symbols.push(node);
            node = tree_root;
            next_index = 0;
        }
        bit_index += 1;
    }

    if bit_depth == 8 {
        symbols.truncate(expected);
        return Ok(symbols);
    }

    // 4-bit symbols are packed low nibble first.
    let mut out = vec![0u8; expected];
    for (i, slot) in out.iter_mut().enumerate() {
        let low = symbols.get(2 * i).copied().unwrap_or(0);
        let high = symbols.get(2 * i + 1).copied().unwrap_or(0);
        *slot = low | (high << 4);
    }
    Ok(out)
}

fn rle(payload: &[u8], expected: usize) -> Result<Vec<u8>> {
    let mut out: Vec<u8> = Vec::with_capacity(expected);
    let mut pos = 4usize;

    while out.len() < expected {
        if pos >= payload.len() {
            bail!("truncated RLE flag at output offset {}", out.len());
        }
        let flag = payload[pos];
        pos += 1;
        if flag & 0x80 != 0 {
            if pos >= payload.len() {
                bail!("truncated RLE repeated byte at output offset {}", out.len());
            }
            let repetitions = (flag & 0x7F) as usize + 3;
            let byte = payload[pos];
            pos += 1;
            out.extend(std::iter::repeat_n(byte, repetitions));
        } else {
            let length = flag as usize + 1;
            if pos + length > payload.len() {
                bail!("truncated RLE literal run at output offset {}", out.len());
            }
            out.extend_from_slice(&payload[pos..pos + length]);
            pos += length;
        }
    }

    out.truncate(expected);
    Ok(out)
}

fn zlib(payload: &[u8]) -> Result<Vec<u8>> {
    use std::io::Read;
    let mut decoder = flate2::read::ZlibDecoder::new(&payload[4..]);
    let mut out = Vec::new();
    decoder.read_to_end(&mut out)?;
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn header(method: u8, size: usize) -> [u8; 4] {
        (((size as u32) << 3) | method as u32).to_le_bytes()
    }

    #[test]
    fn peek_header_splits_method_and_size() {
        let block = header(1, 1234);
        assert_eq!(peek_header(&block).unwrap(), (1, 1234));
    }

    #[test]
    fn none_method_returns_raw_payload() {
        let mut block = header(0, 5).to_vec();
        block.extend_from_slice(b"hello world");
        let (method, out) = decompress(&block).unwrap();
        assert_eq!(method, Method::None);
        assert_eq!(out, b"hello");
    }

    #[test]
    fn rle_expands_literal_and_repeat_runs() {
        let mut block = header(4, 7).to_vec();
        // literal run of 3 bytes, then 4 repeats of 0xAA
        block.extend_from_slice(&[0x02, b'a', b'b', b'c']);
        block.extend_from_slice(&[0x81, 0xAA]);
        let (method, out) = decompress(&block).unwrap();
        assert_eq!(method, Method::Rle);
        assert_eq!(out, vec![b'a', b'b', b'c', 0xAA, 0xAA, 0xAA, 0xAA]);
    }

    #[test]
    fn lz10_copies_back_references() {
        let mut block = header(1, 6).to_vec();
        // flags: first 3 literals, 4th token is a back-reference
        block.push(0b0001_0000);
        block.extend_from_slice(&[b'a', b'b', b'c']);
        // count = (0>>4)+3 = 3, disp = 2+1 = 3 -> repeats "abc"
        block.extend_from_slice(&[0x00, 0x02]);
        let (_, out) = decompress(&block).unwrap();
        assert_eq!(out, b"abcabc");
    }

    #[test]
    fn zlib_round_trips() {
        use flate2::{Compression, write::ZlibEncoder};
        use std::io::Write;
        let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(b"level5 zlib payload").unwrap();
        let compressed = encoder.finish().unwrap();

        let mut block = header(5, 19).to_vec();
        block.extend_from_slice(&compressed);
        let (method, out) = decompress(&block).unwrap();
        assert_eq!(method, Method::Zlib);
        assert_eq!(out, b"level5 zlib payload");
    }

    #[test]
    fn truncated_payload_is_an_error() {
        assert!(decompress(&[0x01, 0x00]).is_err());
    }
}
