//! Search result caching and the virtualized archive list row.
//!
//! `filter_records` over 4,500 records costs ~33 us, which is cheap but still
//! pointless to repeat 60 times a second, so results are cached and only
//! recomputed when the filter or the underlying record list actually changed.

use super::widgets;
use crate::index::{ArchiveRecord, SearchFilter, filter_records};
use crate::theme;
use eframe::egui;

/// Height of one result row, in points. Fixed so the list can be virtualized.
pub const ROW_HEIGHT: f32 = 21.0;

/// Everything that can invalidate a cached result set.
#[derive(Clone, Debug, PartialEq, Eq)]
struct CacheKey {
    /// Bumped by the app whenever `records` is replaced.
    revision: u64,
    query: String,
    only_with_models: bool,
    only_with_textures: bool,
    category: Option<String>,
}

impl CacheKey {
    fn new(revision: u64, filter: &SearchFilter) -> Self {
        Self {
            revision,
            query: filter.query.clone(),
            only_with_models: filter.only_with_models,
            only_with_textures: filter.only_with_textures,
            category: filter.category.clone(),
        }
    }
}

/// Cached indices of the records matching the current filter.
#[derive(Default)]
pub struct ResultCache {
    key: Option<CacheKey>,
    matches: Vec<usize>,
    #[cfg(test)]
    recomputes: u64,
}

impl ResultCache {
    pub fn matches(&self) -> &[usize] {
        &self.matches
    }

    pub fn len(&self) -> usize {
        self.matches.len()
    }

    /// Recompute only when the filter or the record revision changed.
    /// Returns `true` when the result set was rebuilt.
    pub fn refresh(&mut self, records: &[ArchiveRecord], filter: &SearchFilter, revision: u64) -> bool {
        let key = CacheKey::new(revision, filter);
        if self.key.as_ref() == Some(&key) {
            return false;
        }
        self.matches = filter_records(records, filter);
        self.key = Some(key);
        #[cfg(test)]
        {
            self.recomputes += 1;
        }
        true
    }

    /// Drop the cache so the next `refresh` rebuilds it.
    pub fn invalidate(&mut self) {
        self.key = None;
        self.matches.clear();
    }

    /// How many times the filter has actually run; used by tests.
    #[cfg(test)]
    pub fn recomputes(&self) -> u64 {
        self.recomputes
    }
}

/// `"312 of 4,529 archives"`, with grouped numbers.
pub fn match_summary(matched: usize, total: usize) -> String {
    format!(
        "{} of {} archives",
        theme::format_count(matched),
        theme::format_count(total)
    )
}

/// Directory part of a relative key, without the file name.
pub fn directory_of(relative: &str) -> &str {
    match relative.rfind('/') {
        Some(cut) => &relative[..cut],
        None => "",
    }
}

