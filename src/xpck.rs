//! XPCK archive directory parsing for Gundam AGE PSP resources.
//!
//! Ported from `tools/age_xpck_tool.py`. The archive keeps its own bytes so
//! members can be sliced without touching disk again.

use crate::level5;
use anyhow::{Result, bail};
use std::path::{Path, PathBuf};

pub const MAGIC: &[u8; 4] = b"XPCK";
const HEADER_SIZE: usize = 20;
const ENTRY_SIZE: usize = 12;

/// Archive container extensions seen in the AGE PSP resource tree.
pub const ARCHIVE_EXTENSIONS: &[&str] = &["xc", "xb", "xa", "xv", "xk"];

#[derive(Clone, Copy, Debug)]
pub struct Header {
    pub file_count: usize,
    pub variant_nibble: u8,
    pub file_info_offset: usize,
    pub filename_table_offset: usize,
    pub data_offset: usize,
    pub file_info_size: usize,
    pub filename_table_size: usize,
    pub data_size: usize,
}

#[derive(Clone, Debug)]
pub struct Entry {
    pub index: usize,
    pub name: String,
    pub crc32: u32,
    pub offset: usize,
    pub size: usize,
    pub valid: bool,
}

impl Entry {
    /// Lowercase extension without the dot.
    pub fn extension(&self) -> String {
        Path::new(&self.name)
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_ascii_lowercase()
    }

    /// Filename without extension, e.g. `002` for `002.prm`.
    pub fn stem(&self) -> String {
        Path::new(&self.name)
            .file_stem()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_string()
    }
}

pub struct Archive {
    pub path: Option<PathBuf>,
    pub header: Header,
    pub name_table_method: level5::Method,
    pub entries: Vec<Entry>,
    data: Vec<u8>,
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
        bail!("too small for an XPCK header ({} bytes)", data.len());
    }
    if &data[0..4] != MAGIC {
        bail!("not an XPCK archive (magic {:02X?})", &data[0..4]);
    }

    let fc1 = data[4] as usize;
    let fc2 = data[5] as usize;
    Ok(Header {
        file_count: ((fc2 & 0x0F) << 8) | fc1,
        variant_nibble: ((fc2 & 0xF0) >> 4) as u8,
        file_info_offset: (u16_at(data, 6) as usize) << 2,
        filename_table_offset: (u16_at(data, 8) as usize) << 2,
        data_offset: (u16_at(data, 10) as usize) << 2,
        file_info_size: (u16_at(data, 12) as usize) << 2,
        filename_table_size: (u16_at(data, 14) as usize) << 2,
        data_size: (u32_at(data, 16) as usize) << 2,
    })
}

/// Read a NUL-terminated name out of the decompressed filename table.
fn read_name(names: &[u8], offset: usize) -> String {
    if offset >= names.len() {
        return format!("entry_{offset:08x}.bin");
    }
    let end = names[offset..]
        .iter()
        .position(|b| *b == 0)
        .map(|p| offset + p)
        .unwrap_or(names.len());
    let raw = &names[offset..end];
    if raw.is_empty() {
        return format!("entry_{offset:08x}.bin");
    }
    String::from_utf8_lossy(raw).replace('\\', "/")
}

impl Archive {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        let data = std::fs::read(path)
            .map_err(|e| anyhow::anyhow!("could not read {}: {e}", path.display()))?;
        let mut archive = Self::parse(data)?;
        archive.path = Some(path.to_path_buf());
        Ok(archive)
    }

    pub fn parse(data: Vec<u8>) -> Result<Self> {
        let header = parse_header(&data)?;

        if header.file_info_offset + header.file_count * ENTRY_SIZE > data.len() {
            bail!("XPCK entry table extends beyond the file");
        }
        let name_end = header.filename_table_offset + header.filename_table_size;
        if name_end > data.len() {
            bail!("XPCK filename table extends beyond the file");
        }

        let (name_table_method, names) =
            level5::decompress(&data[header.filename_table_offset..name_end])
                .map_err(|e| anyhow::anyhow!("XPCK filename table: {e}"))?;

        let mut entries = Vec::with_capacity(header.file_count);
        for index in 0..header.file_count {
            let base = header.file_info_offset + index * ENTRY_SIZE;
            let crc32 = u32_at(&data, base);
            let name_offset = u16_at(&data, base + 4) as usize;
            let off_low = u16_at(&data, base + 6) as usize;
            let size_low = u16_at(&data, base + 8) as usize;
            let off_high = data[base + 10] as usize;
            let size_high = data[base + 11] as usize;

            let offset = header.data_offset + (((off_high << 16) | off_low) << 2);
            let size = (size_high << 16) | size_low;
            let valid = offset <= data.len() && offset + size <= data.len();

            entries.push(Entry {
                index,
                name: read_name(&names, name_offset),
                crc32,
                offset,
                size,
                valid,
            });
        }

        Ok(Self {
            path: None,
            header,
            name_table_method,
            entries,
            data,
        })
    }

    pub fn total_size(&self) -> usize {
        self.data.len()
    }

    /// Raw bytes of one member, or `None` when the recorded range is invalid.
    pub fn member(&self, index: usize) -> Option<&[u8]> {
        let entry = self.entries.get(index)?;
        if !entry.valid {
            return None;
        }
        Some(&self.data[entry.offset..entry.offset + entry.size])
    }

    /// Case-insensitive member lookup by exact file name.
    pub fn member_by_name(&self, name: &str) -> Option<&[u8]> {
        let wanted = name.to_ascii_lowercase();
        let index = self
            .entries
            .iter()
            .position(|e| e.name.to_ascii_lowercase() == wanted)?;
        self.member(index)
    }

    /// All members whose lowercase extension matches, sorted by name.
    pub fn entries_with_extension(&self, ext: &str) -> Vec<&Entry> {
        let mut found: Vec<&Entry> = self
            .entries
            .iter()
            .filter(|e| e.valid && e.extension() == ext)
            .collect();
        found.sort_by(|a, b| a.name.cmp(&b.name));
        found
    }

    /// True when a member looks like a nested XPCK archive.
    pub fn member_is_archive(&self, index: usize) -> bool {
        self.member(index)
            .map(|b| b.len() >= 4 && &b[0..4] == MAGIC)
            .unwrap_or(false)
    }
}

