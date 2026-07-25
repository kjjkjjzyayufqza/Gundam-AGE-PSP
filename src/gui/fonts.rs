//! Install a CJK-capable font so Japanese mesh names and localized OS error
//! strings render instead of tofu. AGE mesh/material names are mostly ASCII but
//! Shift-JIS names do appear, and Windows IO errors are localized.

use egui::{
    Context,
    epaint::text::{FontData, FontFamily, FontInsert, FontPriority, InsertFontFamily},
};
use std::path::PathBuf;

const CJK_FONT_ID: &str = "age-viewer-cjk";

pub fn install_cjk_fonts(ctx: &Context) {
    let Some((bytes, index)) = first_available_cjk_font() else {
        eprintln!(
            "[gui] no CJK-capable font found; Japanese names may render as missing glyphs"
        );
        return;
    };

    ctx.add_font(FontInsert::new(
        CJK_FONT_ID,
        FontData {
            font: std::borrow::Cow::Owned(bytes),
            index,
            tweak: Default::default(),
        },
        vec![
            InsertFontFamily {
                family: FontFamily::Proportional,
                priority: FontPriority::Lowest,
            },
            InsertFontFamily {
                family: FontFamily::Monospace,
                priority: FontPriority::Lowest,
            },
        ],
    ));
}

/// Index of the first face in the file that actually parses.
fn first_parseable_face(bytes: &[u8]) -> Option<u32> {
    match ttf_parser::fonts_in_collection(bytes) {
        Some(count) => (0..count.min(64)).find(|i| ttf_parser::Face::parse(bytes, *i).is_ok()),
        None => ttf_parser::Face::parse(bytes, 0).ok().map(|_| 0),
    }
}

fn first_available_cjk_font() -> Option<(Vec<u8>, u32)> {
    for path in candidate_font_paths() {
        if !path.is_file() {
            continue;
        }
        let Ok(bytes) = std::fs::read(&path) else {
            continue;
        };
        let Some(face) = first_parseable_face(&bytes) else {
            continue;
        };
        eprintln!("[gui] CJK font: {} (face {face})", path.display());
        return Some((bytes, face));
    }
    None
}

fn candidate_font_paths() -> Vec<PathBuf> {
    let mut paths = Vec::new();

    #[cfg(target_os = "windows")]
    {
        let fonts_dir = std::env::var("WINDIR")
            .map(|w| PathBuf::from(w).join("Fonts"))
            .unwrap_or_else(|_| PathBuf::from(r"C:\Windows\Fonts"));
        for name in ["msyh.ttc", "msgothic.ttc", "meiryo.ttc", "simhei.ttf", "simsun.ttc"] {
            paths.push(fonts_dir.join(name));
        }
    }

    #[cfg(target_os = "macos")]
    {
        paths.push(PathBuf::from("/System/Library/Fonts/PingFang.ttc"));
        paths.push(PathBuf::from(
            "/System/Library/Fonts/Supplemental/Songti.ttc",
        ));
    }

    #[cfg(target_os = "linux")]
    {
        for path in [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
        ] {
            paths.push(PathBuf::from(path));
        }
    }

    paths
}