/// Paint one result row and return its interaction response.
///
/// Layout is fixed: name on the left, directory next to it (elided), model and
/// texture counts right-aligned in monospace.
pub fn row(
    ui: &mut egui::Ui,
    record: &ArchiveRecord,
    row_index: usize,
    selected: bool,
) -> egui::Response {
    let width = ui.available_width();
    let (rect, response) =
        ui.allocate_exact_size(egui::vec2(width, ROW_HEIGHT), egui::Sense::click());

    if !ui.is_rect_visible(rect) {
        return response;
    }

    let painter = ui.painter();
    let radius = egui::CornerRadius::same(theme::RADIUS_CONTROL);
    if selected {
        painter.rect_filled(rect, radius, theme::ACCENT_SELECTION);
        painter.rect_stroke(
            rect,
            radius,
            egui::Stroke::new(1.0_f32, theme::ACCENT),
            egui::StrokeKind::Inside,
        );
    } else if response.hovered() {
        painter.rect_filled(rect, radius, theme::BG_ELEVATED);
    } else if row_index % 2 == 1 {
        painter.rect_filled(rect, radius, theme::BG_ROW_ALT);
    }

    let body = widgets::body_font(ui);
    let mono = widgets::mono_font(ui);
    let inner = rect.shrink2(egui::vec2(6.0, 0.0));

    // Counts first: they are fixed width, so the name and path get the rest.
    let counts = format!("{:>3}P {:>3}T", record.prm_count, record.xi_count);
    let counts_galley = widgets::truncated_galley(
        ui,
        &counts,
        mono.clone(),
        theme::TEXT_SECONDARY,
        inner.width().max(1.0),
    );
    let counts_width = counts_galley.size().x;
    let counts_pos = egui::pos2(
        inner.right() - counts_width,
        inner.center().y - counts_galley.size().y * 0.5,
    );

    let text_room = (inner.width() - counts_width - 8.0).max(24.0);
    let name_width = (text_room * 0.62).max(24.0);
    let name_galley = widgets::truncated_galley(
        ui,
        &record.file_name,
        body.clone(),
        theme::TEXT_PRIMARY,
        name_width,
    );
    let name_pos = egui::pos2(
        inner.left(),
        inner.center().y - name_galley.size().y * 0.5,
    );

    let directory = directory_of(&record.relative);
    let dir_left = inner.left() + name_galley.size().x + 8.0;
    let dir_width = (counts_pos.x - 8.0 - dir_left).max(0.0);

    let painter = ui.painter();
    painter.galley(name_pos, name_galley, theme::TEXT_PRIMARY);
    painter.galley(counts_pos, counts_galley, theme::TEXT_SECONDARY);
    if !directory.is_empty() && dir_width > 12.0 {
        let dir_galley =
            widgets::truncated_galley(ui, directory, mono, theme::TEXT_SECONDARY, dir_width);
        let dir_pos = egui::pos2(dir_left, inner.center().y - dir_galley.size().y * 0.5);
        ui.painter()
            .galley(dir_pos, dir_galley, theme::TEXT_SECONDARY);
    }

    response
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn record(relative: &str, prm: usize, xi: usize) -> ArchiveRecord {
        let relative = relative.to_string();
        ArchiveRecord {
            path: PathBuf::from(&relative),
            search_key: relative.to_lowercase(),
            category: relative
                .split_once('/')
                .map(|(head, _)| head.to_string())
                .unwrap_or_else(|| "(root)".to_string()),
            file_name: relative
                .rsplit('/')
                .next()
                .unwrap_or(relative.as_str())
                .to_string(),
            member_count: prm + xi,
            prm_count: prm,
            xi_count: xi,
            mbn_count: 0,
            size: 2048,
            relative,
        }
    }

    fn sample() -> Vec<ArchiveRecord> {
        vec![
            record("chr/ms001000/ms001000_p000.xc", 6, 5),
            record("chr/ms002000/ms002000_p000.xc", 4, 0),
            record("map/e1101.xc", 20, 9),
        ]
    }

    #[test]
    fn first_refresh_computes_and_repeats_do_not() {
        let records = sample();
        let filter = SearchFilter::default();
        let mut cache = ResultCache::default();

        assert!(cache.refresh(&records, &filter, 1));
        assert_eq!(cache.matches(), &[0, 1, 2]);
        assert_eq!(cache.recomputes(), 1);

        for _ in 0..30 {
            assert!(!cache.refresh(&records, &filter, 1));
        }
        assert_eq!(cache.recomputes(), 1, "an unchanged filter must not refilter");
    }

    #[test]
    fn every_filter_field_invalidates_the_cache() {
        let records = sample();
        let mut cache = ResultCache::default();
        let mut filter = SearchFilter::default();
        cache.refresh(&records, &filter, 1);

        filter.query = "chr".to_string();
        assert!(cache.refresh(&records, &filter, 1));
        assert_eq!(cache.matches(), &[0, 1]);

        filter.only_with_textures = true;
        assert!(cache.refresh(&records, &filter, 1));
        assert_eq!(cache.matches(), &[0]);

        filter.only_with_models = true;
        assert!(cache.refresh(&records, &filter, 1));
        assert_eq!(cache.matches(), &[0]);

        filter.category = Some("map".to_string());
        assert!(cache.refresh(&records, &filter, 1));
        assert!(cache.matches().is_empty());

        assert_eq!(cache.recomputes(), 5);
    }

    #[test]
    fn a_new_record_revision_invalidates_an_identical_filter() {
        let mut records = sample();
        let filter = SearchFilter::default();
        let mut cache = ResultCache::default();

        cache.refresh(&records, &filter, 1);
        assert_eq!(cache.len(), 3);

        records.push(record("map/e1102.xc", 1, 1));
        assert!(cache.refresh(&records, &filter, 2));
        assert_eq!(cache.len(), 4);
    }

    #[test]
    fn invalidate_forces_the_next_refresh() {
        let records = sample();
        let filter = SearchFilter::default();
        let mut cache = ResultCache::default();

        cache.refresh(&records, &filter, 7);
        cache.invalidate();
        assert!(cache.matches().is_empty());
        assert!(cache.refresh(&records, &filter, 7));
        assert_eq!(cache.recomputes(), 2);
    }

    #[test]
    fn match_summary_groups_thousands() {
        assert_eq!(match_summary(312, 4529), "312 of 4,529 archives");
        assert_eq!(match_summary(0, 0), "0 of 0 archives");
        assert_eq!(match_summary(1, 1), "1 of 1 archives");
    }

    #[test]
    fn directory_of_drops_the_file_name() {
        assert_eq!(directory_of("chr/ms001000/a.xc"), "chr/ms001000");
        assert_eq!(directory_of("top.xc"), "");
        assert_eq!(directory_of(""), "");
    }
}