/// Cheap member listing for indexing: reads only the header, entry table and
/// name table instead of the whole archive.
pub fn scan_members(path: &Path) -> Result<Vec<(String, usize)>> {
    use std::io::{Read, Seek, SeekFrom};

    let mut file = std::fs::File::open(path)?;
    let mut head = [0u8; HEADER_SIZE];
    file.read_exact(&mut head)?;
    let header = parse_header(&head)?;

    let mut table = vec![0u8; header.file_count * ENTRY_SIZE];
    file.seek(SeekFrom::Start(header.file_info_offset as u64))?;
    file.read_exact(&mut table)?;

    let mut name_block = vec![0u8; header.filename_table_size];
    file.seek(SeekFrom::Start(header.filename_table_offset as u64))?;
    file.read_exact(&mut name_block)?;
    let names = level5::decompress_data(&name_block)?;

    let mut out = Vec::with_capacity(header.file_count);
    for index in 0..header.file_count {
        let base = index * ENTRY_SIZE;
        let name_offset = u16_at(&table, base + 4) as usize;
        let size_low = u16_at(&table, base + 8) as usize;
        let size_high = table[base + 11] as usize;
        out.push((read_name(&names, name_offset), (size_high << 16) | size_low));
    }
    Ok(out)
}

/// True when the file begins with the XPCK magic.
pub fn is_archive_file(path: &Path) -> bool {
    use std::io::Read;
    let Ok(mut file) = std::fs::File::open(path) else {
        return false;
    };
    let mut magic = [0u8; 4];
    file.read_exact(&mut magic).is_ok() && &magic == MAGIC
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a minimal single-member XPCK archive with an uncompressed name table.
    fn synthetic_archive() -> Vec<u8> {
        let names = b"000.prm\0";
        let name_block: Vec<u8> = {
            let mut v = ((((names.len() as u32) << 3) | 0) as u32)
                .to_le_bytes()
                .to_vec();
            v.extend_from_slice(names);
            v
        };

        let file_info_offset = HEADER_SIZE; // 20
        let entry_table_len = ENTRY_SIZE; // 12
        let filename_table_offset = file_info_offset + entry_table_len; // 32
        // data offset must be a multiple of 4
        let data_offset = (filename_table_offset + name_block.len() + 3) & !3;
        let payload = b"XMPRpayload!!";

        let mut out = vec![0u8; data_offset + payload.len()];
        out[0..4].copy_from_slice(MAGIC);
        out[4] = 1; // file count low
        out[5] = 0x70; // variant nibble 7, count high nibble 0
        out[6..8].copy_from_slice(&((file_info_offset as u16) >> 2).to_le_bytes());
        out[8..10].copy_from_slice(&((filename_table_offset as u16) >> 2).to_le_bytes());
        out[10..12].copy_from_slice(&((data_offset as u16) >> 2).to_le_bytes());
        out[12..14].copy_from_slice(&((entry_table_len as u16) >> 2).to_le_bytes());
        out[14..16].copy_from_slice(&((name_block.len() as u16 + 3) / 4).to_le_bytes());
        out[16..20].copy_from_slice(&((payload.len() as u32 + 3) / 4).to_le_bytes());

        // entry: crc32, name_offset, off_low, size_low, off_high, size_high
        let base = file_info_offset;
        out[base..base + 4].copy_from_slice(&0xDEADBEEFu32.to_le_bytes());
        out[base + 4..base + 6].copy_from_slice(&0u16.to_le_bytes());
        out[base + 6..base + 8].copy_from_slice(&0u16.to_le_bytes());
        out[base + 8..base + 10].copy_from_slice(&(payload.len() as u16).to_le_bytes());
        out[base + 10] = 0;
        out[base + 11] = 0;

        out[filename_table_offset..filename_table_offset + name_block.len()]
            .copy_from_slice(&name_block);
        out[data_offset..data_offset + payload.len()].copy_from_slice(payload);
        out
    }

    #[test]
    fn parses_header_offsets_and_member() {
        let archive = Archive::parse(synthetic_archive()).unwrap();
        assert_eq!(archive.header.file_count, 1);
        assert_eq!(archive.header.variant_nibble, 7);
        assert_eq!(archive.entries.len(), 1);

        let entry = &archive.entries[0];
        assert_eq!(entry.name, "000.prm");
        assert_eq!(entry.extension(), "prm");
        assert_eq!(entry.stem(), "000");
        assert_eq!(entry.crc32, 0xDEAD_BEEF);
        assert!(entry.valid);

        assert_eq!(archive.member(0).unwrap(), b"XMPRpayload!!");
        assert_eq!(archive.member_by_name("000.PRM").unwrap(), b"XMPRpayload!!");
        assert_eq!(archive.entries_with_extension("prm").len(), 1);
    }

    #[test]
    fn rejects_non_xpck_data() {
        assert!(Archive::parse(vec![0u8; 64]).is_err());
    }
}
