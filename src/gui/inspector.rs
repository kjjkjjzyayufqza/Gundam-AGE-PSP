//! Right-hand inspector: objective archive / mesh / texture facts.
//!
//! Layout is a plain property grid plus compact lists. No decorative chrome —
//! values are the product, not the frame around them.

use super::widgets;
use crate::imgp::Texture;
use crate::scene::Scene;
use crate::theme;
use eframe::egui;

/// Side length of a texture thumbnail, in points.
const THUMBNAIL: f32 = 48.0;

/// Per-archive cache of egui texture handles for the thumbnail strip.
#[derive(Default)]
pub struct ThumbnailCache {
    /// Scene generation the handles belong to; 0 means "nothing cached".
    generation: u64,
    handles: Vec<Option<egui::TextureHandle>>,
}

impl ThumbnailCache {
    /// Point the cache at a scene generation, dropping stale handles.
    /// Returns `true` when the cache was reset.
    pub fn sync(&mut self, generation: u64, texture_count: usize) -> bool {
        if self.generation == generation && self.handles.len() == texture_count {
            return false;
        }
        self.generation = generation;
        self.handles.clear();
        self.handles.resize_with(texture_count, || None);
        true
    }

    pub fn clear(&mut self) {
        self.generation = 0;
        self.handles.clear();
    }

    /// Number of thumbnails currently uploaded.
    #[cfg(test)]
    pub fn uploaded(&self) -> usize {
        self.handles.iter().filter(|slot| slot.is_some()).count()
    }

    /// Upload on first use, then hand back the cached handle.
    pub fn handle(
        &mut self,
        ctx: &egui::Context,
        index: usize,
        member: &str,
        texture: &Texture,
    ) -> Option<egui::TextureHandle> {
        let slot = self.handles.get_mut(index)?;
        if slot.is_none() {
            let size = [texture.width.max(1) as usize, texture.height.max(1) as usize];
            let mut rgba = texture.rgba_bytes();
            rgba.resize(size[0] * size[1] * 4, 0);
            let image = egui::ColorImage::from_rgba_unmultiplied(size, &rgba);
            *slot = Some(ctx.load_texture(
                format!("age_thumb_{}_{member}", self.generation),
                image,
                egui::TextureOptions::NEAREST,
            ));
        }
        slot.clone()
    }
}

/// Draw the inspector. Returns the texture index the user asked to enlarge.
pub fn show(
    ui: &mut egui::Ui,
    ctx: &egui::Context,
    scene: &mut Scene,
    generation: u64,
    thumbs: &mut ThumbnailCache,
) -> Option<usize> {
    thumbs.sync(generation, scene.textures.len());
    let mut open_texture = None;

    egui::ScrollArea::vertical()
        .auto_shrink([false, false])
        .show(ui, |ui| {
            archive_summary(ui, scene);
            widgets::failure_list(ui, "Mesh decode failures", &scene.mesh_failures);
            widgets::failure_list(ui, "Texture decode failures", &scene.texture_failures);

            ui.add_space(8.0);
            mesh_list(ui, scene);

            ui.add_space(8.0);
            open_texture = texture_list(ui, ctx, scene, thumbs);
        });

    open_texture
}

