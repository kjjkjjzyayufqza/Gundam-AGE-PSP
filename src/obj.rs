//! Wavefront OBJ + MTL export for decoded Gundam AGE PSP scenes.
//!
//! Layout (mirrors the Python pipeline under `tools/`):
//!
//! ```text
//! <out_dir>/
//!   <name>.obj
//!   <name>.mtl
//!   textures/<stem>.png
//! ```
//!
//! Geometry is the decoded bind pose. Animation is not executed.

use crate::gltf::{self, ExportOptions, ExportSummary};
use crate::scene::Scene;
use anyhow::{Result, bail};
use std::collections::{HashMap, HashSet};
use std::path::Path;

/// Export a decoded scene as OBJ + MTL, optionally with PNG textures.
pub fn export_scene(
    scene: &Scene,
    out_dir: &Path,
    name: &str,
    options: ExportOptions,
) -> Result<ExportSummary> {
    let selected: Vec<usize> = scene
        .meshes
        .iter()
        .enumerate()
        .filter(|(_, m)| !options.only_visible || m.visible)
        .filter(|(_, m)| !m.mesh.positions.is_empty())
        .map(|(i, _)| i)
        .collect();

    if selected.is_empty() {
        bail!(
            "{} has no exportable geometry (decoded meshes: {})",
            scene.archive_name,
            scene.meshes.len()
        );
    }

    std::fs::create_dir_all(out_dir)?;
    let base = gltf::sanitize(name, "model");
    let obj_path = out_dir.join(format!("{base}.obj"));
    let mtl_path = out_dir.join(format!("{base}.mtl"));
    let mtl_file_name = mtl_path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("model.mtl")
        .to_string();

    // Write only textures referenced by exported meshes (or every texture when
    // the user asked for textures and nothing is bound — still export all so
    // the package is complete for unresolved archives).
    let mut texture_uri_by_index: HashMap<usize, String> = HashMap::new();
    let mut texture_count = 0usize;
    if options.write_textures {
        let mut needed: Vec<usize> = selected
            .iter()
            .filter_map(|i| scene.meshes[*i].texture_index)
            .collect();
        if needed.is_empty() {
            needed = (0..scene.textures.len()).collect();
        } else {
            needed.sort_unstable();
            needed.dedup();
        }

        if !needed.is_empty() {
            let texture_dir = out_dir.join("textures");
            std::fs::create_dir_all(&texture_dir)?;
            for index in needed {
                let Some(entry) = scene.texture(index) else {
                    continue;
                };
                let stem = Path::new(&entry.member)
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .unwrap_or("texture");
                let file_name = format!("{}.png", gltf::sanitize(stem, "texture"));
                let png = crate::imgp::encode_png(&entry.texture)?;
                std::fs::write(texture_dir.join(&file_name), png)?;
                texture_uri_by_index.insert(index, format!("textures/{file_name}"));
                texture_count += 1;
            }
        }
    }

    // One MTL material per unique (material name, texture uri) pair.
    let mut material_keys: Vec<String> = Vec::new();
    let mut material_index_by_key: HashMap<String, usize> = HashMap::new();
    let mut material_defs: Vec<MaterialDef> = Vec::new();

    for &mesh_index in &selected {
        let entry = &scene.meshes[mesh_index];
        let material_name = gltf::sanitize(&entry.mesh.material, "default_material");
        let texture_uri = entry
            .texture_index
            .and_then(|i| texture_uri_by_index.get(&i).cloned());
        let key = format!("{material_name}|{}", texture_uri.clone().unwrap_or_default());
        if material_index_by_key.contains_key(&key) {
            continue;
        }
        let index = material_defs.len();
        material_index_by_key.insert(key.clone(), index);
        material_keys.push(key);
        material_defs.push(MaterialDef {
            name: unique_mtl_name(&material_name, index, &material_defs),
            map_kd: texture_uri,
            age_material: entry.mesh.material.clone(),
            binding: entry.binding.label().to_string(),
        });
    }

    write_mtl(&mtl_path, &material_defs)?;
    let (vertex_count, face_count) =
        write_obj(&obj_path, scene, &selected, &mtl_file_name, |mesh_index| {
            let entry = &scene.meshes[mesh_index];
            let material_name = gltf::sanitize(&entry.mesh.material, "default_material");
            let texture_uri = entry
                .texture_index
                .and_then(|i| texture_uri_by_index.get(&i).cloned())
                .unwrap_or_default();
            let key = format!("{material_name}|{texture_uri}");
            material_defs[material_index_by_key[&key]].name.clone()
        })?;

    Ok(ExportSummary {
        gltf_path: obj_path,
        bin_path: mtl_path,
        mesh_count: selected.len(),
        vertex_count,
        face_count,
        material_count: material_defs.len(),
        texture_count,
        skipped_meshes: scene.meshes.len() - selected.len(),
    })
}

struct MaterialDef {
    name: String,
    map_kd: Option<String>,
    age_material: String,
    binding: String,
}

fn unique_mtl_name(base: &str, index: usize, existing: &[MaterialDef]) -> String {
    let taken: HashSet<&str> = existing.iter().map(|m| m.name.as_str()).collect();
    if !taken.contains(base) {
        return base.to_string();
    }
    let candidate = format!("{base}_{index}");
    if !taken.contains(candidate.as_str()) {
        return candidate;
    }
    for suffix in 2..=u32::MAX {
        let candidate = format!("{base}_{suffix}");
        if !taken.contains(candidate.as_str()) {
            return candidate;
        }
    }
    base.to_string()
}

