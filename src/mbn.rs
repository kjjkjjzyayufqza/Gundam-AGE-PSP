//! MBN skeleton / bind-pose loader for Gundam AGE PSP.
//!
//! Full 168-byte MBN layout matches StudioEleven `MBNSupport.MBNData` and
//! `studio_eleven/formats/mbn.py`:
//!
//! ```text
//! 0x00  u32 name hash
//! 0x04  u32 parent hash
//! 0x08  u32 flags (usually 4)
//! 0x0C  vec3 location (local)
//! 0x18  mat3 rotation (9 floats)
//! 0x3C  vec3 scale
//! 0x48  mat3 local rotation
//! 0x6C  vec3 location×head helper
//! 0x78  vec3 first column of local rotation
//! 0x84  vec3 (tail - head)
//! 0x90  vec3 last column of local rotation
//! 0x9C  vec3 head  (absolute bind-pose joint position, recorded in file)
//! ```
//!
//! Bind matrices are built from local SRT only. On AGE PSP character packages the
//! hierarchical global translation matches the recorded `head` when the file
//! rotation matrix is converted **without** StudioEleven's Blender-side
//! quaternion invert (verified on `ms001000_p000`: mean |head−gT| ≈ 0 with no
//! invert, ~0.15 / max ~3 with invert).
//!
//! XPVB skinned positions (`s16_norm`) stay in their compact unit-ish bind-pose
//! space. There is **no** free-floating mesh↔skeleton scale field in the files;
//! do not invent AABB fits. Static export keeps both spaces as recorded
//! (StudioEleven / `age_gltf_tool.py` do the same).

use std::collections::HashMap;

/// Row-major 4×4 affine matrix (translation in elements 3, 7, 11).
pub type Mat4 = [f32; 16];

pub const IDENTITY: Mat4 = [
    1.0, 0.0, 0.0, 0.0, //
    0.0, 1.0, 0.0, 0.0, //
    0.0, 0.0, 1.0, 0.0, //
    0.0, 0.0, 0.0, 1.0,
];

/// Minimum MBN size used by older research tools (SRT only).
const MBN_MIN_SRT: usize = 0x48;
/// Full StudioEleven MBN size (includes head/tail).
const MBN_FULL_SIZE: usize = 168;

/// One bone loaded from a `.mbn` member.
#[derive(Clone, Debug)]
pub struct Bone {
    /// 8-digit uppercase hex of the bone id (matches XMPR node_hashes).
    pub hash: String,
    /// Parent bone hash, when non-zero in the file.
    pub parent: Option<String>,
    /// Local bind transform from location/rotation/scale (row-major).
    pub local_matrix: Mat4,
    /// Absolute head position recorded at 0x9C (skeleton units).
    pub head: [f32; 3],
    /// Absolute tail position = head + (tail-head) from file.
    pub tail: [f32; 3],
    pub flags: u32,
}

/// Skeleton assembled from every `.mbn` in an archive.
#[derive(Clone, Debug, Default)]
pub struct Skeleton {
    pub bones: HashMap<String, Bone>,
    /// Global bind matrices, filled by [`Skeleton::rebuild_globals`].
    pub global: HashMap<String, Mat4>,
}

impl Skeleton {
    pub fn is_empty(&self) -> bool {
        self.bones.is_empty()
    }

    pub fn bone_count(&self) -> usize {
        self.bones.len()
    }

