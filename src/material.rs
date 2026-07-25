//! Material and texture binding for Gundam AGE PSP archives.
//!
//! Ported from `tools/age_material_bind.py`. Evidence chain:
//!
//! 1. `RES.bin` is Level-5 compressed and decompresses to a `CHRP00` payload.
//! 2. ASCII strings are scanned out of that payload and hashed with CRC32.
//! 3. Each `NNN.txp` begins with two CRC32 words: the owning material name and
//!    that material's `_texproj0` string.
//! 4. The `.txp` stem selects the same-numbered `.xi` texture.
//!
//! A resource-order heuristic covers archives where step 3 finds no owner.

use crate::xpck::Archive;
use std::collections::HashMap;

/// Resource keys seen in `CHRP00` payloads that are not material names.
const KNOWN_RESOURCE_KEYS: &[&str] = &[
    "bb_ref_bone",
    "bb_size_x",
    "bb_size_y",
    "bb_size_z",
    "flw_cmr_type",
    "mesh_sort",
    "scale_base_one",
];

const MIN_STRING_LENGTH: usize = 4;

/// Standard CRC32 (IEEE, reflected) as used by the Level-5 string hashes.
pub fn crc32(bytes: &[u8]) -> u32 {
    let mut crc = 0xFFFF_FFFFu32;
    for &byte in bytes {
        crc ^= byte as u32;
        for _ in 0..8 {
            let mask = (crc & 1).wrapping_neg();
            crc = (crc >> 1) ^ (0xEDB8_8320 & mask);
        }
    }
    !crc
}

/// True when a `CHRP00` string looks like a material name.
fn is_material_string(value: &str) -> bool {
    if value.is_empty() || value.contains("_texproj") {
        return false;
    }
    if KNOWN_RESOURCE_KEYS.contains(&value) || value.starts_with("out_") {
        return false;
    }
    value.starts_with("DefaultLib.") || (value.contains('.') && value.ends_with('-'))
}

fn is_texture_projection_string(value: &str) -> bool {
    value.contains("_texproj")
}

/// Printable-ASCII runs of at least `MIN_STRING_LENGTH` bytes.
fn ascii_strings(data: &[u8]) -> Vec<String> {
    let mut out = Vec::new();
    let mut current = Vec::new();
    for &byte in data {
        if (0x20..=0x7E).contains(&byte) {
            current.push(byte);
        } else {
            if current.len() >= MIN_STRING_LENGTH {
                out.push(String::from_utf8_lossy(&current).to_string());
            }
            current.clear();
        }
    }
    if current.len() >= MIN_STRING_LENGTH {
        out.push(String::from_utf8_lossy(&current).to_string());
    }
    out
}

/// Strip the `DefaultLib.` prefix and trailing dashes/variant suffix.
fn material_base(material: &str) -> String {
    let trimmed = material
        .strip_prefix("DefaultLib.")
        .unwrap_or(material)
        .trim_end_matches('-');
    trimmed.split('-').next().unwrap_or(trimmed).to_string()
}

#[derive(Clone, Debug)]
pub struct TxpRecord {
    pub stem: String,
    pub hash_words: [u32; 2],
    pub owner_material: Option<String>,
    pub texture_projection: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BindConfidence {
    /// `.txp` CRC32 owner plus a matching same-stem `.xi`.
    TxpStemMatch,
    /// Texture chosen by resource-string order.
    ResourceOrder,
    Unresolved,
}

impl BindConfidence {
    pub fn label(self) -> &'static str {
        match self {
            Self::TxpStemMatch => "txp_stem_xi_match",
            Self::ResourceOrder => "resource_order_heuristic",
            Self::Unresolved => "unresolved",
        }
    }
}

#[derive(Clone, Debug)]
pub struct MaterialRecord {
    pub material_name: String,
    pub base: String,
    /// `.xi` member name, e.g. `002.xi`.
    pub texture_member: Option<String>,
    pub txp_stem: Option<String>,
    pub confidence: BindConfidence,
}

#[derive(Clone, Debug, Default)]
pub struct Bindings {
    pub res_member: Option<String>,
    pub res_method: Option<String>,
    pub strings: Vec<String>,
    pub material_strings: Vec<String>,
    pub texture_name_candidates: Vec<String>,
    pub txp_records: Vec<TxpRecord>,
    pub materials: Vec<MaterialRecord>,
    /// Material name -> `.xi` member name.
    by_material: HashMap<String, String>,
}

impl Bindings {
    /// Resolve the texture member bound to a material name.
    pub fn texture_for_material(&self, material: &str) -> Option<&str> {
        self.by_material.get(material).map(|s| s.as_str())
    }

    pub fn confidence_for_material(&self, material: &str) -> BindConfidence {
        self.materials
            .iter()
            .find(|m| m.material_name == material)
            .map(|m| m.confidence)
            .unwrap_or(BindConfidence::Unresolved)
    }

    pub fn resolved_count(&self) -> usize {
        self.materials
            .iter()
            .filter(|m| m.texture_member.is_some())
            .count()
    }
}

fn u32_at(data: &[u8], offset: usize) -> Option<u32> {
    data.get(offset..offset + 4)
        .map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
}

/// Decompress `RES.bin` (or an already-decoded `RES.dec.bin`) from an archive.
fn read_res_payload(archive: &Archive) -> (Option<String>, Vec<u8>, Option<String>) {
    for name in ["RES.dec.bin", "RES.bin"] {
        let Some(data) = archive.member_by_name(name) else {
            continue;
        };
        if data.len() >= 4 && &data[0..4] == b"CHRP" {
            return (
                Some(name.to_string()),
                data.to_vec(),
                Some("already_decompressed".to_string()),
            );
        }
        if let Ok((method, payload)) = crate::level5::decompress(data) {
            return (
                Some(name.to_string()),
                payload,
                Some(method.name().to_string()),
            );
        }
    }
    (None, Vec::new(), None)
}

