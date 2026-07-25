//! egui application shell.
//!
//! INTERFACE CONTRACT - `run_native` is the only required public entry point.
//! The UI task owns everything else in this module and the `gui/` submodules.
//!
//! Layout is fixed and predictable: menu bar on top, one-line status bar at the
//! bottom, search and results on the left, inspector on the right, 3D viewport
//! with its toolbar in the centre. This is a dense tool, not a page: nothing
//! animates except the viewport itself and real progress.
//!
//! This viewer is read-only. It previews and exports; it never writes back into
//! a game archive.

mod batch;
mod fonts;
mod inspector;
mod persist;
mod search;
mod titlebar;
mod viewport;
mod widgets;

use crate::gpu_renderer::{GpuRenderStats, GpuRenderer, GpuScene, RenderOptions, compute_grid_params};
use crate::index::{self, ArchiveRecord, ScanHandle, ScanMessage, ScanProgress, SearchFilter};
use crate::render::{PreviewBounds, PreviewCamera, PreviewState};
use crate::scene::Scene;
use crate::xmpr::Triangulation;
use crate::{gltf, imgp, theme};
use eframe::egui;
use eframe::egui_wgpu::wgpu;
use std::path::PathBuf;
use std::sync::mpsc::TryRecvError;
use std::time::{Duration, Instant};

/// AGE PSP textures are always PSP-swizzled; there is no reason to expose a
/// layout switch in the UI until a counter-example turns up.
const LAYOUT: imgp::PixelLayout = imgp::PixelLayout::PspSwizzled;

const WINDOW_TITLE: &str = "Gundam AGE PSP Asset Viewer";
const DEFAULT_WINDOW: [f32; 2] = [1680.0, 960.0];
const MIN_WINDOW: [f32; 2] = [1024.0, 640.0];
/// Width reserved on the right of the status bar for counts and job controls.
const STATUS_RIGHT_RESERVE: f32 = 300.0;
/// Failures listed in the post-export report modal before it says "and more".
const MAX_REPORTED_FAILURES: usize = 12;

/// Launch the viewer window.
pub fn run_native() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title(WINDOW_TITLE)
            .with_inner_size(DEFAULT_WINDOW)
            .with_min_inner_size(MIN_WINDOW)
            .with_clamp_size_to_monitor_size(true),
        ..Default::default()
    };
    eframe::run_native(
        WINDOW_TITLE,
        options,
        Box::new(|cc| Ok(Box::new(AgeViewerApp::new(cc)))),
    )
}

/// Severity of the status line. Colour here encodes real state, nothing else.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Level {
    Info,
    Ok,
    Warn,
    Error,
}

#[derive(Clone, Debug)]
struct Status {
    text: String,
    level: Level,
}

impl Status {
    fn info(text: impl Into<String>) -> Self {
        Self {
            text: text.into(),
            level: Level::Info,
        }
    }

    fn ok(text: impl Into<String>) -> Self {
        Self {
            text: text.into(),
            level: Level::Ok,
        }
    }

    fn warn(text: impl Into<String>) -> Self {
        Self {
            text: text.into(),
            level: Level::Warn,
        }
    }

    fn error(text: impl Into<String>) -> Self {
        Self {
            text: text.into(),
            level: Level::Error,
        }
    }

    fn color(&self) -> egui::Color32 {
        match self.level {
            Level::Info => theme::TEXT_SECONDARY,
            Level::Ok => theme::STATUS_OK,
            Level::Warn => theme::STATUS_WARN,
            Level::Error => theme::STATUS_ERROR,
        }
    }
}

/// wgpu handles kept from the eframe render state.
struct WgpuState {
    device: wgpu::Device,
    queue: wgpu::Queue,
    renderer: std::sync::Arc<egui::mutex::RwLock<eframe::egui_wgpu::Renderer>>,
}

/// A running resource-tree scan.
struct ScanJob {
    handle: ScanHandle,
    root: PathBuf,
    progress: ScanProgress,
    started: Instant,
    cancelling: bool,
}

/// A confirmed-but-not-yet-started export.
struct ExportPlan {
    out_dir: PathBuf,
    /// Empty for a single-archive export, which uses the loaded scene.
    targets: Vec<batch::Target>,
    /// Label shown in the confirmation modal.
    subject: String,
    single: bool,
}

pub struct AgeViewerApp {
    // GPU side
    wgpu: Option<WgpuState>,
    renderer: Option<GpuRenderer>,
    gpu_scene: Option<GpuScene>,
    /// Scene generation currently uploaded; `None` forces a re-upload.
    gpu_generation: Option<u64>,
    /// Per-mesh visibility, indexed by `Scene::meshes` order.
    visible: Vec<bool>,
    visibility_key: u64,
    last_stats: Option<GpuRenderStats>,

    // index side
    root: Option<PathBuf>,
    records: Vec<ArchiveRecord>,
    /// Bumped whenever `records` is replaced, to invalidate the result cache.
    records_revision: u64,
    categories: Vec<String>,
    filter: SearchFilter,
    results: search::ResultCache,
    scan: Option<ScanJob>,

    // scene side
    scene: Option<Scene>,
    /// Bumped on every archive load; keys the GPU and thumbnail caches.
    scene_generation: u64,
    selected_record: Option<usize>,
    triangulation: Triangulation,