    /// Parse every `.mbn` payload. Later files with the same bone id are ignored
    /// (first wins), matching the Python multi-root merge.
    pub fn from_mbn_members<'a>(
        members: impl IntoIterator<Item = (&'a str, &'a [u8])>,
    ) -> Self {
        let mut bones = HashMap::new();
        let mut ordered: Vec<(String, Vec<u8>)> = members
            .into_iter()
            .map(|(name, data)| (name.to_string(), data.to_vec()))
            .collect();
        ordered.sort_by(|a, b| a.0.cmp(&b.0));

        for (_name, data) in ordered {
            if let Some(bone) = parse_mbn(&data) {
                bones.entry(bone.hash.clone()).or_insert(bone);
            }
        }

        let mut skeleton = Self {
            bones,
            global: HashMap::new(),
        };
        skeleton.rebuild_globals();
        skeleton
    }

    pub fn rebuild_globals(&mut self) {
        self.global.clear();
        let names: Vec<String> = self.bones.keys().cloned().collect();
        for name in names {
            let _ = self.global_matrix(&name);
        }
    }

    fn global_matrix(&mut self, name: &str) -> Mat4 {
        if let Some(m) = self.global.get(name) {
            return *m;
        }
        // Detect cycles with a temporary placeholder.
        self.global.insert(name.to_string(), IDENTITY);

        let Some(bone) = self.bones.get(name).cloned() else {
            return IDENTITY;
        };

        let result = if let Some(parent) = bone.parent.as_deref() {
            if self.bones.contains_key(parent) {
                let parent_global = self.global_matrix(parent);
                mat4_mul(parent_global, bone.local_matrix)
            } else {
                bone.local_matrix
            }
        } else {
            bone.local_matrix
        };

        self.global.insert(name.to_string(), result);
        result
    }

    /// Inverse bind matrix for a node hash (identity when the bone is missing).
    pub fn inverse_bind_matrix(&self, hash: &str) -> Mat4 {
        let key = hash.to_ascii_uppercase();
        let global = self.global.get(&key).copied().unwrap_or(IDENTITY);
        affine_inverse(global).unwrap_or(IDENTITY)
    }

    /// Local bind matrix for a node hash (identity when missing).
    pub fn local_matrix(&self, hash: &str) -> Mat4 {
        let key = hash.to_ascii_uppercase();
        self.bones
            .get(&key)
            .map(|b| b.local_matrix)
            .unwrap_or(IDENTITY)
    }

    pub fn parent_of(&self, hash: &str) -> Option<&str> {
        let key = hash.to_ascii_uppercase();
        self.bones
            .get(&key)
            .and_then(|b| b.parent.as_deref())
            .filter(|p| self.bones.contains_key(*p))
    }

    /// Absolute bind translation for a bone: recorded `head` when present, else
    /// hierarchical global translation.
    pub fn bind_translation(&self, hash: &str) -> Option<[f32; 3]> {
        let key = hash.to_ascii_uppercase();
        if let Some(bone) = self.bones.get(&key) {
            if bone.head[0].abs() + bone.head[1].abs() + bone.head[2].abs() > 1e-8 {
                return Some(bone.head);
            }
        }
        self.global.get(&key).map(|g| [g[3], g[7], g[11]])
    }
}

/// Parse one `.mbn` file body.
pub fn parse_mbn(data: &[u8]) -> Option<Bone> {
    if data.len() < MBN_MIN_SRT {
        return None;
    }
    let bone_id = u32::from_le_bytes(data[0..4].try_into().ok()?);
    let parent_id = u32::from_le_bytes(data[4..8].try_into().ok()?);
    let flags = if data.len() >= 12 {
        u32::from_le_bytes(data[8..12].try_into().ok()?)
    } else {
        0
    };
    let hash = format!("{bone_id:08X}");
    let parent = if parent_id == 0 {
        None
    } else {
        Some(format!("{parent_id:08X}"))
    };

    let location = [
        f32_at(data, 0x0C)?,
        f32_at(data, 0x10)?,
        f32_at(data, 0x14)?,
    ];
    // File stores 9 floats; age_pose_export reorders columns for quat conversion.
    let f = [
        f32_at(data, 0x18)?,
        f32_at(data, 0x1C)?,
        f32_at(data, 0x20)?,
        f32_at(data, 0x24)?,
        f32_at(data, 0x28)?,
        f32_at(data, 0x2C)?,
        f32_at(data, 0x30)?,
        f32_at(data, 0x34)?,
        f32_at(data, 0x38)?,
    ];
    // File stores 9 floats in the same column-reordered layout as age_pose_export.
    // Do NOT invert the quaternion: inverted quats make hierarchical translations
    // diverge from the recorded absolute head (file ground truth at 0x9C).
    let rotation_matrix3 = [f[0], f[3], f[6], f[1], f[4], f[7], f[2], f[5], f[8]];
    let rotation = matrix3_to_quaternion(rotation_matrix3);
    let scale = [
        f32_at(data, 0x3C)?,
        f32_at(data, 0x40)?,
        f32_at(data, 0x44)?,
    ];
    let local_matrix = srt_matrix(location, rotation, scale);

    let (head, tail) = if data.len() >= MBN_FULL_SIZE {
        let head = [
            f32_at(data, 0x9C)?,
            f32_at(data, 0xA0)?,
            f32_at(data, 0xA4)?,
        ];
        let tail_sub = [
            f32_at(data, 0x84)?,
            f32_at(data, 0x88)?,
            f32_at(data, 0x8C)?,
        ];
        let tail = [
            head[0] + tail_sub[0],
            head[1] + tail_sub[1],
            head[2] + tail_sub[2],
        ];
        (head, tail)
    } else {
        // Fallback: use local translation as head when the short form is present.
        (location, location)
    };

    Some(Bone {
        hash,
        parent,
        local_matrix,
        head,
        tail,
        flags,
    })
}

