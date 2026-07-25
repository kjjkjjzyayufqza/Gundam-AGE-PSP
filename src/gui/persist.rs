//! Persisted UI state: last resource root, dialog directories, and view toggles.
//! Stored as JSON under the user config directory so the tool reopens where the
//! user left off instead of asking for the resource root every launch.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub const RECENT_ROOT_MAX: usize = 8;

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct PersistedState {
    /// Last scanned PSP resource root.
    pub resource_root: Option<PathBuf>,
    pub recent_roots: Vec<PathBuf>,
    /// Directory last used for glTF export.
    pub last_export_dir: Option<PathBuf>,
    /// Directory last used for the single-archive open dialog.
    pub last_open_dir: Option<PathBuf>,
    pub show_grid: Option<bool>,
    pub show_axes: Option<bool>,
    pub show_wireframe: Option<bool>,
    pub show_textures: Option<bool>,
    pub only_with_models: Option<bool>,
    pub only_with_textures: Option<bool>,
}

pub fn state_file_path() -> Option<PathBuf> {
    Some(dirs::config_dir()?.join("age_viewer").join("ui_state.json"))
}

pub fn load() -> PersistedState {
    let Some(path) = state_file_path() else {
        return PersistedState::default();
    };
    let Ok(text) = std::fs::read_to_string(&path) else {
        return PersistedState::default();
    };
    match serde_json::from_str(&text) {
        Ok(state) => state,
        Err(e) => {
            eprintln!("[gui] ignoring unreadable UI state {}: {e}", path.display());
            PersistedState::default()
        }
    }
}

pub fn save(state: &PersistedState) -> std::io::Result<()> {
    let Some(path) = state_file_path() else {
        return Ok(());
    };
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let text = serde_json::to_string_pretty(state)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
    std::fs::write(path, text)
}

/// Move `root` to the front of the recent list, de-duplicated and capped.
pub fn remember_root(recent: &mut Vec<PathBuf>, root: &PathBuf) {
    recent.retain(|p| p != root);
    recent.insert(0, root.clone());
    recent.truncate(RECENT_ROOT_MAX);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn remembering_a_root_moves_it_to_the_front_without_duplicates() {
        let mut recent = vec![PathBuf::from("a"), PathBuf::from("b")];
        remember_root(&mut recent, &PathBuf::from("b"));
        assert_eq!(recent, vec![PathBuf::from("b"), PathBuf::from("a")]);
        assert_eq!(recent.len(), 2);
    }

    #[test]
    fn recent_root_list_is_capped() {
        let mut recent = Vec::new();
        for i in 0..(RECENT_ROOT_MAX + 5) {
            remember_root(&mut recent, &PathBuf::from(i.to_string()));
        }
        assert_eq!(recent.len(), RECENT_ROOT_MAX);
        assert_eq!(recent[0], PathBuf::from((RECENT_ROOT_MAX + 4).to_string()));
    }
}