    // UI state
    preview: PreviewState,
    thumbs: inspector::ThumbnailCache,
    texture_preview: Option<usize>,
    texture_preview_checker: bool,
    show_left: bool,
    show_right: bool,
    status: Status,
    modal_error: Option<String>,
    focus_search: bool,
    export_only_visible: bool,
    pending_export: Option<ExportPlan>,
    batch: Option<batch::Job>,

    // persistence
    persisted: persist::PersistedState,
    persist_dirty: bool,
    last_persist: Instant,
    /// Set once the native window frame has been switched to dark.
    titlebar_darkened: bool,
}

impl AgeViewerApp {
    fn new(cc: &eframe::CreationContext<'_>) -> Self {
        let (renderer, wgpu_state) = match cc.wgpu_render_state.as_ref() {
            Some(rs) => (
                Some(GpuRenderer::new(&rs.device, &rs.queue)),
                Some(WgpuState {
                    device: rs.device.clone(),
                    queue: rs.queue.clone(),
                    renderer: std::sync::Arc::clone(&rs.renderer),
                }),
            ),
            None => {
                eprintln!("[gui] no wgpu render state; the 3D preview is disabled");
                (None, None)
            }
        };

        theme::apply(&cc.egui_ctx);
        fonts::install_cjk_fonts(&cc.egui_ctx);

        let persisted = persist::load();
        if let Some(path) = persist::state_file_path() {
            eprintln!("[gui] UI state: {}", path.display());
        }

        let mut preview = PreviewState::default();
        preview.show_grid = persisted.show_grid.unwrap_or(preview.show_grid);
        preview.show_axes = persisted.show_axes.unwrap_or(preview.show_axes);
        preview.show_wireframe = persisted.show_wireframe.unwrap_or(preview.show_wireframe);
        preview.show_textures = persisted.show_textures.unwrap_or(preview.show_textures);

        let filter = SearchFilter {
            only_with_models: persisted.only_with_models.unwrap_or(false),
            only_with_textures: persisted.only_with_textures.unwrap_or(false),
            ..Default::default()
        };

        let mut app = Self {
            wgpu: wgpu_state,
            renderer,
            gpu_scene: None,
            gpu_generation: None,
            visible: Vec::new(),
            visibility_key: 0,
            last_stats: None,

            root: None,
            records: Vec::new(),
            records_revision: 0,
            categories: Vec::new(),
            filter,
            results: search::ResultCache::default(),
            scan: None,

            scene: None,
            scene_generation: 0,
            selected_record: None,
            triangulation: Triangulation::Strip,

            preview,
            thumbs: inspector::ThumbnailCache::default(),
            texture_preview: None,
            texture_preview_checker: true,
            show_left: true,
            show_right: true,
            status: Status::info("No resource root selected."),
            modal_error: None,
            focus_search: true,
            export_only_visible: false,
            pending_export: None,
            batch: None,

            persisted,
            persist_dirty: false,
            last_persist: Instant::now(),
            titlebar_darkened: false,
        };

        // Reopen where the user left off, but never fail because a drive moved.
        if let Some(root) = app.persisted.resource_root.clone() {
            if root.is_dir() {
                app.start_scan(root);
            } else {
                app.status = Status::warn(format!(
                    "Last resource root is gone: {}",
                    root.display()
                ));
            }
        }
        app
    }

    // ---------------------------------------------------------------- indexing

    fn start_scan(&mut self, root: PathBuf) {
        if let Some(job) = self.scan.take() {
            job.handle.cancel();
        }
        self.root = Some(root.clone());
        self.records.clear();
        self.records_revision = self.records_revision.wrapping_add(1);
        self.categories.clear();
        self.filter.category = None;
        self.results.invalidate();
        self.selected_record = None;

        persist::remember_root(&mut self.persisted.recent_roots, &root);
        self.persisted.resource_root = Some(root.clone());
        self.persist_dirty = true;

        self.status = Status::info(format!("Indexing {}", root.display()));
        self.scan = Some(ScanJob {
            handle: index::spawn_scan(root.clone()),
            root,
            progress: ScanProgress::default(),
            started: Instant::now(),
            cancelling: false,
        });
    }

    fn poll_scan(&mut self) {
        let Some(job) = self.scan.as_mut() else {
            return;
        };
        let mut terminal = None;
        loop {
            match job.handle.receiver.try_recv() {
                Ok(ScanMessage::Progress(progress)) => job.progress = progress,
                Ok(other) => {
                    terminal = Some(other);
                    break;
                }
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => {
                    terminal = Some(ScanMessage::Failed(
                        "the indexer stopped without reporting".to_string(),
                    ));
                    break;
                }
            }
        }

        let Some(terminal) = terminal else {
            return;
        };
        let job = self.scan.take().expect("scan job exists");
        let elapsed = job.started.elapsed().as_secs_f32();

        match terminal {
            ScanMessage::Finished(records) => {
                self.categories = index::categories(&records);
                let count = records.len();
                let errors = job.progress.errors;
                self.records = records;
                self.records_revision = self.records_revision.wrapping_add(1);
                self.results.invalidate();
                self.status = if count == 0 {
                    Status::warn(format!(
                        "No archives found under {} ({:.1} s)",
                        job.root.display(),
                        elapsed
                    ))
                } else if errors > 0 {
                    Status::warn(format!(
                        "Indexed {} archives in {:.1} s, {} unreadable",
                        theme::format_count(count),
                        elapsed,
                        theme::format_count(errors)
                    ))
                } else {
                    Status::ok(format!(
                        "Indexed {} archives in {:.1} s",
                        theme::format_count(count),
                        elapsed
                    ))
                };
            }
            ScanMessage::Cancelled => {
                self.status = Status::warn(format!(
                    "Indexing cancelled after {} files",
                    theme::format_count(job.progress.files_seen)
                ));
            }
            ScanMessage::Failed(reason) => {
                let message = format!("Could not index {}: {reason}", job.root.display());
                self.status = Status::error(message.clone());
                self.modal_error = Some(message);
            }
            ScanMessage::Progress(_) => unreachable!("progress is drained above"),
        }
    }

