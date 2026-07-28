//! Background batch export (glTF or OBJ).
//!
//! Export only: nothing in this module ever writes back into a game archive.
//! One worker thread walks the archives the user is looking at, writes each into
//! a package directory named after the original relative path, keeps going when
//! a single archive fails, and drops a JSON report next to the output.

use crate::export_fmt::{self, Format, Options, Summary};
use crate::theme;
use crate::{imgp, scene::Scene, xmpr};
use serde_json::{Value, json};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, TryRecvError};

/// Report file written into the chosen output directory.
pub const REPORT_FILE_NAME: &str = "age_viewer_export_report.json";
/// Failures kept in memory for the UI; the JSON report keeps all of them.
const MAX_TRACKED_FAILURES: usize = 50;

/// One archive queued for export.
#[derive(Clone, Debug)]
pub struct Target {
    pub path: PathBuf,
    /// Path relative to the resource root, for reports, progress and folders.
    pub relative: String,
}

/// Result of exporting one archive.
#[derive(Clone, Debug)]
struct Outcome {
    relative: String,
    folder: String,
    detail: Result<Counts, String>,
}

#[derive(Clone, Copy, Debug, Default)]
struct Counts {
    meshes: usize,
    vertices: usize,
    faces: usize,
    materials: usize,
    textures: usize,
    skipped: usize,
}

impl From<&Summary> for Counts {
    fn from(summary: &Summary) -> Self {
        Self {
            meshes: summary.mesh_count,
            vertices: summary.vertex_count,
            faces: summary.face_count,
            materials: summary.material_count,
            textures: summary.texture_count,
            skipped: summary.skipped_meshes,
        }
    }
}

enum Message {
    /// About to start `relative`; `done` archives are already finished.
    Progress { done: usize, current: String },
    Item(Outcome),
    Finished {
        cancelled: bool,
        report: Result<PathBuf, String>,
    },
}

/// Terminal state handed back to the UI once the worker stops.
pub struct Finished {
    pub exported: usize,
    pub failed: usize,
    pub cancelled: bool,
    pub report: Result<PathBuf, String>,
}

/// A running batch export.
pub struct Job {
    receiver: Receiver<Message>,
    cancel: Arc<AtomicBool>,
    out_dir: PathBuf,
    total: usize,
    done: usize,
    exported: usize,
    failed: usize,
    current: String,
    cancelling: bool,
    failures: Vec<(String, String)>,
}

impl Job {
    /// Start the worker. Returns immediately; the UI thread never blocks on it.
    pub fn spawn(
        targets: Vec<Target>,
        out_dir: PathBuf,
        options: Options,
        triangulation: xmpr::Triangulation,
        layout: imgp::PixelLayout,
    ) -> Self {
        let (sender, receiver) = std::sync::mpsc::channel();
        let cancel = Arc::new(AtomicBool::new(false));
        let worker_cancel = Arc::clone(&cancel);
        let total = targets.len();
        let worker_out_dir = out_dir.clone();

        std::thread::spawn(move || {
            let mut taken: HashSet<String> = HashSet::new();
            let mut outcomes: Vec<Outcome> = Vec::with_capacity(total);
            let mut cancelled = false;

            for (index, target) in targets.iter().enumerate() {
                if worker_cancel.load(Ordering::Relaxed) {
                    cancelled = true;
                    break;
                }
                let _ = sender.send(Message::Progress {
                    done: index,
                    current: target.relative.clone(),
                });

                let package = export_fmt::package_dir(&worker_out_dir, &target.relative, &mut taken);
                let folder = package
                    .strip_prefix(&worker_out_dir)
                    .unwrap_or(package.as_path())
                    .to_string_lossy()
                    .replace('\\', "/");
                let outcome = Outcome {
                    relative: target.relative.clone(),
                    folder,
                    detail: export_one(
                        &target.path,
                        &package,
                        options,
                        triangulation,
                        layout,
                    ),
                };
                let _ = sender.send(Message::Item(outcome.clone()));
                outcomes.push(outcome);
            }

            let report = write_report(&worker_out_dir, total, options.format, &outcomes, cancelled);
            let _ = sender.send(Message::Finished { cancelled, report });
        });

        Self {
            receiver,
            cancel,
            out_dir,
            total,
            done: 0,
            exported: 0,
            failed: 0,
            current: String::new(),
            cancelling: false,
            failures: Vec::new(),
        }
    }

    pub fn request_cancel(&mut self) {
        self.cancel.store(true, Ordering::Relaxed);
        self.cancelling = true;
    }

    pub fn is_cancelling(&self) -> bool {
        self.cancelling
    }

    pub fn out_dir(&self) -> &Path {
        &self.out_dir
    }

    pub fn fraction(&self) -> f32 {
        if self.total == 0 {
            return 1.0;
        }
        (self.done as f32 / self.total as f32).clamp(0.0, 1.0)
    }

    pub fn progress_label(&self) -> String {
        progress_label(self.done, self.total, &self.current, self.cancelling)
    }

    pub fn failures(&self) -> &[(String, String)] {
        &self.failures
    }

