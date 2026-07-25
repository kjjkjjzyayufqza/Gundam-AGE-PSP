//! XMPR (`.prm`) mesh decoding for Gundam AGE PSP.
//!
//! Ported from `tools/age_xmpr_tool.py`. Layout:
//!
//! ```text
//! XMPR -> XPRM -> XPVB (attribute table + vertex buffer, both Level-5)
//!               -> XPVI (primitive header; AGE PSP carries no index payload)
//! ```
//!
//! AGE PSP `XPVI` blocks declare triangle-strip primitives without an embedded
//! index buffer, so faces are generated from vertex order as a strip and
//! zero-area triangles are dropped.

use crate::level5;
use anyhow::{Result, bail};

pub const MAGIC: &[u8; 4] = b"XMPR";
const ATTRIBUTE_SLOTS: usize = 10;
const SLOT_POSITION: usize = 0;
const SLOT_UV0: usize = 4;
const SLOT_WEIGHTS: usize = 7;
const DEGENERATE_AREA_EPSILON: f32 = 1e-8;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Triangulation {
    /// Treat vertex order as a triangle strip (AGE PSP default).
    Strip,
    /// Treat vertex order as independent triangles.
    List,
    /// Emit no faces; useful for point inspection.
    Points,
}

impl Triangulation {
    pub fn label(self) -> &'static str {
        match self {
            Self::Strip => "strip",
            Self::List => "list",
            Self::Points => "points",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PositionFormat {
    Float32x3,
    Float32x4Xyz,
    /// Signed 16-bit normalized (value / 32768); the skinned bind pose.
    S16Norm,
    Unsupported,
}

impl PositionFormat {
    pub fn label(self) -> &'static str {
        match self {
            Self::Float32x3 => "float32x3",
            Self::Float32x4Xyz => "float32x4_xyz",
            Self::S16Norm => "s16_normx3",
            Self::Unsupported => "unsupported",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UvFormat {
    Float32x2,
    /// Unsigned 16-bit normalized (value / 32768).
    U16Norm,
    Absent,
    Unsupported,
}

impl UvFormat {
    pub fn label(self) -> &'static str {
        match self {
            Self::Float32x2 => "float32x2",
            Self::U16Norm => "u16_normx2",
            Self::Absent => "absent",
            Self::Unsupported => "unsupported",
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Attribute {
    pub slot: usize,
    pub count: u8,
    pub offset: u8,
    pub size: u8,
    pub kind: u8,
}

impl Attribute {
    fn is_active(&self) -> bool {
        self.count > 0 && self.size > 0
    }
}

#[derive(Clone)]
pub struct Mesh {
    /// Source member name inside the archive, e.g. `000.prm`.
    pub source: String,
    pub name: String,
    pub material: String,
    pub positions: Vec<[f32; 3]>,
    pub uvs: Vec<[f32; 2]>,
    pub normals: Vec<[f32; 3]>,
    /// Zero-based triangle indices.
    pub faces: Vec<[u32; 3]>,
    pub has_uvs: bool,
    pub stride: u16,
    pub position_format: PositionFormat,
    pub uv_format: UvFormat,
    pub attributes: Vec<Attribute>,
    pub node_hashes: Vec<String>,
    /// Raw slot-7 bone weight bytes per vertex, when present.
    pub raw_weights: Vec<[u8; 8]>,
    pub attribute_method: level5::Method,
    pub vertex_method: level5::Method,
    pub primitive_type: u16,
    pub declared_face_count: u32,
    pub dropped_degenerate_faces: usize,
    pub bounds_min: [f32; 3],
    pub bounds_max: [f32; 3],
    pub warnings: Vec<String>,
}

impl Mesh {
    pub fn vertex_count(&self) -> usize {
        self.positions.len()
    }

    pub fn face_count(&self) -> usize {
        self.faces.len()
    }

    pub fn is_skinned(&self) -> bool {
        !self.node_hashes.is_empty() && !self.raw_weights.is_empty()
    }
}

fn u16_at(data: &[u8], offset: usize) -> Result<u16> {
    data.get(offset..offset + 2)
        .map(|b| u16::from_le_bytes([b[0], b[1]]))
        .ok_or_else(|| anyhow::anyhow!("read past end of buffer at 0x{offset:X}"))
}

fn u32_at(data: &[u8], offset: usize) -> Result<u32> {
    data.get(offset..offset + 4)
        .map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
        .ok_or_else(|| anyhow::anyhow!("read past end of buffer at 0x{offset:X}"))
}

fn f32_at(data: &[u8], offset: usize) -> Result<f32> {
    Ok(f32::from_bits(u32_at(data, offset)?))
}

fn i16_at(data: &[u8], offset: usize) -> Result<i16> {
    data.get(offset..offset + 2)
        .map(|b| i16::from_le_bytes([b[0], b[1]]))
        .ok_or_else(|| anyhow::anyhow!("read past end of buffer at 0x{offset:X}"))
}

/// Read a NUL-terminated name; AGE strings are ASCII/Shift-JIS.
fn read_name(data: &[u8], offset: usize, length: usize) -> String {
    if offset == 0 || offset >= data.len() || length == 0 {
        return String::new();
    }
    let end = (offset + length).min(data.len());
    let raw = &data[offset..end];
    let raw = raw.split(|b| *b == 0).next().unwrap_or(raw);
    String::from_utf8_lossy(raw).to_string()
}

fn parse_attributes(att: &[u8]) -> Vec<Attribute> {
    (0..ATTRIBUTE_SLOTS)
        .filter_map(|slot| {
            let base = slot * 4;
            let b = att.get(base..base + 4)?;
            Some(Attribute {
                slot,
                count: b[0],
                offset: b[1],
                size: b[2],
                kind: b[3],
            })
        })
        .collect()
}

fn attribute(attributes: &[Attribute], slot: usize) -> Option<&Attribute> {
    attributes.iter().find(|a| a.slot == slot)
}

/// Triangle strip indices with alternating winding, zero-based.
fn strip_faces(vertex_count: usize) -> Vec<[u32; 3]> {
    if vertex_count < 3 {
        return Vec::new();
    }
    let mut faces = Vec::with_capacity(vertex_count - 2);
    let mut flip = false;
    for i in 0..vertex_count - 2 {
        let i = i as u32;
        faces.push(if flip {
            [i + 1, i, i + 2]
        } else {
            [i, i + 1, i + 2]
        });
        flip = !flip;
    }
    faces
}

fn list_faces(vertex_count: usize) -> Vec<[u32; 3]> {
    (0..vertex_count.saturating_sub(2))
        .step_by(3)
        .map(|i| [i as u32, i as u32 + 1, i as u32 + 2])
        .collect()
}

fn triangle_area(a: [f32; 3], b: [f32; 3], c: [f32; 3]) -> f32 {
    let u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    let v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    let cross = [
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    ];
    (cross[0] * cross[0] + cross[1] * cross[1] + cross[2] * cross[2]).sqrt() * 0.5
}

/// Smooth per-vertex normals accumulated from face normals.
fn compute_normals(positions: &[[f32; 3]], faces: &[[u32; 3]]) -> Vec<[f32; 3]> {
    let mut normals = vec![[0.0f32; 3]; positions.len()];
    for face in faces {
        let [ia, ib, ic] = [face[0] as usize, face[1] as usize, face[2] as usize];
        let (Some(a), Some(b), Some(c)) =
            (positions.get(ia), positions.get(ib), positions.get(ic))
        else {
            continue;
        };
        let u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
        let v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
        let n = [
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        ];
        for index in [ia, ib, ic] {
            normals[index][0] += n[0];
            normals[index][1] += n[1];
            normals[index][2] += n[2];
        }
    }
    for n in &mut normals {
        let len = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]).sqrt();
        if len > f32::EPSILON {
            n[0] /= len;
            n[1] /= len;
            n[2] /= len;
        } else {
            *n = [0.0, 1.0, 0.0];
        }
    }
    normals
}

struct VertexData {
    positions: Vec<[f32; 3]>,
    uvs: Vec<[f32; 2]>,
    raw_weights: Vec<[u8; 8]>,
    stride: u16,
    position_format: PositionFormat,
    uv_format: UvFormat,
    attributes: Vec<Attribute>,
    attribute_method: level5::Method,
    vertex_method: level5::Method,
    warnings: Vec<String>,
}

fn decode_xpvb(data: &[u8], xprm_offset: usize) -> Result<VertexData> {
    let rel = u32_at(data, xprm_offset + 0x04)? as usize;
    let len = u32_at(data, xprm_offset + 0x08)? as usize;
    let start = xprm_offset + rel;
    let end = (start + len).min(data.len());
    let xpvb = data
        .get(start..end)
        .ok_or_else(|| anyhow::anyhow!("XPVB block out of range at 0x{start:X}"))?;
    if xpvb.len() < 0x10 || &xpvb[0..4] != b"XPVB" {
        bail!("XPVB block missing at 0x{start:X}");
    }

    let att_off = u16_at(xpvb, 0x04)? as usize;
    let unknown_off = u16_at(xpvb, 0x06)? as usize;
    let vertex_off = u16_at(xpvb, 0x08)? as usize;
    let stride = u16_at(xpvb, 0x0A)?;
    let vertex_count = u32_at(xpvb, 0x0C)? as usize;

    if att_off > unknown_off || unknown_off > xpvb.len() || vertex_off > xpvb.len() {
        bail!("XPVB block offsets are inconsistent");
    }

    let (attribute_method, att) = level5::decompress(&xpvb[att_off..unknown_off])
        .map_err(|e| anyhow::anyhow!("XPVB attribute table: {e}"))?;
    let (vertex_method, vtx) = level5::decompress(&xpvb[vertex_off..])
        .map_err(|e| anyhow::anyhow!("XPVB vertex buffer: {e}"))?;

    let attributes = parse_attributes(&att);
    let mut warnings = Vec::new();

    let pos_attr = *attribute(&attributes, SLOT_POSITION)
        .ok_or_else(|| anyhow::anyhow!("XPVB has no position attribute in slot 0"))?;
    let uv_attr = attribute(&attributes, SLOT_UV0).copied();
    let weight_attr = attribute(&attributes, SLOT_WEIGHTS).copied();

    let stride_usize = stride as usize;
    let position_format = match (pos_attr.size, pos_attr.kind) {
        (12, 2) if pos_attr.offset as usize + 12 <= stride_usize => PositionFormat::Float32x3,
        (16, 2) if pos_attr.offset as usize + 16 <= stride_usize => PositionFormat::Float32x4Xyz,
        (6, 2) if pos_attr.offset as usize + 6 <= stride_usize => PositionFormat::S16Norm,
        _ => PositionFormat::Unsupported,
    };

    let uv_format = match uv_attr {
        Some(a) if a.is_active() => match (a.size, a.kind) {
            (8, 2) if a.offset as usize + 8 <= stride_usize => UvFormat::Float32x2,
            (4, 2) if a.offset as usize + 4 <= stride_usize => UvFormat::U16Norm,
            _ => UvFormat::Unsupported,
        },
        _ => UvFormat::Absent,
    };

    if position_format == PositionFormat::Unsupported {
        warnings.push(format!(
            "position slot 0 has an unsupported layout (count={}, offset={}, size={}, type={}); \
             no geometry was decoded",
            pos_attr.count, pos_attr.offset, pos_attr.size, pos_attr.kind
        ));
    }
    if uv_format == UvFormat::Unsupported {
        warnings.push("UV slot 4 has an unsupported layout; UVs were skipped".to_string());
    }
    if vtx.len() != stride_usize * vertex_count {
        warnings.push(format!(
            "decoded vertex buffer is {} bytes but stride*count is {}",
            vtx.len(),
            stride_usize * vertex_count
        ));
    }

    let mut positions = Vec::new();
    let mut uvs = Vec::new();
    let mut raw_weights = Vec::new();

    if position_format != PositionFormat::Unsupported {
        positions.reserve(vertex_count);
        for index in 0..vertex_count {
            let row = index * stride_usize;
            if row + stride_usize > vtx.len() {
                warnings.push(format!(
                    "stopped at vertex {index}; row exceeds the decoded vertex buffer"
                ));
                break;
            }
            let pos_at = row + pos_attr.offset as usize;
            let position = match position_format {
                PositionFormat::Float32x3 | PositionFormat::Float32x4Xyz => [
                    f32_at(&vtx, pos_at)?,
                    f32_at(&vtx, pos_at + 4)?,
                    f32_at(&vtx, pos_at + 8)?,
                ],
                PositionFormat::S16Norm => [
                    i16_at(&vtx, pos_at)? as f32 / 32768.0,
                    i16_at(&vtx, pos_at + 2)? as f32 / 32768.0,
                    i16_at(&vtx, pos_at + 4)? as f32 / 32768.0,
                ],
                PositionFormat::Unsupported => unreachable!(),
            };
            positions.push(position);

            if let Some(a) = uv_attr {
                let uv_at = row + a.offset as usize;
                // UVs are stored in image space (origin top-left), which is
                // already what glTF TEXCOORD_0 and wgpu texture sampling both
                // expect, so they are used unchanged. The Python OBJ exporter
                // in `tools/` flips V because OBJ measures V from the bottom;
                // reproducing that flip here would render every model upside
                // down in the preview and in exported glTF.
                match uv_format {
                    UvFormat::Float32x2 => {
                        uvs.push([f32_at(&vtx, uv_at)?, f32_at(&vtx, uv_at + 4)?]);
                    }
                    UvFormat::U16Norm => {
                        let u = u16_at(&vtx, uv_at)? as f32 / 32768.0;
                        let v = u16_at(&vtx, uv_at + 2)? as f32 / 32768.0;
                        uvs.push([u, v]);
                    }
                    _ => {}
                }
            }

            if let Some(a) = weight_attr {
                if a.is_active() && a.size == 8 {
                    let at = row + a.offset as usize;
                    if let Some(bytes) = vtx.get(at..at + 8) {
                        let mut w = [0u8; 8];
                        w.copy_from_slice(bytes);
                        raw_weights.push(w);
                    }
                }
            }
        }
    }

    Ok(VertexData {
        positions,
        uvs,
        raw_weights,
        stride,
        position_format,
        uv_format,
        attributes,
        attribute_method,
        vertex_method,
        warnings,
    })
}

fn decode_xpvi(data: &[u8], xprm_offset: usize) -> Result<(u16, u32)> {
    let rel = u32_at(data, xprm_offset + 0x0C)? as usize;
    let len = u32_at(data, xprm_offset + 0x10)? as usize;
    let start = xprm_offset + rel;
    let end = (start + len).min(data.len());
    let Some(xpvi) = data.get(start..end) else {
        return Ok((0, 0));
    };
    if xpvi.len() < 0x0C || &xpvi[0..4] != b"XPVI" {
        return Ok((0, 0));
    }
    Ok((u16_at(xpvi, 0x04)?, u32_at(xpvi, 0x08)?))
}

/// Decode one `.prm` payload.
pub fn decode(source: &str, data: &[u8], triangulation: Triangulation) -> Result<Mesh> {
    if data.len() < 0x54 || &data[0..4] != MAGIC {
        bail!("not an XMPR mesh (magic {:02X?})", &data[0..4.min(data.len())]);
    }

    let xprm_offset = u32_at(data, 0x04)? as usize;
    if xprm_offset == 0
        || xprm_offset + 0x14 > data.len()
        || &data[xprm_offset..xprm_offset + 4] != b"XPRM"
    {
        bail!("XPRM header not found at declared offset 0x{xprm_offset:X}");
    }

    let vertex_data = decode_xpvb(data, xprm_offset)?;
    let (primitive_type, declared_face_count) = decode_xpvi(data, xprm_offset)?;

    // Node hash table drives skin joint slots.
    let nodes_offset = u32_at(data, 0x28)? as usize;
    let nodes_length = u32_at(data, 0x2C)? as usize;
    let mut node_hashes = Vec::new();
    if nodes_offset != 0
        && nodes_length != 0
        && nodes_offset + nodes_length <= data.len()
        && nodes_length % 4 == 0
    {
        for i in 0..nodes_length / 4 {
            node_hashes.push(format!("{:08X}", u32_at(data, nodes_offset + i * 4)?));
        }
    }

    let name = read_name(
        data,
        u32_at(data, 0x30)? as usize,
        u32_at(data, 0x34)? as usize,
    );
    let material = read_name(
        data,
        u32_at(data, 0x38)? as usize,
        u32_at(data, 0x3C)? as usize,
    );

    let mut warnings = vertex_data.warnings;
    if primitive_type == 2 {
        warnings.push(
            "XPVI declares a triangle strip with no index payload; faces are inferred from \
             vertex order"
                .to_string(),
        );
    }

    let inferred = match triangulation {
        Triangulation::Strip => strip_faces(vertex_data.positions.len()),
        Triangulation::List => list_faces(vertex_data.positions.len()),
        Triangulation::Points => Vec::new(),
    };
    let faces: Vec<[u32; 3]> = inferred
        .iter()
        .copied()
        .filter(|f| {
            let (Some(a), Some(b), Some(c)) = (
                vertex_data.positions.get(f[0] as usize),
                vertex_data.positions.get(f[1] as usize),
                vertex_data.positions.get(f[2] as usize),
            ) else {
                return false;
            };
            triangle_area(*a, *b, *c) > DEGENERATE_AREA_EPSILON
        })
        .collect();
    let dropped = inferred.len() - faces.len();

    let mut bounds_min = [f32::INFINITY; 3];
    let mut bounds_max = [f32::NEG_INFINITY; 3];
    for p in &vertex_data.positions {
        for axis in 0..3 {
            bounds_min[axis] = bounds_min[axis].min(p[axis]);
            bounds_max[axis] = bounds_max[axis].max(p[axis]);
        }
    }
    if vertex_data.positions.is_empty() {
        bounds_min = [0.0; 3];
        bounds_max = [0.0; 3];
    }

    let normals = compute_normals(&vertex_data.positions, &faces);
    let has_uvs = vertex_data.uvs.len() == vertex_data.positions.len()
        && !vertex_data.positions.is_empty();

    Ok(Mesh {
        source: source.to_string(),
        name,
        material,
        positions: vertex_data.positions,
        uvs: vertex_data.uvs,
        normals,
        faces,
        has_uvs,
        stride: vertex_data.stride,
        position_format: vertex_data.position_format,
        uv_format: vertex_data.uv_format,
        attributes: vertex_data.attributes,
        node_hashes,
        raw_weights: vertex_data.raw_weights,
        attribute_method: vertex_data.attribute_method,
        vertex_method: vertex_data.vertex_method,
        primitive_type,
        declared_face_count,
        dropped_degenerate_faces: dropped,
        bounds_min,
        bounds_max,
        warnings,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strip_faces_alternate_winding_zero_based() {
        assert_eq!(
            strip_faces(5),
            vec![[0, 1, 2], [2, 1, 3], [2, 3, 4]]
        );
    }

    #[test]
    fn strip_faces_needs_three_vertices() {
        assert!(strip_faces(2).is_empty());
    }

    #[test]
    fn list_faces_groups_in_threes() {
        assert_eq!(list_faces(7), vec![[0, 1, 2], [3, 4, 5]]);
    }

    #[test]
    fn degenerate_triangle_has_zero_area() {
        let a = [0.0, 0.0, 0.0];
        assert_eq!(triangle_area(a, a, a), 0.0);
        assert!(triangle_area(a, [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]) > 0.0);
    }

    #[test]
    fn normals_point_away_from_flat_triangle() {
        let positions = vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]];
        let normals = compute_normals(&positions, &[[0, 1, 2]]);
        // Cross((1,0,0),(0,0,1)) = (0,-1,0)
        for n in normals {
            assert!((n[1] + 1.0).abs() < 1e-5, "unexpected normal {n:?}");
        }
    }

    #[test]
    fn attribute_table_reads_ten_slots() {
        let att = [0u8; 40];
        assert_eq!(parse_attributes(&att).len(), 10);
    }

    #[test]
    fn rejects_non_xmpr_payload() {
        assert!(decode("x.prm", &[0u8; 0x60], Triangulation::Strip).is_err());
    }
}
