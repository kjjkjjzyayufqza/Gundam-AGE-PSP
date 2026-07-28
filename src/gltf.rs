//! Static glTF 2.0 export for decoded Gundam AGE PSP scenes.
//!
//! Writes `<name>.gltf`, `<name>.bin` and a `textures/` folder of PNGs.
//! Geometry is the decoded bind pose. When meshes carry XMPR node hashes and
//! slot-7 weights, the exporter also writes:
//!
//! - joint nodes from MBN bind transforms (identity fallback if a hash is missing)
//! - `skins` with inverse bind matrices
//! - `JOINTS_0` / `WEIGHTS_0` (and `_1` when more than four influences)
//!
//! Animation tracks are not executed.

use crate::mbn::{self, Mat4, IDENTITY};
use crate::{imgp, scene::Scene};
use anyhow::{Result, bail};
use serde_json::{Map, Value, json};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

const COMPONENT_FLOAT: u32 = 5126;
const COMPONENT_UNSIGNED_BYTE: u32 = 5121;
const COMPONENT_UNSIGNED_SHORT: u32 = 5123;
const COMPONENT_UNSIGNED_INT: u32 = 5125;
const TARGET_ARRAY_BUFFER: u32 = 34962;
const TARGET_ELEMENT_ARRAY_BUFFER: u32 = 34963;
const MODE_POINTS: u32 = 0;
const MODE_TRIANGLES: u32 = 4;

#[derive(Clone, Copy, Debug)]
pub struct ExportOptions {
    /// Export only meshes currently ticked visible in the UI.
    pub only_visible: bool,
    /// Write bound textures as PNG next to the glTF.
    pub write_textures: bool,
    /// Write skins, joint nodes, JOINTS/WEIGHTS when mesh weight data is present.
    pub export_skins: bool,
}

impl Default for ExportOptions {
    fn default() -> Self {
        Self {
            only_visible: false,
            write_textures: true,
            export_skins: true,
        }
    }
}

#[derive(Clone, Debug)]
pub struct ExportSummary {
    pub gltf_path: PathBuf,
    pub bin_path: PathBuf,
    pub mesh_count: usize,
    pub vertex_count: usize,
    pub face_count: usize,
    pub material_count: usize,
    pub texture_count: usize,
    pub skipped_meshes: usize,
    pub skin_count: usize,
    pub joint_node_count: usize,
    pub weighted_vertex_count: usize,
    pub mbn_bone_count: usize,
    pub missing_mbn_joint_count: usize,
}

/// Accumulates the binary buffer plus bufferView/accessor tables.
struct BufferBuilder {
    buffer: Vec<u8>,
    views: Vec<Value>,
    accessors: Vec<Value>,
}

impl BufferBuilder {
    fn new() -> Self {
        Self {
            buffer: Vec::new(),
            views: Vec::new(),
            accessors: Vec::new(),
        }
    }

    fn align(&mut self) {
        while self.buffer.len() % 4 != 0 {
            self.buffer.push(0);
        }
    }

    fn add_view(&mut self, payload: &[u8], target: Option<u32>) -> usize {
        self.align();
        let offset = self.buffer.len();
        self.buffer.extend_from_slice(payload);
        self.align();
        let mut view = Map::new();
        view.insert("buffer".to_string(), json!(0));
        view.insert("byteOffset".to_string(), json!(offset));
        view.insert("byteLength".to_string(), json!(payload.len()));
        if let Some(target) = target {
            view.insert("target".to_string(), json!(target));
        }
        self.views.push(Value::Object(view));
        self.views.len() - 1
    }