fn archive_summary(ui: &mut egui::Ui, scene: &Scene) {
    widgets::section_header(ui, "Archive");

    egui::Grid::new("archive_summary")
        .num_columns(2)
        .spacing([12.0, 3.0])
        .striped(true)
        .show(ui, |ui| {
            widgets::property(ui, "File", &scene.archive_name);
            if let Some(path) = scene.archive_path.as_ref() {
                widgets::property(ui, "Path", &path.display().to_string());
            }
            widgets::property(ui, "Size", &theme::format_bytes(scene.archive_size));
            widgets::property(ui, "Members", &theme::format_count(scene.member_count));
            widgets::property(ui, "Meshes", &theme::format_count(scene.meshes.len()));
            widgets::property(ui, "Textures", &theme::format_count(scene.textures.len()));
            widgets::property(ui, "Vertices", &theme::format_count(scene.total_vertices()));
            widgets::property(
                ui,
                "Faces",
                &format!(
                    "{} ({} visible)",
                    theme::format_count(scene.total_faces()),
                    theme::format_count(scene.visible_faces())
                ),
            );
            widgets::property(
                ui,
                "Skinned",
                if scene.is_skinned() { "yes" } else { "no" },
            );
            widgets::property(
                ui,
                "Material binds",
                &format!(
                    "{}/{}",
                    theme::format_count(scene.bindings.resolved_count()),
                    theme::format_count(scene.bindings.materials.len())
                ),
            );
            if let Some(member) = &scene.bindings.res_member {
                let method = scene.bindings.res_method.as_deref().unwrap_or("unknown");
                widgets::property(ui, "RES", &format!("{member} ({method})"));
            }
        });

    if !scene.member_extensions.is_empty() {
        ui.add_space(4.0);
        widgets::section_header(ui, "Member types");
        egui::Grid::new("member_types")
            .num_columns(2)
            .spacing([12.0, 2.0])
            .striped(true)
            .show(ui, |ui| {
                for (ext, count) in &scene.member_extensions {
                    ui.label(theme::mono(ext));
                    ui.label(theme::mono(theme::format_count(*count)));
                    ui.end_row();
                }
            });
    }
}

fn mesh_list(ui: &mut egui::Ui, scene: &mut Scene) {
    widgets::section_header(ui, "Meshes");

    ui.horizontal(|ui| {
        if ui.button("Show all").clicked() {
            scene.set_all_visible(true);
        }
        if ui.button("Hide all").clicked() {
            scene.set_all_visible(false);
        }
        ui.label(theme::caption(format!(
            "{} total",
            theme::format_count(scene.meshes.len())
        )));
    });

    if scene.meshes.is_empty() {
        widgets::empty_state(
            ui,
            "No models in this archive.",
            "May contain only textures, animation or layout data.",
        );
        return;
    }

    ui.add_space(2.0);
    for index in 0..scene.meshes.len() {
        let (name, material, source, vertices, faces, position_format, uv_format, warning, dropped) = {
            let entry = &scene.meshes[index];
            (
                entry.mesh.name.clone(),
                entry.mesh.material.clone(),
                entry.mesh.source.clone(),
                entry.mesh.vertex_count(),
                entry.mesh.face_count(),
                entry.mesh.position_format.label().to_string(),
                entry.mesh.uv_format.label().to_string(),
                entry.mesh.warnings.first().cloned(),
                entry.mesh.dropped_degenerate_faces,
            )
        };
        let texture_member = scene.meshes[index]
            .texture_index
            .and_then(|i| scene.texture(i))
            .map(|entry| entry.member.clone());
        let confidence = scene.meshes[index].binding.label();

        ui.push_id(index, |ui| {
            ui.horizontal(|ui| {
                ui.checkbox(&mut scene.meshes[index].visible, "");
                widgets::truncating_label(
                    ui,
                    theme::mono_strong(format!("{source}  {name}")),
                    &format!("{source}  {name}"),
                );
            });

            // Indent detail lines without using Grid (egui forbids add_space in grids).
            ui.indent("mesh_detail", |ui| {
                ui.label(theme::mono(format!(
                    "v={}  f={}  pos={}  uv={}",
                    theme::format_count(vertices),
                    theme::format_count(faces),
                    position_format,
                    uv_format
                )));
                let bind_line = match &texture_member {
                    Some(member) => format!("{material} -> {member}  [{confidence}]"),
                    None => format!("{material}  [{confidence}]"),
                };
                widgets::truncating_label(ui, theme::mono(&bind_line), &bind_line);
                if dropped > 0 {
                    ui.label(theme::caption(format!(
                        "degenerate faces dropped: {}",
                        theme::format_count(dropped)
                    )));
                }
                if let Some(warning) = warning {
                    let response = ui.add(
                        egui::Label::new(
                            egui::RichText::new(&warning)
                                .small()
                                .color(theme::STATUS_WARN),
                        )
                        .truncate(),
                    );
                    response.on_hover_text(&warning);
                }
            });
            ui.add_space(4.0);
        });
    }
}

