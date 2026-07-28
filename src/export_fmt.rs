//! Export format selection shared by the GUI and the batch worker.

use crate::{gltf, obj, scene::Scene};
use anyhow::Result;
use std::path::{Path, PathBuf};

/// On-disk format for one archive package.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Format {
    Gltf,
    Obj,
}

impl Format {
    pub fn label(self) -> &'static str {
        match self {
            Self::Gltf => "glTF 2.0 (.gltf + .bin + textures)",
            Self::Obj => "Wavefront OBJ (.obj + .mtl + textures)",
        }
    }

    pub fn short_label(self) -> &'static str {
        match self {
            Self::Gltf => "glTF",
            Self::Obj => "OBJ",
        }
    }
}

impl Default for Format {
    fn default() -> Self {
        Self::Gltf
    }
}

/// Options applied to every format.
#[derive(Clone, Copy, Debug)]
pub struct Options {
    pub format: Format,
    pub only_visible: bool,
    pub write_textures: bool,
}

impl Default for Options {
    fn default() -> Self {
        Self {
            format: Format::Gltf,
            only_visible: false,
            write_textures: true,
        }
    }
}

impl Options {
    fn into_gltf(self) -> gltf::ExportOptions {
        gltf::ExportOptions {
            only_visible: self.only_visible,
            write_textures: self.write_textures,
        }
    }
}

/// Result of exporting one archive package.
#[derive(Clone, Debug)]
pub struct Summary {
    pub primary_path: PathBuf,
    pub mesh_count: usize,
    pub vertex_count: usize,
    pub face_count: usize,
    pub material_count: usize,
    pub texture_count: usize,
    pub skipped_meshes: usize,
    pub format: Format,
}

impl From<(gltf::ExportSummary, Format)> for Summary {
    fn from((summary, format): (gltf::ExportSummary, Format)) -> Self {
        Self {
            primary_path: summary.gltf_path,
            mesh_count: summary.mesh_count,
            vertex_count: summary.vertex_count,
            face_count: summary.face_count,
            material_count: summary.material_count,
            texture_count: summary.texture_count,
            skipped_meshes: summary.skipped_meshes,
            format,
        }
    }
}

/// Export one decoded scene into `out_dir` using the original archive stem as
/// the file base name.
pub fn export_scene(
    scene: &Scene,
    out_dir: &Path,
    name: &str,
    options: Options,
) -> Result<Summary> {
    let gltf_options = options.into_gltf();
    let summary = match options.format {
        Format::Gltf => gltf::export_scene(scene, out_dir, name, gltf_options)?,
        Format::Obj => obj::export_scene(scene, out_dir, name, gltf_options)?,
    };
    Ok(Summary::from((summary, options.format)))
}

/// Package directory for one archive under the chosen output root.
///
/// Preserves the original relative path layout so a batch export of
/// `chr/ms001000/ms001000_p000.xc` lands in:
///
/// ```text
/// <out>/chr/ms001000/ms001000_p000/
/// ```
///
/// Each path segment is sanitized for the filesystem. When two archives would
/// map to the same directory, a numeric suffix is appended to the leaf.
pub fn package_dir(out_dir: &Path, relative: &str, taken: &mut std::collections::HashSet<String>) -> PathBuf {
    let relative_path = Path::new(relative);
    let mut segments: Vec<String> = Vec::new();

    if let Some(parent) = relative_path.parent() {
        for component in parent.components() {
            if let std::path::Component::Normal(part) = component {
                let name = part.to_str().unwrap_or("dir");
                segments.push(gltf::sanitize(name, "dir"));
            }
        }
    }

    let stem = relative_path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("archive");
    let leaf = gltf::sanitize(stem, "archive");

    // Key used for uniqueness is the joined relative package path.
    let base_key = {
        let mut parts = segments.clone();
        parts.push(leaf.clone());
        parts.join("/")
    };

    let unique_leaf = if taken.insert(base_key.clone()) {
        leaf
    } else {
        let mut resolved = leaf.clone();
        for suffix in 2..=u32::MAX {
            let candidate_leaf = format!("{leaf}_{suffix}");
            let mut parts = segments.clone();
            parts.push(candidate_leaf.clone());
            let key = parts.join("/");
            if taken.insert(key) {
                resolved = candidate_leaf;
                break;
            }
        }
        resolved
    };

    let mut package = out_dir.to_path_buf();
    for segment in segments {
        package.push(segment);
    }
    package.push(unique_leaf);
    package
}

/// Package directory when only a local file name is known (single-archive open).
pub fn package_dir_from_name(out_dir: &Path, archive_name: &str) -> PathBuf {
    let stem = Path::new(archive_name)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(archive_name);
    out_dir.join(gltf::sanitize(stem, "archive"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn package_dir_keeps_the_original_relative_tree() {
        let mut taken = HashSet::new();
        let dir = package_dir(Path::new("out"), "chr/ms001000/ms001000_p000.xc", &mut taken);
        assert_eq!(
            dir,
            PathBuf::from("out")
                .join("chr")
                .join("ms001000")
                .join("ms001000_p000")
        );
        assert_eq!(taken.len(), 1);
    }

    #[test]
    fn package_dir_disambiguates_colliding_stems_in_the_same_folder() {
        let mut taken = HashSet::new();
        let a = package_dir(Path::new("out"), "chr/a/model.xc", &mut taken);
        let b = package_dir(Path::new("out"), "chr/a/model.xc", &mut taken);
        assert_eq!(a.file_name().unwrap(), "model");
        assert_eq!(b.file_name().unwrap(), "model_2");
    }

    #[test]
    fn package_dir_from_name_uses_the_archive_stem() {
        assert_eq!(
            package_dir_from_name(Path::new("out"), "ms001000_p000.xc"),
            PathBuf::from("out").join("ms001000_p000")
        );
    }
}