    // ------------------------------------------------------------------ scenes

    fn select_record(&mut self, index: usize) {
        let Some(record) = self.records.get(index) else {
            return;
        };
        let path = record.path.clone();
        self.selected_record = Some(index);
        self.load_archive(path);
    }

    fn load_archive(&mut self, path: PathBuf) {
        match Scene::load(&path, self.triangulation, LAYOUT) {
            Ok(scene) => {
                let failures = scene.mesh_failures.len() + scene.texture_failures.len();
                self.status = if failures > 0 {
                    Status::warn(format!(
                        "{}: {} meshes, {} textures, {} decode failures",
                        scene.archive_name,
                        theme::format_count(scene.meshes.len()),
                        theme::format_count(scene.textures.len()),
                        theme::format_count(failures)
                    ))
                } else {
                    Status::ok(format!(
                        "{}: {} meshes, {} textures, {} members",
                        scene.archive_name,
                        theme::format_count(scene.meshes.len()),
                        theme::format_count(scene.textures.len()),
                        theme::format_count(scene.member_count)
                    ))
                };
                self.scene = Some(scene);
                self.scene_generation = self.scene_generation.wrapping_add(1);
                self.gpu_generation = None;
                self.thumbs.clear();
                self.texture_preview = None;
            }
            Err(error) => {
                self.scene = None;
                self.gpu_scene = None;
                self.gpu_generation = None;
                self.visible.clear();
                self.thumbs.clear();
                self.texture_preview = None;
                let message = format!("Could not read {}: {error}", path.display());
                self.status = Status::error(message.clone());
                self.modal_error = Some(message);
            }
        }
    }

    /// Reload the current archive with a different triangulation hypothesis.
    fn set_triangulation(&mut self, triangulation: Triangulation) {
        if self.triangulation == triangulation {
            return;
        }
        self.triangulation = triangulation;
        match self.scene.as_ref().and_then(|scene| scene.archive_path.clone()) {
            Some(path) => self.load_archive(path),
            None => {
                self.status = Status::info(format!(
                    "Face mode set to {}; it applies to the next archive",
                    triangulation.label()
                ));
            }
        }
    }

    /// Upload the scene when it changed, and keep the visibility slice in sync.
    fn sync_gpu_scene(&mut self) {
        let Some(scene) = self.scene.as_ref() else {
            self.gpu_scene = None;
            self.gpu_generation = None;
            self.visible.clear();
            return;
        };

        let key = scene.visibility_key();
        if self.gpu_generation == Some(self.scene_generation) {
            // Visibility is a draw-time filter, so it never needs a re-upload.
            if self.visibility_key != key {
                self.visible = scene.meshes.iter().map(|mesh| mesh.visible).collect();
                self.visibility_key = key;
            }
            return;
        }

        let (Some(renderer), Some(rs)) = (self.renderer.as_mut(), self.wgpu.as_ref()) else {
            return;
        };
        self.gpu_scene = renderer.upload_scene(&rs.device, &rs.queue, scene);
        self.visible = scene.meshes.iter().map(|mesh| mesh.visible).collect();
        self.visibility_key = key;
        self.gpu_generation = Some(self.scene_generation);

        let bounds = self.gpu_scene.as_ref().map(|gpu| gpu.bounds());
        let (extent, step) = compute_grid_params(bounds.as_ref());
        renderer.update_grid(&rs.device, extent, step);
        self.preview.camera = Some(default_camera(self.gpu_scene.as_ref()));
    }

    fn reset_view(&mut self) {
        self.preview.camera = Some(default_camera(self.gpu_scene.as_ref()));
    }

    // ------------------------------------------------------------------ export

    fn export_current_archive_dialog(&mut self) {
        let Some(scene) = self.scene.as_ref() else {
            self.status = Status::warn("No archive is loaded.".to_string());
            return;
        };
        let subject = scene.archive_name.clone();
        let Some(out_dir) = self.pick_export_dir() else {
            return;
        };
        self.pending_export = Some(ExportPlan {
            out_dir,
            targets: Vec::new(),
            subject,
            single: true,
        });
    }

    fn export_results_dialog(&mut self) {
        let targets: Vec<batch::Target> = self
            .results
            .matches()
            .iter()
            .filter_map(|index| self.records.get(*index))
            .map(|record| batch::Target {
                path: record.path.clone(),
                relative: record.relative.clone(),
            })
            .collect();

        if targets.is_empty() {
            self.status = Status::warn("No search results to export.".to_string());
            return;
        }
        let Some(out_dir) = self.pick_export_dir() else {
            return;
        };
        self.pending_export = Some(ExportPlan {
            subject: format!("{} archives", theme::format_count(targets.len())),
            out_dir,
            targets,
            single: false,
        });
    }

