//! Entry point for the Gundam AGE PSP asset viewer.

// Release builds open without a console window; debug builds keep stderr logging.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() -> eframe::Result<()> {
    age_viewer::gui::run_native()
}