/// Build the material/texture binding table for one archive.
pub fn build(archive: &Archive) -> Bindings {
    let (res_member, res_payload, res_method) = read_res_payload(archive);
    let strings = ascii_strings(&res_payload);

    let mut string_by_crc: HashMap<u32, String> = HashMap::new();
    for value in &strings {
        string_by_crc
            .entry(crc32(value.as_bytes()))
            .or_insert_with(|| value.clone());
    }

    let material_strings: Vec<String> = strings
        .iter()
        .filter(|s| is_material_string(s))
        .cloned()
        .collect();

    // Texture-name candidates mirror the Python classifier's exclusions.
    let texture_name_candidates: Vec<String> = strings
        .iter()
        .filter(|s| {
            s.contains('_')
                && !is_material_string(s)
                && !is_texture_projection_string(s)
                && !s.contains("_output.")
                && !KNOWN_RESOURCE_KEYS.contains(&s.as_str())
                && !s.starts_with("out_")
                && !s.starts_with("c_")
                && !s.starts_with("l_")
                && !s.starts_with("r_")
        })
        .cloned()
        .collect();

    // Available texture members, sorted by name so numbered stems line up.
    let xi_members: Vec<String> = archive
        .entries_with_extension("xi")
        .iter()
        .map(|e| e.name.clone())
        .collect();
    let xi_by_stem: HashMap<String, String> = archive
        .entries_with_extension("xi")
        .iter()
        .map(|e| (e.stem(), e.name.clone()))
        .collect();

    // Step 3: read the CRC32 owner words out of each .txp.
    let mut txp_records = Vec::new();
    for entry in archive.entries_with_extension("txp") {
        let Some(data) = archive.member(entry.index) else {
            continue;
        };
        let (Some(w0), Some(w1)) = (u32_at(data, 0), u32_at(data, 4)) else {
            continue;
        };
        let resolved: Vec<Option<&String>> = vec![string_by_crc.get(&w0), string_by_crc.get(&w1)];
        let owner_material = resolved
            .iter()
            .flatten()
            .find(|s| is_material_string(s))
            .map(|s| (*s).clone());
        let texture_projection = resolved
            .iter()
            .flatten()
            .find(|s| is_texture_projection_string(s))
            .map(|s| (*s).clone());
        txp_records.push(TxpRecord {
            stem: entry.stem(),
            hash_words: [w0, w1],
            owner_material,
            texture_projection,
        });
    }

    // Ordered material list: CHRP00 strings first, then any extra .txp owners.
    let mut materials_ordered: Vec<String> = material_strings.clone();
    for record in &txp_records {
        if let Some(owner) = &record.owner_material {
            if !materials_ordered.contains(owner) {
                materials_ordered.push(owner.clone());
            }
        }
    }

    let txp_by_material: HashMap<&str, &TxpRecord> = txp_records
        .iter()
        .filter_map(|r| r.owner_material.as_deref().map(|m| (m, r)))
        .collect();

    let mut materials = Vec::new();
    let mut by_material = HashMap::new();

    for (order_index, material_name) in materials_ordered.iter().enumerate() {
        let txp = txp_by_material.get(material_name.as_str());
        let txp_stem = txp.map(|r| r.stem.clone());

        // Preferred: same-numbered .xi as the owning .txp.
        let mut texture_member = txp_stem.as_ref().and_then(|s| xi_by_stem.get(s).cloned());
        let mut confidence = if texture_member.is_some() {
            BindConfidence::TxpStemMatch
        } else {
            BindConfidence::Unresolved
        };

        // Fallback: position of the material within the resource string order.
        if texture_member.is_none() {
            if let Some(name) = xi_members.get(order_index) {
                texture_member = Some(name.clone());
                confidence = BindConfidence::ResourceOrder;
            }
        }

        if let Some(member) = &texture_member {
            by_material.insert(material_name.clone(), member.clone());
        }

        materials.push(MaterialRecord {
            material_name: material_name.clone(),
            base: material_base(material_name),
            texture_member,
            txp_stem,
            confidence,
        });
    }

    Bindings {
        res_member,
        res_method,
        strings,
        material_strings,
        texture_name_candidates,
        txp_records,
        materials,
        by_material,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crc32_matches_known_values() {
        assert_eq!(crc32(b""), 0);
        assert_eq!(crc32(b"123456789"), 0xCBF4_3926);
    }

    #[test]
    fn material_strings_are_recognised() {
        assert!(is_material_string("DefaultLib.ms001100_01"));
        assert!(is_material_string("e1101.e1101g01-"));
        assert!(!is_material_string("DefaultLib.ms001100_01_texproj0"));
        assert!(!is_material_string("mesh_sort"));
        assert!(!is_material_string("out_something"));
        assert!(!is_material_string("plain_texture_name"));
    }

    #[test]
    fn material_base_strips_prefix_and_variant() {
        assert_eq!(material_base("DefaultLib.ms001100_01"), "ms001100_01");
        assert_eq!(material_base("e1101.e1101e02-a-add-"), "e1101.e1101e02");
    }

    #[test]
    fn ascii_scan_keeps_only_long_runs() {
        let data = b"ab\0DefaultLib.test\0xy";
        let found = ascii_strings(data);
        assert_eq!(found, vec!["DefaultLib.test".to_string()]);
    }

    #[test]
    fn texproj_strings_are_detected() {
        assert!(is_texture_projection_string("DefaultLib.x_texproj0"));
        assert!(!is_texture_projection_string("DefaultLib.x"));
    }
}
