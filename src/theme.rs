//! Design tokens for the viewer chrome.
//!
//! Direction: dense professional tooling (reference family: Blender, Substance,
//! RenderDoc). The chrome is a neutral off-black frame that recedes so game
//! textures in the viewport carry the only saturated colour on screen.
//!
//! Locked decisions, applied everywhere:
//! - One accent (amber). No second accent, no gradients, no glows.
//! - Never pure black or pure white; neutral ramp only.
//! - Two corner radii: `RADIUS_CONTROL` for widgets, `RADIUS_PANEL` for containers.
//! - Monospace for every number, hash, size and path.
//! - All body/label colours clear WCAG AA against their own surface.

use egui::{Color32, CornerRadius, FontFamily, FontId, Stroke, TextStyle};

// Neutral ramp. Cool off-black, no pure #000.
pub const BG_BASE: Color32 = Color32::from_rgb(0x17, 0x18, 0x1A);
pub const BG_PANEL: Color32 = Color32::from_rgb(0x1E, 0x20, 0x23);
pub const BG_ELEVATED: Color32 = Color32::from_rgb(0x26, 0x2A, 0x2E);
pub const BG_SUNKEN: Color32 = Color32::from_rgb(0x13, 0x14, 0x16);
pub const BG_ROW_ALT: Color32 = Color32::from_rgb(0x22, 0x24, 0x28);

pub const STROKE_SUBTLE: Color32 = Color32::from_rgb(0x2E, 0x32, 0x36);
pub const STROKE_STRONG: Color32 = Color32::from_rgb(0x3C, 0x41, 0x47);

/// Widget fill on hover.
pub const BG_HOVER: Color32 = Color32::from_rgb(0x30, 0x35, 0x3A);
/// Widget fill while pressed; warm-shifted so it reads as related to the accent.
pub const BG_ACTIVE: Color32 = Color32::from_rgb(0x3A, 0x35, 0x2C);

// Text ramp. Every tone is verified against every surface by the theme tests:
// primary and secondary clear AA (4.5:1), de-emphasised tones clear 3:1.
pub const TEXT_PRIMARY: Color32 = Color32::from_rgb(0xE6, 0xE8, 0xEA);
pub const TEXT_SECONDARY: Color32 = Color32::from_rgb(0xA2, 0xA8, 0xAE);
pub const TEXT_MUTED: Color32 = Color32::from_rgb(0x85, 0x8C, 0x93);

// Single locked accent.
pub const ACCENT: Color32 = Color32::from_rgb(0xE0, 0xA2, 0x52);
pub const ACCENT_HOVER: Color32 = Color32::from_rgb(0xEF, 0xB4, 0x68);
pub const ACCENT_PRESSED: Color32 = Color32::from_rgb(0xC8, 0x8C, 0x3F);
/// Accent-tinted surface for selected rows; kept dark enough that row text
/// clears WCAG AA against it rather than relying on a saturated fill.
pub const ACCENT_SELECTION: Color32 = Color32::from_rgb(0x45, 0x38, 0x20);

pub const STATUS_OK: Color32 = Color32::from_rgb(0x6F, 0xB2, 0x7E);
pub const STATUS_WARN: Color32 = Color32::from_rgb(0xD9, 0xA4, 0x41);
pub const STATUS_ERROR: Color32 = Color32::from_rgb(0xD8, 0x72, 0x68);

pub const RADIUS_CONTROL: u8 = 4;
pub const RADIUS_PANEL: u8 = 6;

/// Viewport clear colour; cool neutral so amber chrome never competes with it.
pub const VIEWPORT_CLEAR: [f64; 3] = [0.086, 0.094, 0.102];

/// Apply the token set to an egui context.
///
/// Two things here are load-bearing:
///
/// 1. The theme preference is pinned to dark. eframe otherwise follows the OS
///    theme, and egui stores a *separate* style per theme, so a light-mode OS
///    would resolve to egui's light visuals and paint white panels underneath
///    this palette's light text.
/// 2. The style is written to every theme slot, so nothing that re-resolves the
///    preference at runtime can drop us back onto an unstyled default.
///
/// The palette starts from egui's own dark visuals and overrides surfaces, the
/// accent and the radii only. Widget foreground strokes are deliberately left
/// as egui computes them, which keeps label contrast correct by construction
/// instead of depending on every call site picking the right colour.
pub fn apply(ctx: &egui::Context) {
    ctx.options_mut(|options| options.theme_preference = egui::ThemePreference::Dark);
    ctx.set_theme(egui::ThemePreference::Dark);
    ctx.all_styles_mut(style_dark);
}