fn f32_at(data: &[u8], offset: usize) -> Option<f32> {
    let bytes: [u8; 4] = data.get(offset..offset + 4)?.try_into().ok()?;
    Some(f32::from_le_bytes(bytes))
}

pub fn mat4_mul(a: Mat4, b: Mat4) -> Mat4 {
    let mut out = [0.0f32; 16];
    for row in 0..4 {
        for col in 0..4 {
            let mut sum = 0.0;
            for k in 0..4 {
                sum += a[row * 4 + k] * b[k * 4 + col];
            }
            out[row * 4 + col] = sum;
        }
    }
    out
}

/// Affine inverse; `None` when the upper-left 3×3 is singular.
pub fn affine_inverse(matrix: Mat4) -> Option<Mat4> {
    let a = matrix[0];
    let b = matrix[1];
    let c = matrix[2];
    let d = matrix[4];
    let e = matrix[5];
    let f = matrix[6];
    let g = matrix[8];
    let h = matrix[9];
    let i = matrix[10];
    let det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
    if det.abs() <= 1e-12 {
        return None;
    }
    let inv_det = 1.0 / det;
    let inverse3 = [
        (e * i - f * h) * inv_det,
        (c * h - b * i) * inv_det,
        (b * f - c * e) * inv_det,
        (f * g - d * i) * inv_det,
        (a * i - c * g) * inv_det,
        (c * d - a * f) * inv_det,
        (d * h - e * g) * inv_det,
        (b * g - a * h) * inv_det,
        (a * e - b * d) * inv_det,
    ];
    let tx = matrix[3];
    let ty = matrix[7];
    let tz = matrix[11];
    let inv_t = [
        -(inverse3[0] * tx + inverse3[1] * ty + inverse3[2] * tz),
        -(inverse3[3] * tx + inverse3[4] * ty + inverse3[5] * tz),
        -(inverse3[6] * tx + inverse3[7] * ty + inverse3[8] * tz),
    ];
    Some([
        inverse3[0],
        inverse3[1],
        inverse3[2],
        inv_t[0],
        inverse3[3],
        inverse3[4],
        inverse3[5],
        inv_t[1],
        inverse3[6],
        inverse3[7],
        inverse3[8],
        inv_t[2],
        0.0,
        0.0,
        0.0,
        1.0,
    ])
}

/// Convert row-major Mat4 to glTF column-major 16 floats.
pub fn gltf_column_major(matrix: Mat4) -> [f32; 16] {
    [
        matrix[0], matrix[4], matrix[8], matrix[12], //
        matrix[1], matrix[5], matrix[9], matrix[13], //
        matrix[2], matrix[6], matrix[10], matrix[14], //
        matrix[3], matrix[7], matrix[11], matrix[15],
    ]
}

fn matrix3_to_quaternion(m: [f32; 9]) -> [f32; 4] {
    let (m00, m01, m02, m10, m11, m12, m20, m21, m22) =
        (m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8]);
    let trace = m00 + m11 + m22;
    if trace > 0.0 {
        let scale = (trace + 1.0).sqrt() * 2.0;
        return [
            (m21 - m12) / scale,
            (m02 - m20) / scale,
            (m10 - m01) / scale,
            0.25 * scale,
        ];
    }
    if m00 > m11 && m00 > m22 {
        let scale = (1.0 + m00 - m11 - m22).sqrt() * 2.0;
        return [
            0.25 * scale,
            (m01 + m10) / scale,
            (m02 + m20) / scale,
            (m21 - m12) / scale,
        ];
    }
    if m11 > m22 {
        let scale = (1.0 + m11 - m00 - m22).sqrt() * 2.0;
        return [
            (m01 + m10) / scale,
            0.25 * scale,
            (m12 + m21) / scale,
            (m02 - m20) / scale,
        ];
    }
    let scale = (1.0 + m22 - m00 - m11).sqrt() * 2.0;
    [
        (m02 + m20) / scale,
        (m12 + m21) / scale,
        0.25 * scale,
        (m10 - m01) / scale,
    ]
}