    fn pick_export_dir(&mut self) -> Option<PathBuf> {
        let mut dialog = rfd::FileDialog::new();
        if let Some(dir) = &self.persisted.last_export_dir {
            dialog = dialog.set_directory(dir);
        }
        let picked = dialog.pick_folder()?;
        self.persisted.last_export_dir = Some(picked.clone());
        self.persist_dirty = true;
        Some(picked)
    }

    fn run_export(&mut self, plan: ExportPlan) {
        let options = gltf::ExportOptions {
            // A batch reloads every archive with all meshes visible, so the
            // visible-only filter can only mean anything for the open archive.
            only_visible: plan.single && self.export_only_visible,
            write_textures: true,
        };

        if plan.single {
            let Some(scene) = self.scene.as_ref() else {
                self.status = Status::warn("No archive is loaded.".to_string());
                return;
            };
            let name = scene
                .archive_path
                .as_deref()
                .map(batch::archive_stem)
                .unwrap_or_else(|| gltf::sanitize(&scene.archive_name, "model"));
            match gltf::export_scene(scene, &plan.out_dir, &name, options) {
                Ok(summary) => {
                    self.status = Status::ok(format!(
                        "Exported {} meshes, {} vertices to {}",
                        theme::format_count(summary.mesh_count),
                        theme::format_count(summary.vertex_count),
                        summary.gltf_path.display()
                    ));
                }
                Err(error) => {
                    let message = format!(
                        "Export failed for {} into {}: {error}",
                        scene.archive_name,
                        plan.out_dir.display()
                    );
                    self.status = Status::error(message.clone());
                    self.modal_error = Some(message);
                }
            }
            return;
        }

        let total = plan.targets.len();
        self.batch = Some(batch::Job::spawn(
            plan.targets,
            plan.out_dir.clone(),
            options,
            self.triangulation,
            LAYOUT,
        ));
        self.status = Status::info(format!(
            "Exporting {} archives to {}",
            theme::format_count(total),
            plan.out_dir.display()
        ));
    }

    fn poll_batch(&mut self) {
        let Some(job) = self.batch.as_mut() else {
            return;
        };
        let Some(finished) = job.poll() else {
            return;
        };

        let job = self.batch.take().expect("batch job exists");
        let summary = batch::summary_label(&finished, job.out_dir());
        self.status = if finished.failed > 0 || finished.report.is_err() {
            Status::warn(summary)
        } else if finished.cancelled {
            Status::warn(summary)
        } else {
            Status::ok(summary)
        };

        if finished.failed > 0 {
            let mut lines = vec![format!(
                "{} archives exported, {} failed.",
                theme::format_count(finished.exported),
                theme::format_count(finished.failed)
            )];
            if let Ok(report) = &finished.report {
                lines.push(format!("Full report: {}", report.display()));
            }
            lines.push(String::new());
            for (archive, error) in job.failures().iter().take(MAX_REPORTED_FAILURES) {
                lines.push(format!("{archive}: {error}"));
            }
            if finished.failed > job.failures().len().min(MAX_REPORTED_FAILURES) {
                lines.push(format!(
                    "and {} more, see the report",
                    theme::format_count(
                        finished.failed - job.failures().len().min(MAX_REPORTED_FAILURES)
                    )
                ));
            }
            self.modal_error = Some(lines.join("\n"));
        }
    }

    // ------------------------------------------------------------------ chrome

    fn menu_bar(&mut self, ui: &mut egui::Ui) {
        egui::MenuBar::new().ui(ui, |ui| {
            ui.menu_button("File", |ui| {
                if ui.button("Open root...").clicked() {
                    self.open_root_dialog();
                    ui.close();
                }
                ui.menu_button("Recent roots", |ui| {
                    if self.persisted.recent_roots.is_empty() {
                        ui.label(theme::caption("none yet"));
                    } else {
                        for root in self.persisted.recent_roots.clone() {
                            let missing = !root.is_dir();
                            let label = widgets::ellipsize_middle(&root.display().to_string(), 48);
                            let text = if missing {
                                egui::RichText::new(format!("{label} (missing)"))
                                    .color(theme::TEXT_MUTED)
                            } else {
                                egui::RichText::new(label).color(theme::TEXT_PRIMARY)
                            };
                            let response = ui
                                .add_enabled(!missing, egui::Button::new(text))
                                .on_hover_text(root.display().to_string());
                            if response.clicked() {
                                self.start_scan(root);
                                ui.close();
                            }
                        }
                    }
                });
                if ui.button("Open archive...").clicked() {
                    self.open_archive_dialog();
                    ui.close();
                }

                ui.separator();
                let can_rescan = self.root.is_some() && self.scan.is_none();
                if ui
                    .add_enabled(can_rescan, egui::Button::new("Rescan root"))
                    .clicked()
                {
                    if let Some(root) = self.root.clone() {
                        self.start_scan(root);
                    }
                    ui.close();
                }
                if ui
                    .add_enabled(self.scan.is_some(), egui::Button::new("Cancel scan"))
                    .clicked()
                {
                    self.cancel_scan();
                    ui.close();
                }

                ui.separator();
                let busy = self.batch.is_some();
                if ui
                    .add_enabled(
                        self.scene.is_some() && !busy,
                        egui::Button::new("Export archive..."),
                    )
                    .clicked()
                {
                    self.export_current_archive_dialog();
                    ui.close();
                }
                if ui
                    .add_enabled(
                        self.results.len() > 0 && !busy,
                        egui::Button::new("Export results..."),
                    )
                    .clicked()
                {
                    self.export_results_dialog();
                    ui.close();
                }
                if ui
                    .add_enabled(busy, egui::Button::new("Cancel export"))
                    .clicked()
                {
                    if let Some(job) = self.batch.as_mut() {
                        job.request_cancel();
                    }
                    ui.close();
                }

                ui.separator();
                if ui.button("Exit").clicked() {
                    ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
                }
            });

            ui.menu_button("View", |ui| {
                ui.checkbox(&mut self.show_left, "Search panel");
                ui.checkbox(&mut self.show_right, "Inspector");
                ui.separator();
                if ui
                    .add_enabled(self.scene.is_some(), egui::Button::new("Reset view"))
                    .clicked()
                {
                    self.reset_view();
                    ui.close();
                }
            });

            if let Some(root) = &self.root {
                ui.separator();
                let text = root.display().to_string();
                ui.add(egui::Label::new(theme::mono(widgets::ellipsize_middle(&text, 64))).truncate())
                    .on_hover_text(text);
            }
        });
    }