fn style_dark(style: &mut egui::Style) {
    let control = CornerRadius::same(RADIUS_CONTROL);
    let panel = CornerRadius::same(RADIUS_PANEL);

    let mut visuals = egui::Visuals::dark();

    // Surfaces: one cool neutral ramp, never pure black.
    visuals.panel_fill = BG_PANEL;
    visuals.window_fill = BG_ELEVATED;
    visuals.extreme_bg_color = BG_SUNKEN;
    visuals.faint_bg_color = BG_ROW_ALT;
    visuals.code_bg_color = BG_SUNKEN;
    visuals.window_stroke = Stroke::new(1.0_f32, STROKE_STRONG);
    visuals.window_corner_radius = panel;
    visuals.menu_corner_radius = panel;

    // Single accent, used for selection, focus and the primary action only.
    visuals.selection.bg_fill = ACCENT_SELECTION;
    visuals.selection.stroke = Stroke::new(1.0_f32, ACCENT);
    visuals.hyperlink_color = ACCENT;
    visuals.warn_fg_color = STATUS_WARN;
    visuals.error_fg_color = STATUS_ERROR;

    // Widget surfaces only. `fg_stroke` stays at egui's dark defaults so text
    // is guaranteed readable on each of these fills.
    visuals.widgets.noninteractive.bg_fill = BG_PANEL;
    visuals.widgets.noninteractive.weak_bg_fill = BG_PANEL;
    visuals.widgets.noninteractive.bg_stroke = Stroke::new(1.0_f32, STROKE_SUBTLE);
    visuals.widgets.noninteractive.corner_radius = panel;

    visuals.widgets.inactive.bg_fill = BG_ELEVATED;
    visuals.widgets.inactive.weak_bg_fill = BG_ELEVATED;
    visuals.widgets.inactive.bg_stroke = Stroke::new(1.0_f32, STROKE_SUBTLE);
    visuals.widgets.inactive.corner_radius = control;

    visuals.widgets.hovered.bg_fill = BG_HOVER;
    visuals.widgets.hovered.weak_bg_fill = BG_HOVER;
    visuals.widgets.hovered.bg_stroke = Stroke::new(1.0_f32, STROKE_STRONG);
    visuals.widgets.hovered.corner_radius = control;

    // Pressed state carries the accent on the border, not a coloured fill.
    visuals.widgets.active.bg_fill = BG_ACTIVE;
    visuals.widgets.active.weak_bg_fill = BG_ACTIVE;
    visuals.widgets.active.bg_stroke = Stroke::new(1.0_f32, ACCENT);
    visuals.widgets.active.corner_radius = control;

    visuals.widgets.open.bg_fill = BG_ELEVATED;
    visuals.widgets.open.weak_bg_fill = BG_ELEVATED;
    visuals.widgets.open.bg_stroke = Stroke::new(1.0_f32, STROKE_STRONG);
    visuals.widgets.open.corner_radius = control;

    style.visuals = visuals;

    // Density 7: tight but breathable.
    style.spacing.item_spacing = egui::vec2(8.0, 6.0);
    style.spacing.button_padding = egui::vec2(10.0, 5.0);
    style.spacing.menu_margin = egui::Margin::same(6);
    style.spacing.indent = 16.0;
    style.spacing.interact_size.y = 24.0;
    style.spacing.scroll.bar_width = 10.0;

    style.text_styles.insert(
        TextStyle::Heading,
        FontId::new(15.0, FontFamily::Proportional),
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
    egui::RichText::new(text).monospace().color(TEXT_SECONDARY)
}

/// Monospace run at full contrast, for values the user is reading closely.
pub fn mono_strong(text: impl Into<String>) -> egui::RichText {
    egui::RichText::new(text).monospace().color(TEXT_PRIMARY)
}

/// Secondary label text.
pub fn label(text: impl Into<String>) -> egui::RichText {
    egui::RichText::new(text).color(TEXT_SECONDARY)
}

/// Small caption text; never used for information the user must read.
pub fn caption(text: impl Into<String>) -> egui::RichText {
    egui::RichText::new(text)
        .small()
        .color(TEXT_MUTED)
}

/// Section heading inside a panel.
pub fn section(text: impl Into<String>) -> egui::RichText {
    egui::RichText::new(text)
        .color(TEXT_PRIMARY)
        .strong()
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

/// WCAG relative luminance of an opaque colour.
fn relative_luminance(color: Color32) -> f32 {
    fn channel(value: u8) -> f32 {
        let v = value as f32 / 255.0;
        if v <= 0.039_28 {
            v / 12.92
        } else {
            ((v + 0.055) / 1.055).powf(2.4)
        }
    }
    0.2126 * channel(color.r()) + 0.7152 * channel(color.g()) + 0.0722 * channel(color.b())
}

/// WCAG contrast ratio between two opaque colours, from 1.0 to 21.0.
///
/// Used by the theme tests to prove no token pairing is unreadable. The viewer
/// previously shipped light text over egui's light surfaces, which this catches.
pub fn contrast_ratio(a: Color32, b: Color32) -> f32 {
    let (la, lb) = (relative_luminance(a), relative_luminance(b));
    let (lighter, darker) = if la >= lb { (la, lb) } else { (lb, la) };
    (lighter + 0.05) / (darker + 0.05)
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
    fn contrast_ratio_matches_known_extremes() {
        let white = Color32::from_rgb(255, 255, 255);
        let black = Color32::from_rgb(0, 0, 0);
        assert!((contrast_ratio(white, black) - 21.0).abs() < 0.05);
        assert!((contrast_ratio(white, white) - 1.0).abs() < 0.01);
    }

    /// Every text token must clear WCAG AA on every surface it can land on.
    #[test]
    fn text_tokens_are_readable_on_every_surface() {
        let surfaces = [
            ("BG_BASE", BG_BASE),
            ("BG_PANEL", BG_PANEL),
            ("BG_ELEVATED", BG_ELEVATED),
            ("BG_SUNKEN", BG_SUNKEN),
            ("BG_ROW_ALT", BG_ROW_ALT),
            ("BG_HOVER", BG_HOVER),
            ("BG_ACTIVE", BG_ACTIVE),
            ("ACCENT_SELECTION", ACCENT_SELECTION),
        ];
        let readable = [
            ("TEXT_PRIMARY", TEXT_PRIMARY, 4.5),
            ("TEXT_SECONDARY", TEXT_SECONDARY, 4.5),
            // Captions are de-emphasised, so they only need large-text AA.
            ("TEXT_MUTED", TEXT_MUTED, 3.0),
            ("STATUS_OK", STATUS_OK, 3.0),
            ("STATUS_WARN", STATUS_WARN, 3.0),
            ("STATUS_ERROR", STATUS_ERROR, 3.0),
            ("ACCENT", ACCENT, 3.0),
        ];

        for (surface_name, surface) in surfaces {
            for (text_name, text, minimum) in readable {
                let ratio = contrast_ratio(text, surface);
                assert!(
                    ratio >= minimum,
                    "{text_name} on {surface_name} is {ratio:.2}:1, below {minimum}:1"
                );
            }
        }
    }

    /// The accent-filled primary button paints `BG_BASE` text on `ACCENT`.
    #[test]
    fn the_accent_button_pairing_is_readable() {
        let ratio = contrast_ratio(BG_BASE, ACCENT);
        assert!(ratio >= 4.5, "accent button text is only {ratio:.2}:1");
    }

    /// Guards the reported bug: a light-mode OS must not reach the widgets.
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
        assert_eq!(visuals.panel_fill, BG_PANEL);
        assert_eq!(visuals.window_fill, BG_ELEVATED);

        // The surface a plain label sits on must contrast with the text egui
        // picked for it, whichever theme slot got resolved.
        let label = visuals.widgets.noninteractive.fg_stroke.color;
        let ratio = contrast_ratio(label, visuals.panel_fill);
        assert!(
            ratio >= 4.5,
            "default label contrast is {ratio:.2}:1 on the panel fill"
        );
    }

    /// The style is written to every theme slot, not just the active one.
    #[test]
    fn both_theme_slots_receive_the_dark_palette() {
        let ctx = egui::Context::default();
        apply(&ctx);
        for theme in [egui::Theme::Dark, egui::Theme::Light] {
            let style = ctx.style_of(theme);
            assert_eq!(
                style.visuals.panel_fill, BG_PANEL,
                "{theme:?} slot kept an unstyled panel fill"
            );
            assert!(style.visuals.dark_mode, "{theme:?} slot is not dark");
        }
    }
}
