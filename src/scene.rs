//! Turns one XPCK archive into a previewable/exportable scene:
//! decoded meshes, decoded textures, and the material bindings that link them.

use crate::{imgp, material, xmpr, xpck};
use anyhow::Result;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

#[derive(Clone)]
pub struct SceneTexture {
    /// Archive member name, e.g. `002.xi`.
    pub member: String,
    pub texture: imgp::Texture,
}

#[derive(Clone)]
pub struct SceneMesh {
    pub mesh: xmpr::Mesh,
    /// Index into [`Scene::textures`], when a binding was resolved.
    pub texture_index: Option<usize>,
    pub binding: material::BindConfidence,
    pub visible: bool,
}

#[derive(Clone, Debug)]
pub struct DecodeFailure {
    pub member: String,
    pub error: String,
}

pub struct Scene {
    pub archive_path: Option<PathBuf>,
    pub archive_name: String,
    pub member_count: usize,
    pub archive_size: usize,
    pub meshes: Vec<SceneMesh>,
    pub textures: Vec<SceneTexture>,
    pub bindings: material::Bindings,
    pub mesh_failures: Vec<DecodeFailure>,
    pub texture_failures: Vec<DecodeFailure>,
    /// Extension -> member count, for the inspector.
    pub member_extensions: Vec<(String, usize)>,
    pub bounds_min: [f32; 3],
    pub bounds_max: [f32; 3],
}

impl Scene {
    pub fn total_vertices(&self) -> usize {
        self.meshes.iter().map(|m| m.mesh.vertex_count()).sum()
    }

    pub fn total_faces(&self) -> usize {
        self.meshes.iter().map(|m| m.mesh.face_count()).sum()
    }

    pub fn visible_faces(&self) -> usize {
        self.meshes
            .iter()
            .filter(|m| m.visible)
            .map(|m| m.mesh.face_count())
            .sum()
    }

    pub fn is_skinned(&self) -> bool {
        self.meshes.iter().any(|m| m.mesh.is_skinned())
    }

    pub fn texture(&self, index: usize) -> Option<&SceneTexture> {
        self.textures.get(index)
    }

    /// Stable key describing which meshes are visible, for GPU cache validation.
    pub fn visibility_key(&self) -> u64 {
        let mut key = 1469598103934665603u64;
        for (i, mesh) in self.meshes.iter().enumerate() {
            if mesh.visible {
                key ^= i as u64 + 1;
                key = key.wrapping_mul(1099511628211);
            }
        }
        key
    }

    /// Load and decode an archive from disk.
    pub fn load(path: &Path, triangulation: xmpr::Triangulation, layout: imgp::PixelLayout) -> Result<Self> {
        let archive = xpck::Archive::open(path)?;
        let name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("archive")
            .to_string();
        Ok(Self::from_archive(&archive, name, triangulation, layout))
    }

