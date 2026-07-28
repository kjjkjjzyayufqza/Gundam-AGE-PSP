//! End-to-end checks against a real unpacked PSP resource tree.
//!
//! These are opt-in because they need game data, which is not in this repo.
//! Point the tests at an unpacked resource root either way:
//!
//! ```text
//! cargo test --release --test real_resource_tree -- --nocapture
//! ```
//!
//! The root is read from the `AGE_PSP_ROOT` environment variable, or from a
//! UTF-8 file named `age_psp_root.txt` in the crate directory. The file form
//! exists because Windows `cmd.exe` mangles non-ASCII paths passed as arguments,
//! and real resource roots often sit under non-ASCII directory names.
//!
//! With neither present, every test reports skipped and passes.

use age_viewer::{gltf, imgp, index, scene, xmpr};
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;

/// Resource root from the environment, else from `age_psp_root.txt`.
fn resource_root() -> Option<PathBuf> {
    if let Some(value) = std::env::var_os("AGE_PSP_ROOT") {
        let root = PathBuf::from(value);
        if root.is_dir() {
            return Some(root);
        }
    }

    let config = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("age_psp_root.txt");
    let text = std::fs::read_to_string(config).ok()?;
    let line = text
        .lines()
        .map(str::trim)
        .find(|l| !l.is_empty() && !l.starts_with('#'))?;
    let root = PathBuf::from(line);
    root.is_dir().then_some(root)
}

macro_rules! root_or_skip {
    () => {
        match resource_root() {
            Some(root) => root,
            None => {
                eprintln!("skipped: AGE_PSP_ROOT is not set to a directory");
                return;
            }
        }
    };
}

#[test]
fn scanning_the_tree_finds_archives_with_models_and_textures() {
    let root = root_or_skip!();
    let cancel = AtomicBool::new(false);
    let mut last = index::ScanProgress::default();
    let records = index::scan_root(&root, &cancel, &mut |p| last = p);

    assert!(
        records.len() > 1000,
        "expected a few thousand archives, found {}",
        records.len()
    );
    assert!(
        records.iter().any(|r| r.has_models()),
        "no archive reported any .prm models"
    );
    assert!(
        records.iter().any(|r| r.has_textures()),
        "no archive reported any .xi textures"
    );

    let with_models = records.iter().filter(|r| r.has_models()).count();
    let with_textures = records.iter().filter(|r| r.has_textures()).count();
    eprintln!(
        "archives={} with_models={} with_textures={} scan_errors={}",
        records.len(),
        with_models,
        with_textures,
        last.errors
    );

    // Search must be able to narrow the tree down to one suit.
    let filter = index::SearchFilter {
        query: "ms001000".to_string(),
        only_with_models: true,
        ..Default::default()
    };
    let matches = index::filter_records(&records, &filter);
    assert!(
        !matches.is_empty(),
        "search for ms001000 with models returned nothing"
    );
}