    fn status_bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            let height = ui.available_height();
            let left = (ui.available_width() - STATUS_RIGHT_RESERVE).max(120.0);
            ui.allocate_ui_with_layout(
                egui::vec2(left, height),
                egui::Layout::left_to_right(egui::Align::Center),
                |ui| {
                    let text = self.status_text();
                    ui.add(
                        egui::Label::new(
                            egui::RichText::new(&text).color(self.status.color()),
                        )
                        .truncate(),
                    )
                    .on_hover_text(text);
                },
            );

            ui.with_layout(
                egui::Layout::right_to_left(egui::Align::Center),
                |ui| {
                    if let Some(job) = self.batch.as_mut() {
                        if ui
                            .add_enabled(!job.is_cancelling(), egui::Button::new("Cancel"))
                            .clicked()
                        {
                            job.request_cancel();
                        }
                        ui.add(
                            egui::ProgressBar::new(job.fraction())
                                .desired_width(150.0)
                                .corner_radius(theme::RADIUS_CONTROL)
                                .fill(theme::ACCENT)
                                .text(theme::mono_strong(job.progress_label())),
                        );
                        return;
                    }
                    if let Some(job) = self.scan.as_mut() {
                        if ui
                            .add_enabled(!job.cancelling, egui::Button::new("Cancel"))
                            .clicked()
                        {
                            job.handle.cancel();
                            job.cancelling = true;
                        }
                        ui.label(theme::mono_strong(format!(
                            "{} files   {} archives   {} errors",
                            theme::format_count(job.progress.files_seen),
                            theme::format_count(job.progress.archives_found),
                            theme::format_count(job.progress.errors)
                        )));
                        return;
                    }
                    ui.label(theme::mono(search::match_summary(
                        self.results.len(),
                        self.records.len(),
                    )));
                },
            );
        });
    }

    /// Status text, with the live job state taking precedence over the last result.
    fn status_text(&self) -> String {
        if let Some(job) = &self.batch {
            return format!("Exporting: {}", job.progress_label());
        }
        if let Some(job) = &self.scan {
            let root = widgets::ellipsize_middle(&job.root.display().to_string(), 52);
            if job.cancelling {
                return format!("Stopping the scan of {root}");
            }
            let current = if job.progress.current.is_empty() {
                String::new()
            } else {
                format!(", {}", job.progress.current)
            };
            return format!("Indexing {root}{current}");
        }
        self.status.text.clone()
    }

    // ------------------------------------------------------------------- panels

    fn left_panel(&mut self, ui: &mut egui::Ui) {
        widgets::section_header(ui, "Search");

        ui.horizontal(|ui| {
            let width = (ui.available_width() - 66.0).max(80.0);
            let response = ui.add(
                egui::TextEdit::singleline(&mut self.filter.query)
                    .hint_text("name or path")
                    .desired_width(width),
            );
            if self.focus_search {
                response.request_focus();
                self.focus_search = false;
            }
            if ui
                .add_enabled(
                    !self.filter.query.is_empty(),
                    egui::Button::new("Clear"),
                )
                .clicked()
            {
                self.filter.query.clear();
            }
        });

        ui.horizontal(|ui| {
            let mut changed = ui
                .checkbox(&mut self.filter.only_with_models, "Has models")
                .changed();
            changed |= ui
                .checkbox(&mut self.filter.only_with_textures, "Has textures")
                .changed();
            if changed {
                self.persist_dirty = true;
            }
        });

        ui.horizontal(|ui| {
            ui.label(theme::label("Area"));
            let current = self.filter.category.clone();
            let mut chosen = current.clone();
            let selected_text = current.clone().unwrap_or_else(|| "all".to_string());
            egui::ComboBox::from_id_salt("category")
                .selected_text(selected_text)
                .width((ui.available_width() - 4.0).max(80.0))
                .show_ui(ui, |ui| {
                    ui.selectable_value(&mut chosen, None, "all");
                    for category in &self.categories {
                        ui.selectable_value(
                            &mut chosen,
                            Some(category.clone()),
                            category,
                        );
                    }
                });
            if chosen != current {
                self.filter.category = chosen;
            }
        });

        self.results
            .refresh(&self.records, &self.filter, self.records_revision);

        ui.add_space(6.0);
        ui.label(theme::mono_strong(search::match_summary(
            self.results.len(),
            self.records.len(),
        )));
        ui.add_space(4.0);

        if self.records.is_empty() {
            self.empty_result_state(ui);
            return;
        }
        if self.results.len() == 0 {
            widgets::empty_state(
                ui,
                "No archives match this filter.",
                "Remove a term, clear the model or texture toggle, or pick a different area.",
            );
            return;
        }

        let mut clicked = None;
        egui::ScrollArea::vertical()
            .auto_shrink([false, false])
            .show_rows(ui, search::ROW_HEIGHT, self.results.len(), |ui, range| {
                for row_index in range {
                    let Some(&record_index) = self.results.matches().get(row_index) else {
                        continue;
                    };
                    let Some(record) = self.records.get(record_index) else {
                        continue;
                    };
                    let selected = self.selected_record == Some(record_index);
                    let response = search::row(ui, record, row_index, selected);
                    if response.clicked() {
                        clicked = Some(record_index);
                    }
                    response.on_hover_text(format!(
                        "{}\n{} members, {} models, {} textures, {}",
                        record.relative,
                        theme::format_count(record.member_count),
                        theme::format_count(record.prm_count),
                        theme::format_count(record.xi_count),
                        theme::format_bytes(record.size as usize)
                    ));
                }
            });

        if let Some(index) = clicked {
            self.select_record(index);
        }
    }

    /// Left-panel state when there is nothing to list yet.
    fn empty_result_state(&mut self, ui: &mut egui::Ui) {
        if self.scan.is_some() {
            widgets::empty_state(
                ui,
                "Indexing the resource tree.",
                "Results appear when the scan finishes; progress is in the status bar.",
            );
            return;
        }
        if self.root.is_some() {
            widgets::empty_state(
                ui,
                "No archives were found under this root.",
                "Pick the folder that holds chr, map and eff.",
            );
        } else {
            widgets::empty_state(
                ui,
                "No resource root selected.",
                "Choose the unpacked PSP resource folder to index it.",
            );
        }
        ui.add_space(6.0);
        if ui.button("Open root...").clicked() {
            self.open_root_dialog();
        }
    }

    fn right_panel(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        let generation = self.scene_generation;
        match self.scene.as_mut() {
            Some(scene) => {
                if let Some(index) =
                    inspector::show(ui, ctx, scene, generation, &mut self.thumbs)
                {
                    self.texture_preview = Some(index);
                }
            }
            None => {
                widgets::section_header(ui, "Archive");
                widgets::empty_state(
                    ui,
                    "No archive loaded.",
                    "Pick a search result, or open a single archive from the File menu.",
                );
            }
        }
    }

    fn center_panel(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        let action = viewport::toolbar(
            ui,
            &mut self.preview,
            self.triangulation,
            self.scene.is_some(),
        );
        if action.toggles_changed {
            self.persist_dirty = true;
        }
        if action.reset_view {
            self.reset_view();
        }
        if let Some(triangulation) = action.triangulation {
            self.set_triangulation(triangulation);
        }
        viewport::readout(ui, self.gpu_scene.as_ref(), self.last_stats.as_ref());
        ui.add_space(2.0);
        self.paint_viewport(ui, ctx);
    }

    fn paint_viewport(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        if self.wgpu.is_none() || self.renderer.is_none() {
            widgets::empty_state(
                ui,
                "The 3D preview is unavailable on this machine.",
                "No wgpu device was created at startup; the inspector and export still work.",
            );
            return;
        }

        // The wgpu target must never be zero-sized, however narrow the panels get.
        let available = ui.available_size();
        let width = available.x.max(1.0);
        let height = available.y.max(1.0);

        let camera = *self
            .preview
            .camera
            .get_or_insert_with(|| default_camera(None));
        let options = RenderOptions {
            show_wireframe: self.preview.show_wireframe,
            show_grid: self.preview.show_grid,
            show_axes: self.preview.show_axes,
            show_textures: self.preview.show_textures,
        };

        let texture_id = {
            let rs = self.wgpu.as_ref().expect("wgpu state checked above");
            let renderer = self.renderer.as_mut().expect("renderer checked above");
            renderer.ensure_viewport(
                &rs.device,
                &mut rs.renderer.write(),
                width as u32,
                height as u32,
            );
            self.last_stats = renderer.render(
                &rs.device,
                &rs.queue,
                &camera,
                self.gpu_scene.as_ref(),
                &self.visible,
                options,
            );
            // Never cached across frames: a resize frees and re-registers it.
            renderer.egui_texture_id()
        };

        let (rect, response) = ui.allocate_exact_size(
            egui::vec2(width, height),
            egui::Sense::click_and_drag(),
        );
        if let Some(id) = texture_id {
            ui.painter().image(
                id,
                rect,
                egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
                egui::Color32::WHITE,
            );
        }

        if self.gpu_scene.is_none() {
            let message = if self.scene.is_some() {
                "This archive has no drawable geometry."
            } else {
                "Select an archive to preview it."
            };
            ui.painter().text(
                rect.center(),
                egui::Align2::CENTER_CENTER,
                message,
                widgets::body_font(ui),
                theme::TEXT_SECONDARY,
            );
        }

        if viewport::interact(ui, &response, &mut self.preview) {
            ctx.request_repaint();
        }
    }

    // ------------------------------------------------------------------ dialogs

    fn open_root_dialog(&mut self) {
        let mut dialog = rfd::FileDialog::new();
        if let Some(dir) = &self.persisted.resource_root {
            dialog = dialog.set_directory(dir);
        }
        if let Some(root) = dialog.pick_folder() {
            self.start_scan(root);
        }
    }

    fn open_archive_dialog(&mut self) {
        let mut dialog =
            rfd::FileDialog::new().add_filter("XPCK archive", crate::xpck::ARCHIVE_EXTENSIONS);
        if let Some(dir) = &self.persisted.last_open_dir {
            dialog = dialog.set_directory(dir);
        }
        let Some(path) = dialog.pick_file() else {
            return;
        };
        if let Some(parent) = path.parent() {
            self.persisted.last_open_dir = Some(parent.to_path_buf());
            self.persist_dirty = true;
        }
        // A directly opened archive is not part of any indexed result set.
        self.selected_record = None;
        self.load_archive(path);
    }

    fn cancel_scan(&mut self) {
        if let Some(job) = self.scan.as_mut() {
            job.handle.cancel();
            job.cancelling = true;
        }
    }

    fn export_modal(&mut self, ctx: &egui::Context) {
        let Some(plan) = self.pending_export.take() else {
            return;
        };
        let mut decision: Option<bool> = None;

        let modal = egui::Modal::new(egui::Id::new("age_export_confirm")).show(ctx, |ui| {
            ui.set_min_width(460.0);
            ui.label(theme::section(if plan.single {
                "Export archive"
            } else {
                "Export search results"
            }));
            ui.add_space(6.0);

            if plan.single {
                ui.label(theme::label("Writes one glTF, its buffer and its textures."));
            } else {
                ui.label(theme::label(
                    "Writes one subfolder per archive, each with a glTF, its buffer and its textures.",
                ));
            }
            ui.add_space(6.0);
            widgets::field(ui, "Archives", &plan.subject);
            widgets::field(ui, "Destination", &plan.out_dir.display().to_string());
            ui.label(theme::caption(
                "Files with the same names in the destination are overwritten.",
            ));
            if !plan.single {
                ui.label(theme::caption(format!(
                    "A JSON report is written as {}.",
                    batch::REPORT_FILE_NAME
                )));
            }

            ui.add_space(8.0);
            if plan.single {
                ui.checkbox(&mut self.export_only_visible, "Only visible meshes");
            } else {
                ui.label(theme::caption(
                    "Every mesh of every archive is exported; mesh visibility applies to the open archive only.",
                ));
            }

            ui.add_space(10.0);
            ui.horizontal(|ui| {
                let export = egui::Button::new(
                    egui::RichText::new("Export").color(theme::BG_BASE),
                )
                .fill(theme::ACCENT);
                if ui.add(export).clicked() {
                    decision = Some(true);
                }
                if ui.button("Cancel").clicked() {
                    decision = Some(false);
                }
            });
        });

        match decision {
            Some(true) => self.run_export(plan),
            Some(false) => {}
            None if modal.should_close() => {}
            None => self.pending_export = Some(plan),
        }
    }

    fn error_modal(&mut self, ctx: &egui::Context) {
        let Some(message) = self.modal_error.clone() else {
            return;
        };
        let modal = egui::Modal::new(egui::Id::new("age_error_modal")).show(ctx, |ui| {
            ui.set_min_width(460.0);
            ui.label(
                egui::RichText::new("Something did not work")
                    .color(theme::STATUS_ERROR)
                    .strong(),
            );
            ui.add_space(6.0);
            egui::ScrollArea::vertical()
                .max_height(300.0)
                .show(ui, |ui| {
                    ui.label(theme::mono_strong(&message));
                });
            ui.add_space(8.0);
            ui.button("Close").clicked()
        });
        if modal.inner || modal.should_close() {
            self.modal_error = None;
        }
    }

    fn texture_window(&mut self, ctx: &egui::Context) {
        let Some(index) = self.texture_preview else {
            return;
        };
        let Some(scene) = self.scene.as_ref() else {
            self.texture_preview = None;
            return;
        };
        let Some(entry) = scene.texture(index) else {
            self.texture_preview = None;
            return;
        };

        let member = entry.member.clone();
        let info = inspector::describe_texture(&entry.texture);
        let width = entry.texture.width;
        let height = entry.texture.height;
        let handle = self
            .thumbs
            .handle(ctx, index, &member, &entry.texture);

        let mut open = true;
        let mut checker = self.texture_preview_checker;
        egui::Window::new("Texture")
            .id(egui::Id::new("age_texture_preview"))
            .open(&mut open)
            .resizable(true)
            .default_size([480.0, 540.0])
            .show(ctx, |ui| {
                ui.label(theme::mono_strong(&member));
                ui.label(theme::mono(&info));
                ui.checkbox(&mut checker, "Checkerboard");
                ui.add_space(4.0);

                let available = ui.available_size();
                let (rect, _) = ui.allocate_exact_size(
                    egui::vec2(available.x.max(48.0), available.y.max(48.0)),
                    egui::Sense::hover(),
                );
                let painter = ui.painter();
                if checker {
                    widgets::paint_checkerboard(painter, rect, 12.0);
                } else {
                    painter.rect_filled(
                        rect,
                        egui::CornerRadius::same(theme::RADIUS_CONTROL),
                        theme::BG_SUNKEN,
                    );
                }
                if let Some(handle) = &handle {
                    painter.image(
                        handle.id(),
                        inspector::fit_rect(rect, width, height),
                        egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
                        egui::Color32::WHITE,
                    );
                }
            });

        self.texture_preview_checker = checker;
        if !open {
            self.texture_preview = None;
        }
    }

    // -------------------------------------------------------------- persistence

    fn snapshot_persisted(&mut self) {
        self.persisted.show_grid = Some(self.preview.show_grid);
        self.persisted.show_axes = Some(self.preview.show_axes);
        self.persisted.show_wireframe = Some(self.preview.show_wireframe);
        self.persisted.show_textures = Some(self.preview.show_textures);
        self.persisted.only_with_models = Some(self.filter.only_with_models);
        self.persisted.only_with_textures = Some(self.filter.only_with_textures);
    }

    fn write_persisted(&mut self) {
        self.snapshot_persisted();
        self.persist_dirty = false;
        self.last_persist = Instant::now();
        if let Err(error) = persist::save(&self.persisted) {
            eprintln!("[gui] could not write UI state: {error}");
        }
    }

    fn flush_persisted(&mut self) {
        if self.persist_dirty && self.last_persist.elapsed() >= Duration::from_secs(2) {
            self.write_persisted();
        }
    }

    fn handle_shortcuts(&mut self, ctx: &egui::Context) {
        let focus_search = ctx.input_mut(|input| {
            input.consume_key(egui::Modifiers::COMMAND, egui::Key::F)
        });
        if focus_search {
            self.show_left = true;
            self.focus_search = true;
        }
    }
}