    fn add_accessor(
        &mut self,
        payload: &[u8],
        component_type: u32,
        accessor_type: &str,
        count: usize,
        target: Option<u32>,
        min: Option<Vec<f32>>,
        max: Option<Vec<f32>>,
    ) -> usize {
        let view = self.add_view(payload, target);
        let mut accessor = Map::new();
        accessor.insert("bufferView".to_string(), json!(view));
        accessor.insert("byteOffset".to_string(), json!(0));
        accessor.insert("componentType".to_string(), json!(component_type));
        accessor.insert("count".to_string(), json!(count));
        accessor.insert("type".to_string(), json!(accessor_type));
        if let Some(min) = min {
            accessor.insert("min".to_string(), json!(min));
        }
        if let Some(max) = max {
            accessor.insert("max".to_string(), json!(max));
        }
        self.accessors.push(Value::Object(accessor));
        self.accessors.len() - 1
    }
}

fn pack_f32(values: &[f32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(values.len() * 4);
    for v in values {
        out.extend_from_slice(&v.to_le_bytes());
    }
    out
}

fn pack_u8(values: &[u16]) -> Vec<u8> {
    values.iter().map(|v| *v as u8).collect()
}

fn pack_u16(values: &[u32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(values.len() * 2);
    for v in values {
        out.extend_from_slice(&(*v as u16).to_le_bytes());
    }
    out
}

fn pack_u16_from_u16(values: &[u16]) -> Vec<u8> {
    let mut out = Vec::with_capacity(values.len() * 2);
    for v in values {
        out.extend_from_slice(&v.to_le_bytes());
    }
    out
}

fn pack_u32(values: &[u32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(values.len() * 4);
    for v in values {
        out.extend_from_slice(&v.to_le_bytes());
    }
    out
}

/// Make a name safe for use as a file or glTF identifier.
pub fn sanitize(name: &str, fallback: &str) -> String {
    let cleaned: String = name
        .trim()
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | '.') {
                c
            } else {
                '_'
            }
        })
        .collect();
    let cleaned = cleaned.trim_matches('.').to_string();
    if cleaned.is_empty() {
        fallback.to_string()
    } else {
        cleaned
    }
}

fn mesh_has_exportable_weights(mesh: &crate::xmpr::Mesh) -> bool {
    mesh.is_skinned()
        && mesh.raw_weights.len() == mesh.positions.len()
        && !mesh.node_hashes.is_empty()
}