#[test]
fn character_archive_decodes_meshes_textures_and_bindings() {
    let root = root_or_skip!();
    let archive = root.join("chr").join("ms001000").join("ms001000_p000.xc");
    if !archive.is_file() {
        eprintln!("skipped: {} is absent", archive.display());
        return;
    }

    let scene = scene::Scene::load(
        &archive,
        xmpr::Triangulation::Strip,
        imgp::PixelLayout::PspSwizzled,
    )
    .expect("character archive should decode");

    // Ground truth captured from the validated Python tools.
    assert_eq!(scene.member_count, 80);
    assert_eq!(scene.meshes.len(), 6);
    assert_eq!(scene.textures.len(), 5);
    assert!(scene.mesh_failures.is_empty(), "{:?}", scene.mesh_failures);
    assert!(
        scene.texture_failures.is_empty(),
        "{:?}",
        scene.texture_failures
    );

    // Every mesh must resolve to a texture through the RES.bin/TXP chain.
    for mesh in &scene.meshes {
        assert!(
            mesh.texture_index.is_some(),
            "mesh {} ({}) has no bound texture",
            mesh.mesh.source,
            mesh.mesh.material
        );
    }

    let first = &scene.meshes[0].mesh;
    assert_eq!(first.stride, 18);
    assert_eq!(first.position_format, xmpr::PositionFormat::S16Norm);
    assert_eq!(first.uv_format, xmpr::UvFormat::U16Norm);
    assert!(first.has_uvs);
    assert!(first.is_skinned(), "character meshes carry slot-7 weights");
    assert_eq!(first.vertex_count(), 1002);

    // UV orientation. Game UVs are image-space (origin top-left), which glTF
    // TEXCOORD_0 and wgpu sampling both use directly, so they must NOT be
    // V-flipped. The Python OBJ exporter reports v = 0.358978... for this
    // vertex because OBJ measures V from the bottom, i.e. 1.0 - 0.641021...
    let uv = first.uvs[0];
    assert!(
        (uv[0] - 0.846_282_9).abs() < 1e-5,
        "unexpected U {}, expected the raw stored value",
        uv[0]
    );
    assert!(
        (uv[1] - 0.641_021_7).abs() < 1e-5,
        "unexpected V {}; a value near 0.3590 means the V flip regressed and \
         every model will render upside down",
        uv[1]
    );

    // Textures vary in size within one archive; 004.xi is half-height here.
    // Ground truth from the validated Python decoder.
    let dimensions: Vec<(u32, u32)> = scene
        .textures
        .iter()
        .map(|t| (t.texture.width, t.texture.height))
        .collect();
    assert_eq!(
        dimensions,
        vec![(128, 128), (128, 128), (128, 128), (128, 128), (64, 128)],
        "texture dimensions must match the Python ground truth"
    );

    for texture in &scene.textures {
        assert_eq!(texture.texture.bit_depth, 4);
        assert_eq!(
            texture.texture.pixels.len(),
            texture.texture.width as usize * texture.texture.height as usize,
            "decoded pixel count must match the declared size for {}",
            texture.member
        );
    }

    eprintln!(
        "{}: {} meshes, {} vertices, {} faces, {} textures, {} materials resolved",
        scene.archive_name,
        scene.meshes.len(),
        scene.total_vertices(),
        scene.total_faces(),
        scene.textures.len(),
        scene.bindings.resolved_count()
    );
}

#[test]
fn map_archive_decodes_float_positions() {
    let root = root_or_skip!();
    let archive = root.join("map").join("e1101.xc");
    if !archive.is_file() {
        eprintln!("skipped: {} is absent", archive.display());
        return;
    }

    let scene = scene::Scene::load(
        &archive,
        xmpr::Triangulation::Strip,
        imgp::PixelLayout::PspSwizzled,
    )
    .expect("map archive should decode");

    assert_eq!(scene.member_count, 107);
    assert_eq!(scene.meshes.len(), 20);
    assert_eq!(scene.textures.len(), 9);

    let first = &scene.meshes[0].mesh;
    assert_eq!(first.stride, 24);
    assert_eq!(first.position_format, xmpr::PositionFormat::Float32x3);
    assert_eq!(first.uv_format, xmpr::UvFormat::Float32x2);
    assert!(
        !first.is_skinned(),
        "map meshes are static and must not report weights"
    );
    // Maps live in world units, unlike the unit-scale character meshes.
    assert!(
        first.bounds_max[0] > 10.0,
        "expected world-scale map coordinates, got {:?}",
        first.bounds_max
    );
}