    /// Drain worker messages. Returns the terminal state once the run ends.
    pub fn poll(&mut self) -> Option<Finished> {
        loop {
            match self.receiver.try_recv() {
                Ok(Message::Progress { done, current }) => {
                    self.done = done;
                    self.current = current;
                }
                Ok(Message::Item(outcome)) => {
                    self.done += 1;
                    match outcome.detail {
                        Ok(_) => self.exported += 1,
                        Err(error) => {
                            self.failed += 1;
                            if self.failures.len() < MAX_TRACKED_FAILURES {
                                self.failures.push((outcome.relative, error));
                            }
                        }
                    }
                }
                Ok(Message::Finished { cancelled, report }) => {
                    return Some(Finished {
                        exported: self.exported,
                        failed: self.failed,
                        cancelled,
                        report,
                    });
                }
                Err(TryRecvError::Empty) => return None,
                Err(TryRecvError::Disconnected) => {
                    return Some(Finished {
                        exported: self.exported,
                        failed: self.failed,
                        cancelled: self.cancelling,
                        report: Err("the export worker stopped without reporting".to_string()),
                    });
                }
            }
        }
    }
}

/// Load and export one archive. A decoder panic is contained so a single bad
/// archive cannot abort a large batch run.
fn export_one(
    path: &Path,
    out_dir: &Path,
    options: Options,
    triangulation: xmpr::Triangulation,
    layout: imgp::PixelLayout,
) -> Result<Counts, String> {
    let name = archive_stem(path);
    let attempt = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        Scene::load(path, triangulation, layout)
            .and_then(|scene| export_fmt::export_scene(&scene, out_dir, &name, options))
    }));
    match attempt {
        Ok(Ok(summary)) => Ok(Counts::from(&summary)),
        Ok(Err(error)) => Err(error.to_string()),
        Err(_) => Err("decoder panicked while reading this archive".to_string()),
    }
}

/// File stem of an archive path, e.g. `ms001000_p000`.
pub fn archive_stem(path: &Path) -> String {
    path.file_stem()
        .and_then(|stem| stem.to_str())
        .unwrap_or("archive")
        .to_string()
}

/// `"142 of 312 archives, chr/ms001000/ms001000_p000.xc"`.
pub fn progress_label(done: usize, total: usize, current: &str, cancelling: bool) -> String {
    let head = format!(
        "{} of {} archives",
        theme::format_count(done),
        theme::format_count(total)
    );
    if cancelling {
        return format!("{head}, stopping");
    }
    if current.is_empty() {
        head
    } else {
        format!("{head}, {current}")
    }
}

/// Status line for a finished run.
pub fn summary_label(finished: &Finished, out_dir: &Path) -> String {
    let verb = if finished.cancelled {
        "Export cancelled"
    } else {
        "Export finished"
    };
    let mut text = format!(
        "{verb}: {} written, {} failed, into {}",
        theme::format_count(finished.exported),
        theme::format_count(finished.failed),
        out_dir.display()
    );
    if let Err(error) = &finished.report {
        text.push_str(&format!(" (report not written: {error})"));
    }
    text
}

/// Build the JSON report body.
fn report_json(
    out_dir: &Path,
    requested: usize,
    format: Format,
    outcomes: &[Outcome],
    cancelled: bool,
) -> Value {
    let entries: Vec<Value> = outcomes
        .iter()
        .map(|outcome| match &outcome.detail {
            Ok(counts) => json!({
                "archive": outcome.relative,
                "folder": outcome.folder,
                "status": "ok",
                "meshes": counts.meshes,
                "vertices": counts.vertices,
                "faces": counts.faces,
                "materials": counts.materials,
                "textures": counts.textures,
                "skipped_meshes": counts.skipped,
            }),
            Err(error) => json!({
                "archive": outcome.relative,
                "folder": outcome.folder,
                "status": "failed",
                "error": error,
            }),
        })
        .collect();

    let exported = outcomes.iter().filter(|o| o.detail.is_ok()).count();
    json!({
        "tool": "age_viewer batch export",
        "format": format.short_label(),
        "output_dir": out_dir.display().to_string(),
        "requested": requested,
        "attempted": outcomes.len(),
        "exported": exported,
        "failed": outcomes.len() - exported,
        "cancelled": cancelled,
        "entries": entries,
    })
}