/// Export a decoded scene as static glTF 2.0 (optionally with skins).
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
    let base = sanitize(name, "model");
    let gltf_path = out_dir.join(format!("{base}.gltf"));
    let bin_path = out_dir.join(format!("{base}.bin"));

    // Write only the textures actually referenced by exported meshes.
    let mut texture_uri_by_index: HashMap<usize, String> = HashMap::new();
    if options.write_textures {
        let texture_dir = out_dir.join("textures");
        let mut needed: Vec<usize> = selected
            .iter()
            .filter_map(|i| scene.meshes[*i].texture_index)
            .collect();
        needed.sort_unstable();
        needed.dedup();

        if !needed.is_empty() {
            std::fs::create_dir_all(&texture_dir)?;
        }
        for index in needed {
            let Some(entry) = scene.texture(index) else {
                continue;
            };
            let stem = Path::new(&entry.member)
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("texture");
            let file_name = format!("{}.png", sanitize(stem, "texture"));
            let png = imgp::encode_png(&entry.texture)?;
            std::fs::write(texture_dir.join(&file_name), png)?;
            texture_uri_by_index.insert(index, format!("textures/{file_name}"));
        }
    }

    let mut buffer = BufferBuilder::new();
    let mut meshes_json: Vec<Value> = Vec::new();
    let mut nodes_json: Vec<Value> = Vec::new();
    let mut root_nodes: Vec<usize> = Vec::new();
    let mut materials_json: Vec<Value> = Vec::new();
    let mut images_json: Vec<Value> = Vec::new();
    let mut textures_json: Vec<Value> = Vec::new();
    let mut skins_json: Vec<Value> = Vec::new();

    let mut image_index_by_uri: HashMap<String, usize> = HashMap::new();
    let mut texture_index_by_uri: HashMap<String, usize> = HashMap::new();
    let mut material_index_by_key: HashMap<String, usize> = HashMap::new();

    // Joint node index by uppercase node hash (shared across skins).
    let mut joint_node_by_hash: HashMap<String, usize> = HashMap::new();
    let mut missing_mbn_joints: std::collections::HashSet<String> =
        std::collections::HashSet::new();

    let mut total_vertices = 0usize;
    let mut total_faces = 0usize;
    let mut weighted_vertex_count = 0usize;

    // Mesh vertices (often s16_norm bind pose) and MBN joints live in different
    // recorded unit systems. Align mesh AABB → MBN head AABB so the exported
    // geometry sits in the same space as the file-recorded skeleton. Joint
    // matrices stay pure MBN (no invented bone scaling).
    let mut mesh_min = [f32::INFINITY; 3];
    let mut mesh_max = [f32::NEG_INFINITY; 3];
    for &mesh_index in &selected {
        for p in &scene.meshes[mesh_index].mesh.positions {
            for axis in 0..3 {
                mesh_min[axis] = mesh_min[axis].min(p[axis]);
                mesh_max[axis] = mesh_max[axis].max(p[axis]);
            }
        }
    }
    if !mesh_min[0].is_finite() {
        mesh_min = [0.0; 3];
        mesh_max = [0.0; 3];
    }
    let export_skins_any = options.export_skins
        && selected
            .iter()
            .any(|&i| mesh_has_exportable_weights(&scene.meshes[i].mesh));
    let (mesh_space_scale, mesh_space_translation) =
        if export_skins_any {
            if let Some((bone_min, bone_max)) = scene.skeleton.bind_position_bounds() {
                mbn::aabb_align_transform(mesh_min, mesh_max, bone_min, bone_max)
            } else {
                (1.0, [0.0, 0.0, 0.0])
            }
        } else {
            (1.0, [0.0, 0.0, 0.0])
        };
    let export_skeleton = &scene.skeleton;

    // Recursively ensure a joint node exists, creating parents first.
    // Returns the node index in `nodes_json`.
    let ensure_joint = |hash: &str,
                        nodes_json: &mut Vec<Value>,
                        root_nodes: &mut Vec<usize>,
                        joint_node_by_hash: &mut HashMap<String, usize>,
                        missing: &mut std::collections::HashSet<String>,
                        skeleton: &mbn::Skeleton|
     -> usize {
        fn ensure_inner(
            hash: &str,
            nodes_json: &mut Vec<Value>,
            root_nodes: &mut Vec<usize>,
            joint_node_by_hash: &mut HashMap<String, usize>,
            missing: &mut std::collections::HashSet<String>,
            skeleton: &mbn::Skeleton,
            visiting: &mut std::collections::HashSet<String>,
        ) -> usize {
            let key = hash.to_ascii_uppercase();
            if let Some(&index) = joint_node_by_hash.get(&key) {
                return index;
            }
            if !visiting.insert(key.clone()) {
                // Cycle: emit identity root joint.
                let index = nodes_json.len();
                nodes_json.push(json!({
                    "name": format!("joint_{key}"),
                    "matrix": mbn::gltf_column_major(IDENTITY).to_vec(),
                    "extras": { "node_hash": key, "source": "cycle fallback" }
                }));
                joint_node_by_hash.insert(key.clone(), index);
                root_nodes.push(index);
                return index;
            }

            let parent_hash = skeleton.parent_of(&key).map(|s| s.to_string());
            let parent_index = parent_hash.as_ref().map(|p| {
                ensure_inner(
                    p,
                    nodes_json,
                    root_nodes,
                    joint_node_by_hash,
                    missing,
                    skeleton,
                    visiting,
                )
            });

            let in_mbn = skeleton.bones.contains_key(&key);
            if !in_mbn {
                missing.insert(key.clone());
            }
            let local: Mat4 = skeleton.local_matrix(&key);
            let source = if in_mbn {
                "MBN bind pose"
            } else {
                "XMPR node table identity fallback"
            };

            let index = nodes_json.len();
            nodes_json.push(json!({
                "name": format!("joint_{key}"),
                "matrix": mbn::gltf_column_major(local).to_vec(),
                "extras": {
                    "node_hash": key,
                    "source": source,
                }
            }));
            joint_node_by_hash.insert(key.clone(), index);

            if let Some(parent_index) = parent_index {
                let parent = nodes_json[parent_index]
                    .as_object_mut()
                    .expect("joint node object");
                let children = parent
                    .entry("children".to_string())
                    .or_insert_with(|| Value::Array(Vec::new()));
                if let Value::Array(list) = children {
                    list.push(json!(index));
                }
            } else {
                root_nodes.push(index);
            }

            visiting.remove(&key);
            index
        }

        let mut visiting = std::collections::HashSet::new();
        ensure_inner(
            hash,
            nodes_json,
            root_nodes,
            joint_node_by_hash,
            missing,
            skeleton,
            &mut visiting,
        )
    };

    for &mesh_index in &selected {
        let entry = &scene.meshes[mesh_index];
        let mesh = &entry.mesh;

        // When skins are present, lift mesh positions into MBN/skeleton space
        // using the transform derived from recorded MBN head bounds.
        let apply_mesh_space = export_skins_any
            && ((mesh_space_scale - 1.0).abs() > 1e-8
                || mesh_space_translation.iter().any(|v| v.abs() > 1e-8));
        let mut positions: Vec<f32> = Vec::with_capacity(mesh.positions.len() * 3);
        let mut min = [f32::INFINITY; 3];
        let mut max = [f32::NEG_INFINITY; 3];
        for p in &mesh.positions {
            let q = if apply_mesh_space {
                mbn::transform_point(mesh_space_scale, mesh_space_translation, *p)
            } else {
                *p
            };
            positions.extend_from_slice(&q);
            for axis in 0..3 {
                min[axis] = min[axis].min(q[axis]);
                max[axis] = max[axis].max(q[axis]);
            }
        }

        let mut attributes = Map::new();
        attributes.insert(
            "POSITION".to_string(),
            json!(buffer.add_accessor(
                &pack_f32(&positions),
                COMPONENT_FLOAT,
                "VEC3",
                mesh.positions.len(),
                Some(TARGET_ARRAY_BUFFER),
                Some(min.to_vec()),
                Some(max.to_vec()),
            )),
        );

        if mesh.normals.len() == mesh.positions.len() {
            let mut normals: Vec<f32> = Vec::with_capacity(mesh.normals.len() * 3);
            for n in &mesh.normals {
                normals.extend_from_slice(n);
            }
            attributes.insert(
                "NORMAL".to_string(),
                json!(buffer.add_accessor(
                    &pack_f32(&normals),
                    COMPONENT_FLOAT,
                    "VEC3",
                    mesh.normals.len(),
                    Some(TARGET_ARRAY_BUFFER),
                    None,
                    None,
                )),
            );
        }

        if mesh.has_uvs {
            let mut uvs: Vec<f32> = Vec::with_capacity(mesh.uvs.len() * 2);
            for uv in &mesh.uvs {
                uvs.extend_from_slice(uv);
            }
            attributes.insert(
                "TEXCOORD_0".to_string(),
                json!(buffer.add_accessor(
                    &pack_f32(&uvs),
                    COMPONENT_FLOAT,
                    "VEC2",
                    mesh.uvs.len(),
                    Some(TARGET_ARRAY_BUFFER),
                    None,
                    None,
                )),
            );
        }

        let mut skin_index: Option<usize> = None;
        if options.export_skins && mesh_has_exportable_weights(mesh) {
            let (joints_0, weights_0, set1, _max_inf) =
                mbn::build_joint_weight_sets(&mesh.raw_weights, mesh.node_hashes.len());

            weighted_vertex_count += mesh
                .raw_weights
                .iter()
                .filter(|w| w.iter().any(|&b| b != 0))
                .count();

            let joint_component = if mesh.node_hashes.len() <= 255 {
                COMPONENT_UNSIGNED_BYTE
            } else {
                COMPONENT_UNSIGNED_SHORT
            };

            let joints_payload = if joint_component == COMPONENT_UNSIGNED_BYTE {
                pack_u8(&joints_0)
            } else {
                pack_u16_from_u16(&joints_0)
            };
            attributes.insert(
                "JOINTS_0".to_string(),
                json!(buffer.add_accessor(
                    &joints_payload,
                    joint_component,
                    "VEC4",
                    mesh.positions.len(),
                    Some(TARGET_ARRAY_BUFFER),
                    None,
                    None,
                )),
            );
            attributes.insert(
                "WEIGHTS_0".to_string(),
                json!(buffer.add_accessor(
                    &pack_f32(&weights_0),
                    COMPONENT_FLOAT,
                    "VEC4",
                    mesh.positions.len(),
                    Some(TARGET_ARRAY_BUFFER),
                    None,
                    None,
                )),
            );

            if let Some((joints_1, weights_1)) = set1 {
                let joints_payload = if joint_component == COMPONENT_UNSIGNED_BYTE {
                    pack_u8(&joints_1)
                } else {
                    pack_u16_from_u16(&joints_1)
                };
                attributes.insert(
                    "JOINTS_1".to_string(),
                    json!(buffer.add_accessor(
                        &joints_payload,
                        joint_component,
                        "VEC4",
                        mesh.positions.len(),
                        Some(TARGET_ARRAY_BUFFER),
                        None,
                        None,
                    )),
                );
                attributes.insert(
                    "WEIGHTS_1".to_string(),
                    json!(buffer.add_accessor(
                        &pack_f32(&weights_1),
                        COMPONENT_FLOAT,
                        "VEC4",
                        mesh.positions.len(),
                        Some(TARGET_ARRAY_BUFFER),
                        None,
                        None,
                    )),
                );
            }

            let mut joint_nodes = Vec::with_capacity(mesh.node_hashes.len());
            for node_hash in &mesh.node_hashes {
                let index = ensure_joint(
                    node_hash,
                    &mut nodes_json,
                    &mut root_nodes,
                    &mut joint_node_by_hash,
                    &mut missing_mbn_joints,
                    export_skeleton,
                );
                joint_nodes.push(index);
            }

            let mut inverse_bind: Vec<f32> = Vec::with_capacity(mesh.node_hashes.len() * 16);
            for node_hash in &mesh.node_hashes {
                let ibm = export_skeleton.inverse_bind_matrix(node_hash);
                inverse_bind.extend_from_slice(&mbn::gltf_column_major(ibm));
            }
            let ibm_accessor = buffer.add_accessor(
                &pack_f32(&inverse_bind),
                COMPONENT_FLOAT,
                "MAT4",
                mesh.node_hashes.len(),
                None,
                None,
                None,
            );

            let missing_for_mesh: Vec<String> = mesh
                .node_hashes
                .iter()
                .filter(|h| !export_skeleton.bones.contains_key(&h.to_ascii_uppercase()))
                .cloned()
                .collect();

            let skin_name = format!(
                "{}_skin",
                sanitize(&mesh.name, &format!("mesh_{mesh_index}"))
            );
            skins_json.push(json!({
                "name": skin_name,
                "joints": joint_nodes,
                "inverseBindMatrices": ibm_accessor,
                "extras": {
                    "source": "XMPR node hashes",
                    "semantic": if scene.skeleton.is_empty() {
                        "identity bind skin for static weight preservation"
                    } else {
                        "MBN bind skin; mesh positions aligned to MBN head AABB"
                    },
                    "node_hashes": mesh.node_hashes,
                    "missing_mbn_node_hashes": missing_for_mesh,
                    "mesh_to_skeleton_scale": mesh_space_scale,
                    "mesh_to_skeleton_translation": mesh_space_translation,
                }
            }));
            skin_index = Some(skins_json.len() - 1);
        }

        // One glTF material per (material name, bound texture) pair.
        let texture_uri = entry
            .texture_index
            .and_then(|i| texture_uri_by_index.get(&i).cloned());
        let material_name = sanitize(&mesh.material, "default_material");
        let material_key = format!("{material_name}|{}", texture_uri.clone().unwrap_or_default());
        let material_index = *material_index_by_key
            .entry(material_key)
            .or_insert_with(|| {
                let mut pbr = Map::new();
                pbr.insert("baseColorFactor".to_string(), json!([1.0, 1.0, 1.0, 1.0]));
                pbr.insert("metallicFactor".to_string(), json!(0.0));
                pbr.insert("roughnessFactor".to_string(), json!(1.0));

                let mut transparent = false;
                if let Some(uri) = &texture_uri {
                    let image_index = *image_index_by_uri.entry(uri.clone()).or_insert_with(|| {
                        images_json.push(json!({ "uri": uri }));
                        images_json.len() - 1
                    });
                    let texture_index =
                        *texture_index_by_uri.entry(uri.clone()).or_insert_with(|| {
                            textures_json.push(json!({ "sampler": 0, "source": image_index }));
                            textures_json.len() - 1
                        });
                    pbr.insert(
                        "baseColorTexture".to_string(),
                        json!({ "index": texture_index }),
                    );
                    transparent = entry
                        .texture_index
                        .and_then(|i| scene.texture(i))
                        .map(|t| t.texture.has_transparency())
                        .unwrap_or(false);
                }

                let mut material = Map::new();
                material.insert("name".to_string(), json!(material_name));
                material.insert("pbrMetallicRoughness".to_string(), Value::Object(pbr));
                material.insert("doubleSided".to_string(), json!(true));
                if transparent {
                    material.insert("alphaMode".to_string(), json!("BLEND"));
                }
                material.insert(
                    "extras".to_string(),
                    json!({
                        "age_material_name": mesh.material,
                        "binding_confidence": entry.binding.label(),
                    }),
                );
                materials_json.push(Value::Object(material));
                materials_json.len() - 1
            });

        let mut primitive = Map::new();
        primitive.insert("attributes".to_string(), Value::Object(attributes));
        primitive.insert("material".to_string(), json!(material_index));
        primitive.insert(
            "mode".to_string(),
            json!(if mesh.faces.is_empty() {
                MODE_POINTS
            } else {
                MODE_TRIANGLES
            }),
        );

        if !mesh.faces.is_empty() {
            let indices: Vec<u32> = mesh.faces.iter().flat_map(|f| *f).collect();
            let max_index = indices.iter().copied().max().unwrap_or(0);
            let (payload, component) = if max_index <= u16::MAX as u32 {
                (pack_u16(&indices), COMPONENT_UNSIGNED_SHORT)
            } else {
                (pack_u32(&indices), COMPONENT_UNSIGNED_INT)
            };
            primitive.insert(
                "indices".to_string(),
                json!(buffer.add_accessor(
                    &payload,
                    component,
                    "SCALAR",
                    indices.len(),
                    Some(TARGET_ELEMENT_ARRAY_BUFFER),
                    None,
                    None,
                )),
            );
            total_faces += mesh.faces.len();
        }
        total_vertices += mesh.positions.len();

        let node_name = sanitize(&mesh.name, &format!("mesh_{mesh_index}"));
        meshes_json.push(json!({
            "name": node_name,
            "primitives": [Value::Object(primitive)],
            "extras": {
                "source_member": mesh.source,
                "age_mesh_name": mesh.name,
                "position_format": mesh.position_format.label(),
                "uv_format": mesh.uv_format.label(),
                "node_hashes": mesh.node_hashes,
                "skinned": skin_index.is_some(),
            }
        }));

        let mut mesh_node = Map::new();
        mesh_node.insert("name".to_string(), json!(node_name));
        mesh_node.insert("mesh".to_string(), json!(meshes_json.len() - 1));
        if let Some(skin) = skin_index {
            mesh_node.insert("skin".to_string(), json!(skin));
        }
        mesh_node.insert(
            "extras".to_string(),
            json!({ "source_member": mesh.source }),
        );
        nodes_json.push(Value::Object(mesh_node));
        root_nodes.push(nodes_json.len() - 1);
    }

    let mut gltf = Map::new();
    gltf.insert(
        "asset".to_string(),
        json!({
            "version": "2.0",
            "generator": "Gundam AGE PSP age_viewer",
            "extras": {
                "source_archive": scene.archive_name,
                "note": "Static bind-pose export; animation data is not executed.",
                "joint_nodes": "MBN bind nodes when available; missing hashes use identity.",
                "mbn_bone_count": scene.skeleton.bone_count(),
                "skin_count": skins_json.len(),
                "mesh_to_skeleton_scale": mesh_space_scale,
                "mesh_to_skeleton_translation": mesh_space_translation,
            }
        }),
    );
    gltf.insert("scene".to_string(), json!(0));
    gltf.insert(
        "scenes".to_string(),
        json!([{ "name": scene.archive_name, "nodes": root_nodes }]),
    );
    gltf.insert("nodes".to_string(), Value::Array(nodes_json));
    gltf.insert("meshes".to_string(), Value::Array(meshes_json.clone()));
    gltf.insert("materials".to_string(), Value::Array(materials_json.clone()));
    if !skins_json.is_empty() {
        gltf.insert("skins".to_string(), Value::Array(skins_json.clone()));
    }
    gltf.insert(
        "buffers".to_string(),
        json!([{
            "uri": bin_path.file_name().and_then(|n| n.to_str()).unwrap_or("model.bin"),
            "byteLength": buffer.buffer.len(),
        }]),
    );
    gltf.insert("bufferViews".to_string(), Value::Array(buffer.views.clone()));
    gltf.insert(
        "accessors".to_string(),
        Value::Array(buffer.accessors.clone()),
    );
    if !images_json.is_empty() {
        gltf.insert(
            "samplers".to_string(),
            json!([{ "magFilter": 9729, "minFilter": 9729, "wrapS": 10497, "wrapT": 10497 }]),
        );
        gltf.insert("images".to_string(), Value::Array(images_json.clone()));
        gltf.insert("textures".to_string(), Value::Array(textures_json.clone()));
    }

    std::fs::write(&bin_path, &buffer.buffer)?;
    std::fs::write(&gltf_path, serde_json::to_vec_pretty(&Value::Object(gltf))?)?;

    Ok(ExportSummary {
        gltf_path,
        bin_path,
        mesh_count: selected.len(),
        vertex_count: total_vertices,
        face_count: total_faces,
        material_count: materials_json.len(),
        texture_count: textures_json.len(),
        skipped_meshes: scene.meshes.len() - selected.len(),
        skin_count: skins_json.len(),
        joint_node_count: joint_node_by_hash.len(),
        weighted_vertex_count,
        mbn_bone_count: scene.skeleton.bone_count(),
        missing_mbn_joint_count: missing_mbn_joints.len(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sanitize_replaces_unsafe_characters() {
        assert_eq!(sanitize("DefaultLib.ms001 01", "x"), "DefaultLib.ms001_01");
        assert_eq!(sanitize("  ", "fallback"), "fallback");
        assert_eq!(sanitize("a/b\\c", "x"), "a_b_c");
    }

    #[test]
    fn pack_helpers_are_little_endian() {
        assert_eq!(pack_u16(&[1]), vec![1, 0]);
        assert_eq!(pack_u32(&[1]), vec![1, 0, 0, 0]);
        assert_eq!(pack_f32(&[1.0]), 1.0f32.to_le_bytes().to_vec());
        assert_eq!(pack_u8(&[1, 2, 255]), vec![1, 2, 255]);
    }

    #[test]
    fn buffer_views_stay_four_byte_aligned() {
        let mut builder = BufferBuilder::new();
        builder.add_view(&[1, 2, 3], None);
        let second = builder.add_view(&[4, 5, 6, 7], None);
        let offset = builder.views[second]["byteOffset"].as_u64().unwrap();
        assert_eq!(offset % 4, 0);
    }

    #[test]
    fn default_options_export_skins() {
        assert!(ExportOptions::default().export_skins);
    }
}