fn quaternion_matrix(q: [f32; 4]) -> Mat4 {
    let (mut x, mut y, mut z, mut w) = (q[0], q[1], q[2], q[3]);
    let length = (x * x + y * y + z * z + w * w).sqrt();
    if length <= 1e-12 {
        return IDENTITY;
    }
    x /= length;
    y /= length;
    z /= length;
    w /= length;
    let (xx, yy, zz) = (x * x, y * y, z * z);
    let (xy, xz, yz) = (x * y, x * z, y * z);
    let (wx, wy, wz) = (w * x, w * y, w * z);
    [
        1.0 - 2.0 * (yy + zz),
        2.0 * (xy - wz),
        2.0 * (xz + wy),
        0.0,
        2.0 * (xy + wz),
        1.0 - 2.0 * (xx + zz),
        2.0 * (yz - wx),
        0.0,
        2.0 * (xz - wy),
        2.0 * (yz + wx),
        1.0 - 2.0 * (xx + yy),
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    ]
}

fn srt_matrix(location: [f32; 3], rotation: [f32; 4], scale: [f32; 3]) -> Mat4 {
    let rotation_matrix = quaternion_matrix(rotation);
    let scale_matrix = [
        scale[0], 0.0, 0.0, 0.0, //
        0.0, scale[1], 0.0, 0.0, //
        0.0, 0.0, scale[2], 0.0, //
        0.0, 0.0, 0.0, 1.0,
    ];
    let translation_matrix = [
        1.0, 0.0, 0.0, location[0], //
        0.0, 1.0, 0.0, location[1], //
        0.0, 0.0, 1.0, location[2], //
        0.0, 0.0, 0.0, 1.0,
    ];
    mat4_mul(translation_matrix, mat4_mul(rotation_matrix, scale_matrix))
}

/// Per-vertex joint influences for glTF JOINTS_n / WEIGHTS_n (slot = skin joint index).
pub fn vertex_influences(raw_weights: &[u8; 8], node_hash_count: usize) -> Vec<(u16, f32)> {
    let mut scaled = Vec::new();
    for (slot, &raw) in raw_weights.iter().enumerate() {
        if raw == 0 || slot >= node_hash_count {
            continue;
        }
        let weight = (raw.min(128) as f32) / 128.0;
        scaled.push((slot as u16, weight));
    }
    let total: f32 = scaled.iter().map(|(_, w)| *w).sum();
    if total > 0.0 {
        for (_, w) in &mut scaled {
            *w /= total;
        }
        scaled
    } else {
        vec![(0, 1.0)]
    }
}