#[test]
fn exporting_a_character_archive_writes_a_valid_gltf() {
    let root = root_or_skip!();
    let archive = root.join("chr").join("ms001000").join("ms001000_p000.xc");
    if !archive.is_file() {
        eprintln!("skipped: {} is absent", archive.display());
        return;
    }

    let scene = scene::Scene::load(
        &archive,
        xmpr::Triangulation::Strip,
        imgp::PixelLayout::PspSwizzled,
    )
    .expect("archive should decode");

    let out_dir = std::env::temp_dir().join("age_viewer_export_check");
    let _ = std::fs::remove_dir_all(&out_dir);

    let summary = gltf::export_scene(
        &scene,
        &out_dir,
        "ms001000_p000",
        gltf::ExportOptions::default(),
    )
    .expect("export should succeed");

    assert_eq!(summary.mesh_count, 6);
    assert!(summary.vertex_count > 0 && summary.face_count > 0);
    assert!(summary.texture_count > 0, "textures should be referenced");
    assert!(summary.gltf_path.is_file());
    assert!(summary.bin_path.is_file());

    // Character packages carry MBN bones and weighted meshes.
    assert!(
        scene.bone_count() > 0,
        "ms001000 should load MBN bones, got 0"
    );
    assert!(
        scene.is_skinned(),
        "ms001000 should decode as skinned (node hashes + weights)"
    );
    assert!(
        summary.skin_count > 0,
        "export must emit skins for a skinned character (got {})",
        summary.skin_count
    );
    assert!(
        summary.joint_node_count > 0,
        "export must emit joint nodes"
    );

    // The glTF must be parseable and internally consistent.
    let text = std::fs::read_to_string(&summary.gltf_path).expect("read gltf");
    let doc: serde_json::Value = serde_json::from_str(&text).expect("gltf must be valid JSON");
    assert_eq!(doc["asset"]["version"], "2.0");

    let accessors = doc["accessors"].as_array().expect("accessors array");
    let views = doc["bufferViews"].as_array().expect("bufferViews array");
    let nodes = doc["nodes"].as_array().expect("nodes array");
    let skins = doc["skins"]
        .as_array()
        .expect("skins array must be present for skinned character export");
    assert_eq!(skins.len(), summary.skin_count);

    let declared = doc["buffers"][0]["byteLength"].as_u64().expect("byteLength");
    let actual = std::fs::metadata(&summary.bin_path).expect("bin metadata").len();
    assert_eq!(
        declared, actual,
        "buffer byteLength must match the .bin size on disk"
    );

    // Every buffer view must stay inside the buffer.
    for view in views {
        let offset = view["byteOffset"].as_u64().unwrap_or(0);
        let length = view["byteLength"].as_u64().expect("view byteLength");
        assert!(
            offset + length <= declared,
            "buffer view {offset}+{length} exceeds buffer {declared}"
        );
    }

    // Every mesh primitive must have positions and reference a real material.
    let material_count = doc["materials"].as_array().map(|m| m.len()).unwrap_or(0);
    let mut skinned_primitives = 0usize;
    for mesh in doc["meshes"].as_array().expect("meshes array") {
        for primitive in mesh["primitives"].as_array().expect("primitives array") {
            let position = primitive["attributes"]["POSITION"]
                .as_u64()
                .expect("POSITION accessor");
            assert!((position as usize) < accessors.len());
            let material = primitive["material"].as_u64().expect("material index");
            assert!((material as usize) < material_count);
            if primitive["attributes"].get("JOINTS_0").is_some() {
                assert!(
                    primitive["attributes"].get("WEIGHTS_0").is_some(),
                    "JOINTS_0 requires WEIGHTS_0"
                );
                skinned_primitives += 1;
            }
        }
    }
    assert!(
        skinned_primitives > 0,
        "at least one primitive must carry JOINTS_0/WEIGHTS_0"
    );

    // Skin joints must reference live nodes and inverse-bind MAT4 accessors.
    for skin in skins {
        let joints = skin["joints"].as_array().expect("skin.joints");
        assert!(!joints.is_empty(), "skin must list joints");
        for joint in joints {
            let index = joint.as_u64().expect("joint index") as usize;
            assert!(index < nodes.len(), "joint {index} out of range");
        }
        let ibm = skin["inverseBindMatrices"]
            .as_u64()
            .expect("inverseBindMatrices") as usize;
        assert!(ibm < accessors.len());
        assert_eq!(accessors[ibm]["type"], "MAT4");
        assert_eq!(
            accessors[ibm]["count"].as_u64().unwrap(),
            joints.len() as u64
        );
        // Mesh is lifted into skeleton space using MBN head bounds (file data).
        let mesh_scale = skin["extras"]["mesh_to_skeleton_scale"]
            .as_f64()
            .expect("mesh_to_skeleton_scale");
        assert!(
            mesh_scale > 1.0,
            "character s16 mesh should scale up into MBN head space, got {mesh_scale}"
        );
    }

    // Mesh positions should now live in skeleton/head units (not unit-cube).
    let mut mesh_max_r = 0.0f64;
    for mesh in doc["meshes"].as_array().expect("meshes") {
        for prim in mesh["primitives"].as_array().expect("prims") {
            let pos_acc = prim["attributes"]["POSITION"].as_u64().unwrap() as usize;
            let max = accessors[pos_acc]["max"].as_array().expect("pos max");
            let min = accessors[pos_acc]["min"].as_array().expect("pos min");
            for i in 0..3 {
                let a = max[i].as_f64().unwrap_or(0.0).abs();
                let b = min[i].as_f64().unwrap_or(0.0).abs();
                mesh_max_r = mesh_max_r.max(a).max(b);
            }
        }
    }
    assert!(
        mesh_max_r > 5.0,
        "exported mesh should be in MBN/head units after align, max |coord|={mesh_max_r}"
    );

    // Mesh nodes that declare a skin index must be in range.
    for node in nodes {
        if let Some(skin) = node.get("skin") {
            let index = skin.as_u64().expect("skin index") as usize;
            assert!(index < skins.len());
        }
    }

    // Referenced texture images must exist next to the glTF.
    for image in doc["images"].as_array().map(|v| v.as_slice()).unwrap_or(&[]) {
        let uri = image["uri"].as_str().expect("image uri");
        let path = out_dir.join(uri);
        assert!(path.is_file(), "missing exported texture {uri}");
    }

    eprintln!(
        "exported {} meshes / {} verts / {} skins / {} joints / {} MBN bones / {} textures -> {}",
        summary.mesh_count,
        summary.vertex_count,
        summary.skin_count,
        summary.joint_node_count,
        summary.mbn_bone_count,
        summary.texture_count,
        summary.gltf_path.display()
    );

    let _ = std::fs::remove_dir_all(&out_dir);
}