fn texture_list(
    ui: &mut egui::Ui,
    ctx: &egui::Context,
    scene: &Scene,
    thumbs: &mut ThumbnailCache,
) -> Option<usize> {
    widgets::section_header(ui, "Textures");

    if scene.textures.is_empty() {
        widgets::empty_state(ui, "No textures in this archive.", "");
        return None;
    }

    let mut clicked = None;
    for (index, entry) in scene.textures.iter().enumerate() {
        let handle = thumbs.handle(ctx, index, &entry.member, &entry.texture);
        ui.horizontal(|ui| {
            let (rect, response) = ui.allocate_exact_size(
                egui::vec2(THUMBNAIL, THUMBNAIL),
                egui::Sense::click(),
            );
            if ui.is_rect_visible(rect) {
                let painter = ui.painter();
                widgets::paint_checkerboard(painter, rect, 8.0);
                if let Some(handle) = &handle {
                    painter.image(
                        handle.id(),
                        fit_rect(rect, entry.texture.width, entry.texture.height),
                        egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
                        egui::Color32::WHITE,
                    );
                }
                painter.rect_stroke(
                    rect,
                    0.0,
                    ui.visuals().widgets.noninteractive.bg_stroke,
                    egui::StrokeKind::Inside,
                );
            }
            if response.clicked() {
                clicked = Some(index);
            }

            ui.vertical(|ui| {
                widgets::truncating_label(ui, theme::mono_strong(&entry.member), &entry.member);
                ui.label(theme::mono(describe_texture(&entry.texture)));
                if ui.small_button("Open").clicked() {
                    clicked = Some(index);
                }
            });
        });
        ui.add_space(4.0);
    }
    clicked
}

/// `"128 x 128   8 bpp   alpha"`.
pub fn describe_texture(texture: &Texture) -> String {
    let alpha = if texture.has_transparency() {
        "alpha"
    } else {
        "opaque"
    };
    format!(
        "{} x {}   {} bpp   {alpha}",
        texture.width, texture.height, texture.bit_depth
    )
}

/// Largest rect inside `bounds` with the texture's aspect ratio, centred.
pub fn fit_rect(bounds: egui::Rect, width: u32, height: u32) -> egui::Rect {
    let w = width.max(1) as f32;
    let h = height.max(1) as f32;
    let scale = (bounds.width() / w).min(bounds.height() / h);
    let size = egui::vec2(w * scale, h * scale);
    egui::Rect::from_center_size(bounds.center(), size)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn syncing_to_a_new_generation_drops_cached_handles() {
        let mut cache = ThumbnailCache::default();

        assert!(cache.sync(1, 3));
        assert_eq!(cache.handles.len(), 3);
        assert_eq!(cache.uploaded(), 0);

        assert!(!cache.sync(1, 3));

        assert!(cache.sync(2, 1));
        assert_eq!(cache.handles.len(), 1);

        cache.clear();
        assert!(cache.handles.is_empty());
        assert!(cache.sync(2, 1), "clearing forces the next sync to rebuild");
    }

    #[test]
    fn syncing_an_archive_without_textures_is_stable() {
        let mut cache = ThumbnailCache::default();
        assert!(cache.sync(4, 0));
        assert!(!cache.sync(4, 0));
        assert_eq!(cache.uploaded(), 0);
    }

    #[test]
    fn fit_rect_preserves_aspect_and_stays_inside_bounds() {
        let bounds = egui::Rect::from_min_size(egui::pos2(0.0, 0.0), egui::vec2(100.0, 50.0));

        let wide = fit_rect(bounds, 200, 50);
        assert!((wide.width() - 100.0).abs() < 0.01);
        assert!((wide.height() - 25.0).abs() < 0.01);
        assert!(bounds.contains_rect(wide));

        let tall = fit_rect(bounds, 50, 200);
        assert!((tall.height() - 50.0).abs() < 0.01);
        assert!((tall.width() - 12.5).abs() < 0.01);
        assert!(bounds.contains_rect(tall));

        let degenerate = fit_rect(bounds, 0, 0);
        assert!(degenerate.width().is_finite() && degenerate.height().is_finite());
    }
}