/// Pack JOINTS/WEIGHTS sets for one mesh (matches `build_joint_weight_payloads`).
pub fn build_joint_weight_sets(
    raw_weights: &[[u8; 8]],
    node_hash_count: usize,
) -> (Vec<u16>, Vec<f32>, Option<(Vec<u16>, Vec<f32>)>, usize) {
    let mut all: Vec<Vec<(u16, f32)>> = Vec::with_capacity(raw_weights.len());
    let mut max_influences = 0usize;
    for weights in raw_weights {
        let influences = vertex_influences(weights, node_hash_count);
        max_influences = max_influences.max(influences.len());
        all.push(influences);
    }

    let mut joints_0 = Vec::with_capacity(raw_weights.len() * 4);
    let mut weights_0 = Vec::with_capacity(raw_weights.len() * 4);
    let mut joints_1 = Vec::with_capacity(raw_weights.len() * 4);
    let mut weights_1 = Vec::with_capacity(raw_weights.len() * 4);
    let need_set1 = max_influences > 4;

    for influences in &all {
        let mut padded = influences.clone();
        padded.resize(8, (0, 0.0));
        for (slot, weight) in &padded[..4] {
            joints_0.push(*slot);
            weights_0.push(*weight);
        }
        if need_set1 {
            for (slot, weight) in &padded[4..8] {
                joints_1.push(*slot);
                weights_1.push(*weight);
            }
        }
    }

    let set1 = if need_set1 {
        Some((joints_1, weights_1))
    } else {
        None
    };
    (joints_0, weights_0, set1, max_influences)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_mbn_bytes(bone_id: u32, parent_id: u32, loc_y: f32, head: [f32; 3]) -> Vec<u8> {
        let mut data = vec![0u8; MBN_FULL_SIZE];
        data[0..4].copy_from_slice(&bone_id.to_le_bytes());
        data[4..8].copy_from_slice(&parent_id.to_le_bytes());
        data[8..12].copy_from_slice(&4u32.to_le_bytes());
        data[0x10..0x14].copy_from_slice(&loc_y.to_le_bytes());
        // identity rotation floats at diagonal of original file layout
        data[0x18..0x1C].copy_from_slice(&1.0f32.to_le_bytes());
        data[0x28..0x2C].copy_from_slice(&1.0f32.to_le_bytes());
        data[0x38..0x3C].copy_from_slice(&1.0f32.to_le_bytes());
        data[0x3C..0x40].copy_from_slice(&1.0f32.to_le_bytes());
        data[0x40..0x44].copy_from_slice(&1.0f32.to_le_bytes());
        data[0x44..0x48].copy_from_slice(&1.0f32.to_le_bytes());
        // local rotation identity
        data[0x48..0x4C].copy_from_slice(&1.0f32.to_le_bytes());
        data[0x58..0x5C].copy_from_slice(&1.0f32.to_le_bytes());
        data[0x68..0x6C].copy_from_slice(&1.0f32.to_le_bytes());
        data[0x9C..0xA0].copy_from_slice(&head[0].to_le_bytes());
        data[0xA0..0xA4].copy_from_slice(&head[1].to_le_bytes());
        data[0xA4..0xA8].copy_from_slice(&head[2].to_le_bytes());
        // tail - head = (0,1,0)
        data[0x88..0x8C].copy_from_slice(&1.0f32.to_le_bytes());
        data
    }

    #[test]
    fn identity_inverse_is_identity() {
        let inv = affine_inverse(IDENTITY).expect("identity invertible");
        for i in 0..16 {
            assert!((inv[i] - IDENTITY[i]).abs() < 1e-5);
        }
    }

    #[test]
    fn parse_mbn_reads_full_head_tail() {
        let data = sample_mbn_bytes(0x11223344, 0xAABBCCDD, 2.0, [1.0, 5.0, 0.0]);
        let bone = parse_mbn(&data).expect("parse");
        assert_eq!(bone.hash, "11223344");
        assert_eq!(bone.parent.as_deref(), Some("AABBCCDD"));
        assert_eq!(bone.flags, 4);
        assert!((bone.head[1] - 5.0).abs() < 1e-5);
        assert!((bone.tail[1] - 6.0).abs() < 1e-5);
    }

    #[test]
    fn hierarchical_global_translation_matches_recorded_head() {
        // Parent at (0, 10, 0), child local (2, 0, 0) → head (2, 10, 0).
        let parent = sample_mbn_bytes(0x11111111, 0, 10.0, [0.0, 10.0, 0.0]);
        let mut child = sample_mbn_bytes(0x22222222, 0x11111111, 0.0, [2.0, 10.0, 0.0]);
        // child local location = (2, 0, 0)
        child[0x0C..0x10].copy_from_slice(&2.0f32.to_le_bytes());
        child[0x10..0x14].copy_from_slice(&0.0f32.to_le_bytes());
        child[0x14..0x18].copy_from_slice(&0.0f32.to_le_bytes());

        let skeleton = Skeleton::from_mbn_members([
            ("000.mbn", parent.as_slice()),
            ("001.mbn", child.as_slice()),
        ]);
        let g = skeleton.global.get("22222222").expect("child global");
        let t = [g[3], g[7], g[11]];
        let head = skeleton.bones["22222222"].head;
        for i in 0..3 {
            assert!(
                (t[i] - head[i]).abs() < 1e-4,
                "axis {i}: global {t:?} vs head {head:?}"
            );
        }
    }

    #[test]
    fn vertex_influences_normalize_and_skip_zero() {
        let raw = [128, 0, 64, 0, 0, 0, 0, 0];
        let inf = vertex_influences(&raw, 4);
        assert_eq!(inf.len(), 2);
        let total: f32 = inf.iter().map(|(_, w)| *w).sum();
        assert!((total - 1.0).abs() < 1e-5);
    }

    #[test]
    fn joint_weight_sets_emit_set1_when_needed() {
        let mut raw = [0u8; 8];
        for i in 0..6 {
            raw[i] = 32;
        }
        let (_j0, _w0, set1, max_inf) = build_joint_weight_sets(&[raw], 8);
        assert!(max_inf >= 6);
        assert!(set1.is_some());
    }

    #[test]
    fn gltf_column_major_transposes_translation() {
        let m = srt_matrix([5.0, 6.0, 7.0], [0.0, 0.0, 0.0, 1.0], [1.0, 1.0, 1.0]);
        let col = gltf_column_major(m);
        assert!((col[12] - 5.0).abs() < 1e-5);
        assert!((col[13] - 6.0).abs() < 1e-5);
        assert!((col[14] - 7.0).abs() < 1e-5);
    }
}
