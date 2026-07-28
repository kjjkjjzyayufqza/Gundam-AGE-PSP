//! Light chrome helpers on top of stock egui dark visuals.
//!
//! The viewer deliberately does not invent a custom design system. Surfaces,
//! widgets and selection colours come from [`egui::Visuals::dark`]. This module
//! only pins dark mode (so a light OS theme cannot flip the window white) and
//! offers a few status / formatting helpers used by the panels.

use egui::{Color32, FontFamily, FontId, TextStyle};

// Stock-adjacent neutrals used only where a painter needs an explicit fill
// (checkerboard, custom list rows). They track egui's dark palette closely.
pub const BG_SUNKEN: Color32 = Color32::from_rgb(0x1A, 0x1A, 0x1A);
pub const BG_ROW_ALT: Color32 = Color32::from_rgb(0x2A, 0x2A, 0x2A);
pub const BG_HOVER: Color32 = Color32::from_rgb(0x3A, 0x3A, 0x3A);
pub const BG_SELECTION: Color32 = Color32::from_rgb(0x2F, 0x4A, 0x6A);

pub const TEXT_PRIMARY: Color32 = Color32::from_rgb(0xF0, 0xF0, 0xF0);
pub const TEXT_SECONDARY: Color32 = Color32::from_rgb(0xB0, 0xB0, 0xB0);
pub const TEXT_MUTED: Color32 = Color32::from_rgb(0x8A, 0x8A, 0x8A);

pub const STATUS_OK: Color32 = Color32::from_rgb(0x7A, 0xC0, 0x7A);
pub const STATUS_WARN: Color32 = Color32::from_rgb(0xE0, 0xB0, 0x50);
pub const STATUS_ERROR: Color32 = Color32::from_rgb(0xE0, 0x70, 0x70);

/// Viewport clear colour (linear RGB), matching a stock dark panel.
pub const VIEWPORT_CLEAR: [f64; 3] = [0.10, 0.10, 0.10];

/// Pin dark mode and apply stock egui dark visuals to every theme slot.
///
/// eframe keeps a separate style per theme preference. Without writing both
/// slots, a light OS preference can still resolve light panels under dark text.
pub fn apply(ctx: &egui::Context) {
    ctx.options_mut(|options| options.theme_preference = egui::ThemePreference::Dark);
    ctx.set_theme(egui::ThemePreference::Dark);
    ctx.all_styles_mut(style_egui_dark);
}

fn style_egui_dark(style: &mut egui::Style) {
    style.visuals = egui::Visuals::dark();

    // Slightly denser tool layout; otherwise leave egui defaults alone.
    style.spacing.item_spacing = egui::vec2(8.0, 4.0);
    style.spacing.button_padding = egui::vec2(8.0, 3.0);
    style.spacing.indent = 18.0;
    style.spacing.interact_size.y = 22.0;

    style.text_styles.insert(
        TextStyle::Heading,
        FontId::new(16.0, FontFamily::Proportional),
    );
    style.text_styles.insert(
        TextStyle::Body,
        FontId::new(13.0, FontFamily::Proportional),
    );
    style.text_styles.insert(
        TextStyle::Button,
        FontId::new(13.0, FontFamily::Proportional),
    );
    style.text_styles.insert(
        TextStyle::Small,
        FontId::new(11.0, FontFamily::Proportional),
    );
    style.text_styles.insert(
        TextStyle::Monospace,
        FontId::new(12.0, FontFamily::Monospace),
    );
}

/// Monospace run for numbers, hashes, sizes and paths.
pub fn mono(text: impl Into<String>) -> egui::RichText {
    egui::RichText::new(text).monospace()
}

/// Monospace run at full contrast.
pub fn mono_strong(text: impl Into<String>) -> egui::RichText {
    egui::RichText::new(text).monospace().strong()
}

/// Secondary label text.
pub fn label(text: impl Into<String>) -> egui::RichText {
    egui::RichText::new(text).color(TEXT_SECONDARY)
}

/// Small caption text.
pub fn caption(text: impl Into<String>) -> egui::RichText {
    egui::RichText::new(text).small().color(TEXT_MUTED)
}

/// Section heading inside a panel (plain strong text, no custom chrome).
pub fn section(text: impl Into<String>) -> egui::RichText {
    egui::RichText::new(text).strong()
}

/// Format a byte count for display, e.g. `1.4 MB`.
pub fn format_bytes(bytes: usize) -> String {
    const KB: f64 = 1024.0;
    const MB: f64 = KB * 1024.0;
    let bytes_f = bytes as f64;
    if bytes_f >= MB {
        format!("{:.1} MB", bytes_f / MB)
    } else if bytes_f >= KB {
        format!("{:.1} KB", bytes_f / KB)
    } else {
        format!("{bytes} B")
    }
}

/// Group thousands with a thin separator, e.g. `23,880`.
pub fn format_count(value: usize) -> String {
    let digits = value.to_string();
    let mut out = String::with_capacity(digits.len() + digits.len() / 3);
    for (i, ch) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(ch);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn byte_formatting_switches_units() {
        assert_eq!(format_bytes(512), "512 B");
        assert_eq!(format_bytes(2048), "2.0 KB");
        assert_eq!(format_bytes(3 * 1024 * 1024), "3.0 MB");
    }

    #[test]
    fn count_formatting_groups_thousands() {
        assert_eq!(format_count(7), "7");
        assert_eq!(format_count(1234), "1,234");
        assert_eq!(format_count(23880), "23,880");
        assert_eq!(format_count(1000000), "1,000,000");
    }

    #[test]
    fn applying_the_theme_pins_dark_mode_regardless_of_system_preference() {
        let ctx = egui::Context::default();
        ctx.set_theme(egui::ThemePreference::Light);
        apply(&ctx);

        assert_eq!(
            ctx.options(|o| o.theme_preference),
            egui::ThemePreference::Dark,
            "theme preference must be pinned so the OS cannot flip it"
        );

        let visuals = ctx.style().visuals.clone();
        assert!(visuals.dark_mode, "resolved visuals must be dark");
    }

    #[test]
    fn both_theme_slots_receive_dark_visuals() {
        let ctx = egui::Context::default();
        apply(&ctx);
        for theme in [egui::Theme::Dark, egui::Theme::Light] {
            let style = ctx.style_of(theme);
            assert!(
                style.visuals.dark_mode,
                "{theme:?} slot is not dark"
            );
        }
    }
}