impl eframe::App for AgeViewerApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // The native window only exists once the loop is running, so the frame
        // colour is set on the first frame rather than during construction.
        if !self.titlebar_darkened {
            titlebar::make_dark(WINDOW_TITLE);
            self.titlebar_darkened = true;
        }

        self.poll_scan();
        self.poll_batch();
        self.handle_shortcuts(ctx);

        egui::TopBottomPanel::top("age_menu_bar").show(ctx, |ui| {
            self.menu_bar(ui);
        });
        egui::TopBottomPanel::bottom("age_status_bar").show(ctx, |ui| {
            self.status_bar(ui);
        });

        if self.show_left {
            egui::SidePanel::left("age_search_panel")
                .resizable(true)
                .default_width(360.0)
                .min_width(240.0)
                .max_width(560.0)
                .show(ctx, |ui| {
                    self.left_panel(ui);
                });
        }
        if self.show_right {
            egui::SidePanel::right("age_inspector_panel")
                .resizable(true)
                .default_width(340.0)
                .min_width(240.0)
                .max_width(560.0)
                .show(ctx, |ui| {
                    self.right_panel(ui, ctx);
                });
        }

        self.sync_gpu_scene();

        egui::CentralPanel::default().show(ctx, |ui| {
            self.center_panel(ui, ctx);
        });

        self.export_modal(ctx);
        self.error_modal(ctx);
        self.texture_window(ctx);
        self.flush_persisted();

        // Poll background work without spinning the GPU when nothing is running.
        if self.scan.is_some() || self.batch.is_some() {
            ctx.request_repaint_after(Duration::from_millis(120));
        }
    }

    fn on_exit(&mut self) {
        if let Some(job) = self.scan.as_ref() {
            job.handle.cancel();
        }
        if let Some(job) = self.batch.as_mut() {
            job.request_cancel();
        }
        self.write_persisted();
    }
}