/// Broad decode sweep: catches regressions that only show up on unusual archives.
#[test]
fn a_sample_across_categories_decodes_without_panicking() {
    let root = root_or_skip!();
    let cancel = AtomicBool::new(false);
    let records = index::scan_root(&root, &cancel, &mut |_| {});

    let mut checked = 0usize;
    let mut failures = Vec::new();

    for category in index::categories(&records) {
        let sample: Vec<&index::ArchiveRecord> = records
            .iter()
            .filter(|r| r.category == category && r.has_models())
            .take(12)
            .collect();

        for record in sample {
            match scene::Scene::load(
                &record.path,
                xmpr::Triangulation::Strip,
                imgp::PixelLayout::PspSwizzled,
            ) {
                Ok(scene) => {
                    checked += 1;
                    // A model archive that decodes must produce geometry.
                    if scene.meshes.iter().all(|m| m.mesh.positions.is_empty()) {
                        failures.push(format!("{}: no geometry decoded", record.relative));
                    }
                }
                Err(e) => failures.push(format!("{}: {e}", record.relative)),
            }
        }
    }

    eprintln!("decoded {checked} archives across categories, {} problems", failures.len());
    for problem in failures.iter().take(20) {
        eprintln!("  {problem}");
    }
    assert!(checked > 0, "no model archives were sampled");
    assert!(
        failures.is_empty(),
        "{} archives failed to decode",
        failures.len()
    );
}


