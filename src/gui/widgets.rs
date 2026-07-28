//! Small shared painters and text helpers used by more than one panel.

use crate::scene::DecodeFailure;
use crate::theme;
use eframe::egui;
use std::sync::Arc;

/// Resolved body font for the current style.
pub fn body_font(ui: &egui::Ui) -> egui::FontId {
    egui::TextStyle::Body.resolve(ui.style())
}

/// Resolved monospace font for the current style; used for every number.
pub fn mono_font(ui: &egui::Ui) -> egui::FontId {
    egui::TextStyle::Monospace.resolve(ui.style())
}

/// Lay out one line of text, elided with an ellipsis when it exceeds `max_width`.
pub fn truncated_galley(
    ui: &egui::Ui,
    text: &str,
    font: egui::FontId,
    color: egui::Color32,
    max_width: f32,
) -> Arc<egui::text::Galley> {
    let mut job = egui::text::LayoutJob::single_section(
        text.to_owned(),
        egui::text::TextFormat::simple(font, color),
    );
    job.wrap = egui::text::TextWrapping::truncate_at_width(max_width.max(1.0));
    ui.painter().layout_job(job)
}

/// Single-line label that elides instead of wrapping, with the full text on hover.
pub fn truncating_label(ui: &mut egui::Ui, text: egui::RichText, full: &str) {
    let response = ui.add(egui::Label::new(text).truncate());
    if !full.is_empty() {
        response.on_hover_text(full);
    }
}

/// Shorten a long string for a one-line slot, keeping the tail (file name)
/// readable. Returns at most `max_chars` characters.
pub fn ellipsize_middle(text: &str, max_chars: usize) -> String {
    let total = text.chars().count();
    if total <= max_chars {
        return text.to_string();
    }
    if max_chars <= 1 {
        return "\u{2026}".to_string();
    }
    let budget = max_chars - 1;
    let head_len = budget / 3;
    let tail_len = budget - head_len;
    let head: String = text.chars().take(head_len).collect();
    let tail: String = text.chars().skip(total - tail_len).collect();
    format!("{head}\u{2026}{tail}")
}

/// Plain empty/idle state: one instruction line plus a de-emphasised hint.
pub fn empty_state(ui: &mut egui::Ui, headline: &str, hint: &str) {
    ui.add_space(8.0);
    ui.label(headline);
    if !hint.is_empty() {
        ui.label(theme::caption(hint));
    }
}

/// Section heading (stock egui strong text + separator).
pub fn section_header(ui: &mut egui::Ui, title: &str) {
    ui.add_space(2.0);
    ui.label(theme::section(title));
    ui.separator();
}

/// Two-column property row: key (secondary) / value (monospace).
pub fn property(ui: &mut egui::Ui, name: &str, value: &str) {
    ui.label(theme::label(name));
    truncating_label(ui, theme::mono(value), value);
    ui.end_row();
}

/// Decode failures listed with the error colour.
pub fn failure_list(ui: &mut egui::Ui, title: &str, failures: &[DecodeFailure]) {
    if failures.is_empty() {
        return;
    }
    ui.add_space(4.0);
    ui.colored_label(
        theme::STATUS_ERROR,
        format!("{title} ({})", failures.len()),
    );
    for failure in failures {
        let line = format!("{}: {}", failure.member, failure.error);
        let response = ui.add(
            egui::Label::new(
                egui::RichText::new(&line)
                    .small()
                    .color(theme::STATUS_ERROR),
            )
            .truncate(),
        );
        response.on_hover_text(&line);
    }
}

/// Two-tone backdrop so texture transparency is readable.
pub fn paint_checkerboard(painter: &egui::Painter, rect: egui::Rect, cell: f32) {
    painter.rect_filled(rect, 0.0, theme::BG_SUNKEN);
    let longest = rect.width().max(rect.height());
    let cell = cell.max(longest / 64.0).max(2.0);
    let cols = (rect.width() / cell).ceil() as i32;
    let rows = (rect.height() / cell).ceil() as i32;
    for row in 0..rows {
        for col in 0..cols {
            if (row + col) % 2 == 0 {
                continue;
            }
            let min = egui::pos2(
                rect.left() + col as f32 * cell,
                rect.top() + row as f32 * cell,
            );
            let max = egui::pos2(
                (min.x + cell).min(rect.right()),
                (min.y + cell).min(rect.bottom()),
            );
            painter.rect_filled(egui::Rect::from_min_max(min, max), 0.0, theme::BG_ROW_ALT);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn short_text_is_returned_unchanged() {
        assert_eq!(ellipsize_middle("chr/a.xc", 32), "chr/a.xc");
        assert_eq!(ellipsize_middle("", 8), "");
        assert_eq!(ellipsize_middle("12345678", 8), "12345678");
    }

    #[test]
    fn long_text_is_elided_to_the_budget_and_keeps_the_tail() {
        let path = "chr/ms001000/parts/ms001000_p000.xc";

        let short = ellipsize_middle(path, 20);
        assert_eq!(short.chars().count(), 20);
        assert!(short.contains('\u{2026}'));
        assert!(path.starts_with(short.split('\u{2026}').next().unwrap()));
        let tail = short.split('\u{2026}').nth(1).unwrap();
        assert!(path.ends_with(tail));
        assert!(tail.chars().count() > short.split('\u{2026}').next().unwrap().chars().count());

        let roomy = ellipsize_middle(path, 28);
        assert_eq!(roomy.chars().count(), 28);
        assert!(roomy.ends_with("ms001000_p000.xc"));
    }

    #[test]
    fn degenerate_budgets_collapse_to_an_ellipsis() {
        assert_eq!(ellipsize_middle("chr/a.xc", 0), "\u{2026}");
        assert_eq!(ellipsize_middle("chr/a.xc", 1), "\u{2026}");
        assert_eq!(ellipsize_middle("chr/a.xc", 2).chars().count(), 2);
    }

    #[test]
    fn elision_is_char_safe_for_multibyte_text() {
        let text = "chr/\u{30ac}\u{30f3}\u{30c0}\u{30e0}/\u{6a5f}\u{4f53}.xc";
        let short = ellipsize_middle(text, 8);
        assert_eq!(short.chars().count(), 8);
        assert!(short.ends_with(".xc"));
    }
}