/// Camera that frames an uploaded scene, or a unit box when there is none.
fn default_camera(scene: Option<&GpuScene>) -> PreviewCamera {
    match scene {
        // Display-space bounds and focus target, so off-centre maps frame right.
        Some(gpu) => PreviewCamera::frame_bounds_with_target(gpu.bounds(), gpu.focus_target()),
        None => PreviewCamera::frame_bounds(PreviewBounds::new([-1.0; 3], [1.0; 3])),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn status_levels_map_to_distinct_state_colours() {
        assert_eq!(Status::info("x").color(), theme::TEXT_SECONDARY);
        assert_eq!(Status::ok("x").color(), theme::STATUS_OK);
        assert_eq!(Status::warn("x").color(), theme::STATUS_WARN);
        assert_eq!(Status::error("x").color(), theme::STATUS_ERROR);
    }

    #[test]
    fn status_keeps_its_text() {
        let status = Status::warn("2 decode failures");
        assert_eq!(status.text, "2 decode failures");
        assert_eq!(status.level, Level::Warn);
    }

    #[test]
    fn default_camera_without_a_scene_is_finite() {
        let camera = default_camera(None);
        assert!(camera.distance.is_finite() && camera.distance > 0.0);
        assert!(camera.near > 0.0 && camera.near < camera.far);
    }
}