/// Per-mesh parity against the validated Python decoders in `tools/`.
///
/// These counts come from `tools/research/_age_viewer_parity.py` reading
/// `outputs/manifests/age_viewer_groundtruth.json`. They pin the Rust port to
/// the Python results, so a regression in Level-5 decoding, attribute layout
/// handling or triangle-strip degenerate-face culling fails loudly.
#[test]
fn per_mesh_counts_match_the_python_decoder() {
    let root = root_or_skip!();

    // (archive, [(member, vertices, faces)])
    let expected: &[(PathBuf, &[(&str, usize, usize)])] = &[
        (
            root.join("chr").join("ms001000").join("ms001000_p000.xc"),
            &[
                ("000.prm", 1002, 300),
                ("001.prm", 252, 114),
                ("002.prm", 647, 274),
                ("003.prm", 658, 225),
                ("004.prm", 756, 264),
                ("005.prm", 689, 184),
            ],
        ),
        (
            root.join("chr").join("ms008000").join("ms008000_p000.xc"),
            &[
                ("000.prm", 960, 312),
                ("001.prm", 822, 288),
                ("002.prm", 668, 292),
                ("003.prm", 869, 324),
                ("004.prm", 659, 232),
                ("005.prm", 698, 234),
                ("006.prm", 281, 124),
                ("007.prm", 1783, 600),
                ("008.prm", 1729, 596),
                ("009.prm", 912, 324),
                ("010.prm", 671, 292),
                ("011.prm", 421, 120),
            ],
        ),
        (
            root.join("map").join("e1101.xc"),
            &[
                ("000.prm", 42, 30),
                ("001.prm", 165, 42),
                ("002.prm", 126, 84),
                ("003.prm", 36, 24),
                ("004.prm", 58, 24),
                ("005.prm", 69, 24),
                ("006.prm", 248, 160),
                ("007.prm", 69, 36),
                ("008.prm", 69, 36),
                ("009.prm", 384, 120),
                ("010.prm", 68, 48),
                ("011.prm", 67, 48),
                ("012.prm", 325, 184),
                ("013.prm", 189, 48),
                ("014.prm", 93, 40),
                ("015.prm", 5305, 1836),
                ("016.prm", 1510, 672),
                ("017.prm", 2736, 1368),
                ("018.prm", 4888, 2544),
                // Exercises the float32x4_xyz position path with no UVs.
                ("019.prm", 23, 14),
            ],
        ),
    ];

    for (archive, meshes) in expected {
        if !archive.is_file() {
            eprintln!("skipped: {} is absent", archive.display());
            continue;
        }
        let scene = scene::Scene::load(
            archive,
            xmpr::Triangulation::Strip,
            imgp::PixelLayout::PspSwizzled,
        )
        .unwrap_or_else(|e| panic!("{} should decode: {e}", archive.display()));

        assert!(
            scene.mesh_failures.is_empty(),
            "{}: {:?}",
            archive.display(),
            scene.mesh_failures
        );
        assert_eq!(
            scene.meshes.len(),
            meshes.len(),
            "{}: mesh count",
            archive.display()
        );

        for (index, (member, vertices, faces)) in meshes.iter().enumerate() {
            let actual = &scene.meshes[index].mesh;
            assert_eq!(&actual.source, member, "{}: member order", archive.display());
            assert_eq!(
                actual.vertex_count(),
                *vertices,
                "{} {member}: vertex count",
                archive.display()
            );
            assert_eq!(
                actual.face_count(),
                *faces,
                "{} {member}: face count after degenerate culling",
                archive.display()
            );
        }

        eprintln!(
            "{}: {} meshes match Python ({} vertices, {} faces)",
            scene.archive_name,
            scene.meshes.len(),
            scene.total_vertices(),
            scene.total_faces()
        );
    }
}