    /// Decode every `.prm` and `.xi` member and resolve texture bindings.
    pub fn from_archive(
        archive: &xpck::Archive,
        archive_name: String,
        triangulation: xmpr::Triangulation,
        layout: imgp::PixelLayout,
    ) -> Self {
        let bindings = material::build(archive);

        let mut textures = Vec::new();
        let mut texture_failures = Vec::new();
        let mut texture_index_by_member: HashMap<String, usize> = HashMap::new();

        for entry in archive.entries_with_extension("xi") {
            let Some(data) = archive.member(entry.index) else {
                texture_failures.push(DecodeFailure {
                    member: entry.name.clone(),
                    error: "member range is invalid".to_string(),
                });
                continue;
            };
            match imgp::decode(data, layout) {
                Ok(texture) => {
                    texture_index_by_member.insert(entry.name.clone(), textures.len());
                    textures.push(SceneTexture {
                        member: entry.name.clone(),
                        texture,
                    });
                }
                Err(e) => texture_failures.push(DecodeFailure {
                    member: entry.name.clone(),
                    error: e.to_string(),
                }),
            }
        }

        let mut meshes = Vec::new();
        let mut mesh_failures = Vec::new();

        for entry in archive.entries_with_extension("prm") {
            let Some(data) = archive.member(entry.index) else {
                mesh_failures.push(DecodeFailure {
                    member: entry.name.clone(),
                    error: "member range is invalid".to_string(),
                });
                continue;
            };
            match xmpr::decode(&entry.name, data, triangulation) {
                Ok(mesh) => {
                    let texture_index = bindings
                        .texture_for_material(&mesh.material)
                        .and_then(|member| texture_index_by_member.get(member).copied());
                    let binding = bindings.confidence_for_material(&mesh.material);
                    meshes.push(SceneMesh {
                        mesh,
                        texture_index,
                        binding,
                        visible: true,
                    });
                }
                Err(e) => mesh_failures.push(DecodeFailure {
                    member: entry.name.clone(),
                    error: e.to_string(),
                }),
            }
        }

        // Single-texture archives: bind any unresolved mesh to the only texture.
        if textures.len() == 1 {
            for mesh in &mut meshes {
                if mesh.texture_index.is_none() {
                    mesh.texture_index = Some(0);
                    mesh.binding = material::BindConfidence::ResourceOrder;
                }
            }
        }

        let mut extension_counts: HashMap<String, usize> = HashMap::new();
        for entry in &archive.entries {
            let ext = entry.extension();
            let key = if ext.is_empty() { "(none)".to_string() } else { ext };
            *extension_counts.entry(key).or_insert(0) += 1;
        }
        let mut member_extensions: Vec<(String, usize)> = extension_counts.into_iter().collect();
        member_extensions.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));

        let mut bounds_min = [f32::INFINITY; 3];
        let mut bounds_max = [f32::NEG_INFINITY; 3];
        for mesh in &meshes {
            if mesh.mesh.positions.is_empty() {
                continue;
            }
            for axis in 0..3 {
                bounds_min[axis] = bounds_min[axis].min(mesh.mesh.bounds_min[axis]);
                bounds_max[axis] = bounds_max[axis].max(mesh.mesh.bounds_max[axis]);
            }
        }
        if !bounds_min[0].is_finite() {
            bounds_min = [0.0; 3];
            bounds_max = [0.0; 3];
        }

        Self {
            archive_path: archive.path.clone(),
            archive_name,
            member_count: archive.entries.len(),
            archive_size: archive.total_size(),
            meshes,
            textures,
            bindings,
            mesh_failures,
            texture_failures,
            member_extensions,
            bounds_min,
            bounds_max,
        }
    }

    pub fn set_all_visible(&mut self, visible: bool) {
        for mesh in &mut self.meshes {
            mesh.visible = visible;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn empty_scene() -> Scene {
        Scene {
            archive_path: None,
            archive_name: "test.xc".to_string(),
            member_count: 0,
            archive_size: 0,
            meshes: Vec::new(),
            textures: Vec::new(),
            bindings: material::Bindings::default(),
            mesh_failures: Vec::new(),
            texture_failures: Vec::new(),
            member_extensions: Vec::new(),
            bounds_min: [0.0; 3],
            bounds_max: [0.0; 3],
        }
    }

    #[test]
    fn empty_scene_reports_zero_totals() {
        let scene = empty_scene();
        assert_eq!(scene.total_vertices(), 0);
        assert_eq!(scene.total_faces(), 0);
        assert!(!scene.is_skinned());
    }

    #[test]
    fn visibility_key_changes_with_visibility() {
        let mut scene = empty_scene();
        scene.meshes.push(SceneMesh {
            mesh: blank_mesh(),
            texture_index: None,
            binding: material::BindConfidence::Unresolved,
            visible: true,
        });
        let visible_key = scene.visibility_key();
        scene.set_all_visible(false);
        assert_ne!(visible_key, scene.visibility_key());
    }

    fn blank_mesh() -> xmpr::Mesh {
        xmpr::Mesh {
            source: "000.prm".to_string(),
            name: "m".to_string(),
            material: "DefaultLib.m".to_string(),
            positions: Vec::new(),
            uvs: Vec::new(),
            normals: Vec::new(),
            faces: Vec::new(),
            has_uvs: false,
            stride: 0,
            position_format: xmpr::PositionFormat::Float32x3,
            uv_format: xmpr::UvFormat::Absent,
            attributes: Vec::new(),
            node_hashes: Vec::new(),
            raw_weights: Vec::new(),
            attribute_method: crate::level5::Method::None,
            vertex_method: crate::level5::Method::None,
            primitive_type: 2,
            declared_face_count: 0,
            dropped_degenerate_faces: 0,
            bounds_min: [0.0; 3],
            bounds_max: [0.0; 3],
            warnings: Vec::new(),
        }
    }
}
