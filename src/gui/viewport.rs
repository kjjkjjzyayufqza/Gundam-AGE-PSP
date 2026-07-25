//! Central viewport chrome: the toolbar above the 3D view and its readout line.
//!
//! The wgpu draw itself lives in the app so it can hold the device, queue and
//! renderer handles; this module only owns the controls and the text.

use crate::gpu_renderer::{GpuRenderStats, GpuScene};
use crate::render::PreviewState;
use crate::theme;
use crate::xmpr::Triangulation;
use eframe::egui;

/// What the toolbar asked the app to do this frame.
#[derive(Default)]
pub struct ToolbarAction {
    pub reset_view: bool,
    /// Set when the user picked a different triangulation, which reloads the scene.
    pub triangulation: Option<Triangulation>,
    /// Set when a view toggle changed, so the app can persist it.
    pub toggles_changed: bool,
}

const TRIANGULATIONS: [Triangulation; 3] = [
    Triangulation::Strip,
    Triangulation::List,
    Triangulation::Points,
];

pub fn toolbar(
    ui: &mut egui::Ui,
    preview: &mut PreviewState,
    triangulation: Triangulation,
    has_scene: bool,
) -> ToolbarAction {
    let mut action = ToolbarAction::default();

    ui.horizontal(|ui| {
        action.toggles_changed |= ui
            .checkbox(&mut preview.show_textures, "Textures")
            .changed();
        action.toggles_changed |= ui
            .checkbox(&mut preview.show_wireframe, "Wireframe")
            .changed();
        action.toggles_changed |= ui.checkbox(&mut preview.show_grid, "Grid").changed();
        action.toggles_changed |= ui.checkbox(&mut preview.show_axes, "Axes").changed();

        ui.separator();
        action.reset_view = ui
            .add_enabled(has_scene, egui::Button::new("Reset view"))
            .clicked();

        ui.separator();
        ui.label(theme::label("Faces"));
        let mut selected = triangulation;
        egui::ComboBox::from_id_salt("triangulation")
            .selected_text(triangulation.label())
            .width(84.0)
            .show_ui(ui, |ui| {
                for option in TRIANGULATIONS {
                    ui.selectable_value(&mut selected, option, option.label());
                }
            });
        if selected != triangulation {
            action.triangulation = Some(selected);
        }
    });

    action
}

/// One-line readout under the toolbar: geometry counts and frame cost.
pub fn readout(ui: &mut egui::Ui, scene: Option<&GpuScene>, stats: Option<&GpuRenderStats>) {
    ui.label(theme::mono(readout_text(
        scene.map(|s| (s.vertex_count(), s.triangle_count(), s.part_count())),
        stats.map(|s| (s.total_ms, s.draw_calls)),
    )));
}

/// Pure text builder for [`readout`], so the formatting is testable.
pub fn readout_text(
    geometry: Option<(u32, u32, usize)>,
    frame: Option<(f64, u32)>,
) -> String {
    let Some((vertices, triangles, parts)) = geometry else {
        return "no geometry uploaded".to_string();
    };
    let mut text = format!(
        "{} verts   {} tris   {} parts",
        theme::format_count(vertices as usize),
        theme::format_count(triangles as usize),
        theme::format_count(parts)
    );
    if let Some((total_ms, draw_calls)) = frame {
        text.push_str(&format!(
            "   {total_ms:.2} ms   {} draws",
            theme::format_count(draw_calls as usize)
        ));
    }
    text
}

/// Handle orbit / pan / zoom for the viewport, only while the pointer is on it.
/// Returns `true` when the camera moved.
pub fn interact(
    ui: &egui::Ui,
    response: &egui::Response,
    preview: &mut PreviewState,
) -> bool {
    let Some(camera) = preview.camera.as_mut() else {
        return false;
    };
    let mut moved = false;

    if response.dragged_by(egui::PointerButton::Primary) {
        let delta = ui.input(|input| input.pointer.delta());
        if delta != egui::Vec2::ZERO {
            camera.orbit(delta.x * 0.01, -delta.y * 0.01);
            moved = true;
        }
    }
    if response.dragged_by(egui::PointerButton::Secondary)
        || response.dragged_by(egui::PointerButton::Middle)
    {
        let delta = ui.input(|input| input.pointer.delta());
        if delta != egui::Vec2::ZERO {
            camera.pan(-delta.x, delta.y);
            moved = true;
        }
    }
    if response.hovered() {
        let scroll = ui.input(|input| input.smooth_scroll_delta.y);
        if scroll.abs() > f32::EPSILON {
            camera.zoom((-scroll * 0.001).clamp(-0.5, 0.5));
            moved = true;
        }
    }

    moved
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn readout_states_when_nothing_is_uploaded() {
        assert_eq!(readout_text(None, None), "no geometry uploaded");
        assert_eq!(readout_text(None, Some((1.5, 4))), "no geometry uploaded");
    }

    #[test]
    fn readout_groups_counts_and_appends_frame_cost() {
        let text = readout_text(Some((23880, 7960, 6)), Some((1.234, 14)));
        assert!(text.contains("23,880 verts"));
        assert!(text.contains("7,960 tris"));
        assert!(text.contains("6 parts"));
        assert!(text.contains("1.23 ms"));
        assert!(text.contains("14 draws"));
    }

    #[test]
    fn readout_without_frame_stats_omits_timing() {
        let text = readout_text(Some((10, 4, 1)), None);
        assert!(text.contains("10 verts"));
        assert!(!text.contains("ms"));
    }
}