fn write_mtl(path: &Path, materials: &[MaterialDef]) -> Result<()> {
    let mut lines = vec![
        "# MTL generated by age_viewer from Gundam AGE PSP materials".to_string(),
        "# map_Kd paths are relative to this MTL file.".to_string(),
        String::new(),
    ];
    for material in materials {
        lines.push(format!("newmtl {}", material.name));
        lines.push(format!("# age_material {}", material.age_material));
        lines.push(format!("# binding {}", material.binding));
        lines.push("Ka 1.000 1.000 1.000".to_string());
        lines.push("Kd 1.000 1.000 1.000".to_string());
        lines.push("Ks 0.000 0.000 0.000".to_string());
        lines.push("d 1.0".to_string());
        lines.push("illum 1".to_string());
        if let Some(map_kd) = &material.map_kd {
            lines.push(format!("map_Kd {map_kd}"));
        } else {
            lines.push("# map_Kd unresolved".to_string());
        }
        lines.push(String::new());
    }
    std::fs::write(path, lines.join("\n"))?;
    Ok(())
}

fn write_obj(
    path: &Path,
    scene: &Scene,
    selected: &[usize],
    mtllib: &str,
    material_for: impl Fn(usize) -> String,
) -> Result<(usize, usize)> {
    let mut lines = vec![
        "# OBJ generated by age_viewer from Gundam AGE PSP XMPR/XPVB data".to_string(),
        "# Static bind-pose export; animation data is not executed.".to_string(),
        format!("# source_archive {}", scene.archive_name),
        format!("mtllib {mtllib}"),
        String::new(),
    ];

    let mut vertex_base = 0u32;
    let mut vt_base = 0u32;
    let mut vn_base = 0u32;
    let mut total_vertices = 0usize;
    let mut total_faces = 0usize;

    for &mesh_index in selected {
        let entry = &scene.meshes[mesh_index];
        let mesh = &entry.mesh;
        let object_name = gltf::sanitize(&mesh.name, &format!("mesh_{mesh_index}"));
        let material_name = material_for(mesh_index);

        lines.push(format!("o {object_name}"));
        lines.push(format!("# source {}", mesh.source));
        lines.push(format!("# material {}", mesh.material));
        lines.push(format!("usemtl {material_name}"));
        for warning in &mesh.warnings {
            lines.push(format!("# warning {warning}"));
        }

        for p in &mesh.positions {
            lines.push(format!("v {:.8} {:.8} {:.8}", p[0], p[1], p[2]));
        }
        total_vertices += mesh.positions.len();

        let has_uv = mesh.has_uvs && mesh.uvs.len() == mesh.positions.len();
        if has_uv {
            for uv in &mesh.uvs {
                // OBJ UV origin is bottom-left; decoded UVs already match that.
                lines.push(format!("vt {:.8} {:.8}", uv[0], uv[1]));
            }
        }

        let has_normals = mesh.normals.len() == mesh.positions.len() && !mesh.normals.is_empty();
        if has_normals {
            for n in &mesh.normals {
                lines.push(format!("vn {:.8} {:.8} {:.8}", n[0], n[1], n[2]));
            }
        }

        for face in &mesh.faces {
            let a = face[0] + 1;
            let b = face[1] + 1;
            let c = face[2] + 1;
            let line = match (has_uv, has_normals) {
                (true, true) => format!(
                    "f {}/{}/{} {}/{}/{} {}/{}/{}",
                    a + vertex_base,
                    a + vt_base,
                    a + vn_base,
                    b + vertex_base,
                    b + vt_base,
                    b + vn_base,
                    c + vertex_base,
                    c + vt_base,
                    c + vn_base
                ),
                (true, false) => format!(
                    "f {}/{} {}/{} {}/{}",
                    a + vertex_base,
                    a + vt_base,
                    b + vertex_base,
                    b + vt_base,
                    c + vertex_base,
                    c + vt_base
                ),
                (false, true) => format!(
                    "f {}//{} {}//{} {}//{}",
                    a + vertex_base,
                    a + vn_base,
                    b + vertex_base,
                    b + vn_base,
                    c + vertex_base,
                    c + vn_base
                ),
                (false, false) => {
                    format!("f {} {} {}", a + vertex_base, b + vertex_base, c + vertex_base)
                }
            };
            lines.push(line);
        }
        total_faces += mesh.faces.len();

        vertex_base += mesh.positions.len() as u32;
        if has_uv {
            vt_base += mesh.positions.len() as u32;
        }
        if has_normals {
            vn_base += mesh.positions.len() as u32;
        }
        lines.push(String::new());
    }

    lines.push(String::new());
    std::fs::write(path, lines.join("\n"))?;
    Ok((total_vertices, total_faces))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unique_mtl_names_disambiguate_collisions() {
        let existing = vec![MaterialDef {
            name: "body".to_string(),
            map_kd: None,
            age_material: "body".to_string(),
            binding: "unresolved".to_string(),
        }];
        assert_eq!(unique_mtl_name("body", 1, &existing), "body_1");
        assert_eq!(unique_mtl_name("armor", 0, &existing), "armor");
    }
}