fn write_report(
    out_dir: &Path,
    requested: usize,
    format: Format,
    outcomes: &[Outcome],
    cancelled: bool,
) -> Result<PathBuf, String> {
    let body = report_json(out_dir, requested, format, outcomes, cancelled);
    let text = serde_json::to_string_pretty(&body).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(out_dir).map_err(|e| e.to_string())?;
    let path = out_dir.join(REPORT_FILE_NAME);
    std::fs::write(&path, text).map_err(|e| e.to_string())?;
    Ok(path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::export_fmt;

    fn ok_outcome(relative: &str, folder: &str) -> Outcome {
        Outcome {
            relative: relative.to_string(),
            folder: folder.to_string(),
            detail: Ok(Counts {
                meshes: 6,
                vertices: 1200,
                faces: 2100,
                materials: 3,
                textures: 5,
                skipped: 1,
            }),
        }
    }

    fn failed_outcome(relative: &str, folder: &str, error: &str) -> Outcome {
        Outcome {
            relative: relative.to_string(),
            folder: folder.to_string(),
            detail: Err(error.to_string()),
        }
    }

    #[test]
    fn package_dirs_follow_original_relative_names() {
        let mut taken = HashSet::new();
        let dir = export_fmt::package_dir(
            Path::new("out"),
            "chr/ms001000/ms001000_p000.xc",
            &mut taken,
        );
        assert_eq!(
            dir,
            PathBuf::from("out")
                .join("chr")
                .join("ms001000")
                .join("ms001000_p000")
        );
        assert_eq!(
            export_fmt::package_dir(Path::new("out"), "map/e1101.xc", &mut taken),
            PathBuf::from("out").join("map").join("e1101")
        );
    }

    #[test]
    fn colliding_packages_get_numeric_leaf_suffixes() {
        let mut taken = HashSet::new();
        let a = export_fmt::package_dir(Path::new("out"), "chr/a/model.xc", &mut taken);
        let b = export_fmt::package_dir(Path::new("out"), "chr/a/model.xc", &mut taken);
        assert_eq!(a.file_name().unwrap(), "model");
        assert_eq!(b.file_name().unwrap(), "model_2");
    }

    #[test]
    fn archive_stem_falls_back_when_the_path_has_no_stem() {
        assert_eq!(archive_stem(Path::new("chr/x/ms001.xc")), "ms001");
        assert_eq!(archive_stem(Path::new("")), "archive");
    }

    #[test]
    fn progress_label_reports_position_and_current_archive() {
        assert_eq!(
            progress_label(142, 1312, "chr/ms001000/ms001000_p000.xc", false),
            "142 of 1,312 archives, chr/ms001000/ms001000_p000.xc"
        );
        assert_eq!(progress_label(0, 4529, "", false), "0 of 4,529 archives");
        assert_eq!(
            progress_label(7, 10, "map/e1101.xc", true),
            "7 of 10 archives, stopping"
        );
    }

    #[test]
    fn summary_label_states_counts_and_destination() {
        let finished = Finished {
            exported: 310,
            failed: 2,
            cancelled: false,
            report: Ok(PathBuf::from("out/report.json")),
        };
        let text = summary_label(&finished, Path::new("out"));
        assert!(text.starts_with("Export finished"));
        assert!(text.contains("310 written"));
        assert!(text.contains("2 failed"));

        let cancelled = Finished {
            exported: 4,
            failed: 0,
            cancelled: true,
            report: Err("disk full".to_string()),
        };
        let text = summary_label(&cancelled, Path::new("out"));
        assert!(text.starts_with("Export cancelled"));
        assert!(text.contains("report not written: disk full"));
    }

    #[test]
    fn report_json_counts_successes_and_failures() {
        let outcomes = vec![
            ok_outcome("chr/a.xc", "a"),
            failed_outcome("chr/b.xc", "b", "no exportable geometry"),
            ok_outcome("map/c.xc", "c"),
        ];
        let body = report_json(Path::new("out"), 5, Format::Gltf, &outcomes, true);

        assert_eq!(body["requested"], 5);
        assert_eq!(body["attempted"], 3);
        assert_eq!(body["exported"], 2);
        assert_eq!(body["failed"], 1);
        assert_eq!(body["cancelled"], true);
        assert_eq!(body["format"], "glTF");

        let entries = body["entries"].as_array().expect("entries array");
        assert_eq!(entries.len(), 3);
        assert_eq!(entries[0]["status"], "ok");
        assert_eq!(entries[0]["vertices"], 1200);
        assert_eq!(entries[1]["status"], "failed");
        assert_eq!(entries[1]["error"], "no exportable geometry");
        assert!(entries[1].get("vertices").is_none());
    }

    #[test]
    fn report_is_written_to_the_output_directory() {
        let dir = std::env::temp_dir().join(format!(
            "age_viewer_batch_report_{}_{}",
            std::process::id(),
            "a1"
        ));
        let _ = std::fs::remove_dir_all(&dir);

        let outcomes = vec![ok_outcome("chr/a.xc", "a")];
        let path = write_report(&dir, 1, Format::Obj, &outcomes, false).expect("report written");
        assert_eq!(path.file_name().unwrap(), REPORT_FILE_NAME);

        let text = std::fs::read_to_string(&path).expect("report readable");
        let parsed: Value = serde_json::from_str(&text).expect("report is valid JSON");
        assert_eq!(parsed["exported"], 1);
        assert_eq!(parsed["format"], "OBJ");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn an_empty_run_still_produces_a_consistent_report() {
        let body = report_json(Path::new("out"), 0, Format::Gltf, &[], false);
        assert_eq!(body["attempted"], 0);
        assert_eq!(body["exported"], 0);
        assert_eq!(body["failed"], 0);
        assert!(body["entries"].as_array().expect("array").is_empty());
    }
}
