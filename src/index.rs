//! Background indexing of an unpacked PSP resource tree, plus search filtering.
//!
//! INTERFACE CONTRACT - the signatures below are fixed. Implementations may add
//! private fields and helpers but must not change these public shapes.
//!
//! The tree holds roughly 4,500 XPCK archives, so scanning runs on a worker
//! thread, reports progress, and can be cancelled.

use std::path::{Component, Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::Receiver;
use std::time::{Duration, Instant};

/// One indexed archive.
#[derive(Clone, Debug)]
pub struct ArchiveRecord {
    pub path: PathBuf,
    /// Path relative to the scanned root, using forward slashes.
    pub relative: String,
    pub file_name: String,
    /// Top-level resource area: `chr`, `map`, `eff`, `btl`, `evt`, ...
    pub category: String,
    pub member_count: usize,
    pub prm_count: usize,
    pub xi_count: usize,
    pub mbn_count: usize,
    pub size: u64,
    /// Lowercased `relative`, precomputed so search does not allocate per frame.
    pub search_key: String,
}

impl ArchiveRecord {
    pub fn has_models(&self) -> bool {
        self.prm_count > 0
    }

    pub fn has_textures(&self) -> bool {
        self.xi_count > 0
    }
}

#[derive(Clone, Debug, Default)]
pub struct ScanProgress {
    pub files_seen: usize,
    pub archives_found: usize,
    pub errors: usize,
    /// Most recent archive path, for the status line.
    pub current: String,
}

#[derive(Debug)]
pub enum ScanMessage {
    Progress(ScanProgress),
    /// Scan finished normally; carries every record found.
    Finished(Vec<ArchiveRecord>),
    Cancelled,
    Failed(String),
}

/// Handle to a running scan. Dropping it does not stop the worker; call [`ScanHandle::cancel`].
pub struct ScanHandle {
    pub receiver: Receiver<ScanMessage>,
    cancel: Arc<AtomicBool>,
}

impl ScanHandle {
    pub fn cancel(&self) {
        self.cancel.store(true, std::sync::atomic::Ordering::Relaxed);
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancel.load(std::sync::atomic::Ordering::Relaxed)
    }
}

/// Fallback category for archives sitting directly in the scanned root.
const ROOT_CATEGORY: &str = "(root)";

/// Progress is throttled so the UI channel is not flooded: at most one update
/// per [`PROGRESS_INTERVAL`], and at least one every [`PROGRESS_FILE_STRIDE`]
/// files, plus a final update when the walk ends.
const PROGRESS_INTERVAL: Duration = Duration::from_millis(100);
const PROGRESS_FILE_STRIDE: usize = 64;

/// Start scanning `root` on a worker thread.
pub fn spawn_scan(root: PathBuf) -> ScanHandle {
    let (sender, receiver) = std::sync::mpsc::channel();
    let cancel = Arc::new(AtomicBool::new(false));
    let worker_cancel = Arc::clone(&cancel);

    std::thread::spawn(move || {
        // The root itself is the only fatal problem; everything below it is
        // skipped individually so one bad file cannot kill the scan.
        if !root.is_dir() {
            let reason = if root.exists() {
                format!("{} is not a directory", root.display())
            } else {
                format!("{} does not exist", root.display())
            };
            // The UI may already be gone; a dropped receiver is not an error.
            let _ = sender.send(ScanMessage::Failed(reason));
            return;
        }

        let progress_sender = sender.clone();
        let mut on_progress = move |progress: ScanProgress| {
            let _ = progress_sender.send(ScanMessage::Progress(progress));
        };
        let records = scan_root(&root, &worker_cancel, &mut on_progress);

        let terminal = if worker_cancel.load(Ordering::Relaxed) {
            ScanMessage::Cancelled
        } else {
            ScanMessage::Finished(records)
        };
        let _ = sender.send(terminal);
    });

    ScanHandle { receiver, cancel }
}

/// Scan synchronously; used by tests and by the indexing worker.
pub fn scan_root(
    root: &Path,
    cancel: &AtomicBool,
    on_progress: &mut dyn FnMut(ScanProgress),
) -> Vec<ArchiveRecord> {
    let mut records: Vec<ArchiveRecord> = Vec::new();
    let mut progress = ScanProgress::default();

    if !root.is_dir() {
        on_progress(progress);
        return records;
    }

    let mut last_emit = Instant::now();
    let mut since_emit = 0usize;
    // Explicit stack rather than recursion: the tree is deep and a symlink
    // chain must not risk the worker thread's stack.
    let mut pending: Vec<PathBuf> = vec![root.to_path_buf()];

    'walk: while let Some(dir) = pending.pop() {
        if cancel.load(Ordering::Relaxed) {
            break;
        }
        // Unreadable directories (permissions, races) are skipped, not fatal.
        let Ok(entries) = std::fs::read_dir(&dir) else {
            continue;
        };

        for entry in entries {
            if cancel.load(Ordering::Relaxed) {
                break 'walk;
            }
            let Ok(entry) = entry else { continue };
            let Ok(kind) = entry.file_type() else { continue };
            let path = entry.path();

            if kind.is_dir() {
                pending.push(path);
                continue;
            }
            // Symlinks are inspected as files but never traversed, so the walk
            // cannot loop on a directory link.
            if !kind.is_file()
                && !std::fs::metadata(&path)
                    .map(|meta| meta.is_file())
                    .unwrap_or(false)
            {
                continue;
            }

            progress.files_seen += 1;
            since_emit += 1;

            if has_archive_extension(&path) && crate::xpck::is_archive_file(&path) {
                match index_archive(root, &path) {
                    Some(record) => {
                        progress.archives_found += 1;
                        progress.current = record.relative.clone();
                        records.push(record);
                    }
                    // Malformed member table: count it and keep going.
                    None => progress.errors += 1,
                }
            }

            let now = Instant::now();
            if since_emit >= PROGRESS_FILE_STRIDE
                || now.duration_since(last_emit) >= PROGRESS_INTERVAL
            {
                on_progress(progress.clone());
                since_emit = 0;
                last_emit = now;
            }
        }
    }

    // Stable list order across runs regardless of directory iteration order.
    records.sort_by(|a, b| a.relative.cmp(&b.relative));
    on_progress(progress);
    records
}

/// True when the lowercase extension is one of [`crate::xpck::ARCHIVE_EXTENSIONS`].
fn has_archive_extension(path: &Path) -> bool {
    let Some(ext) = path.extension().and_then(|ext| ext.to_str()) else {
        return false;
    };
    crate::xpck::ARCHIVE_EXTENSIONS
        .iter()
        .any(|known| ext.eq_ignore_ascii_case(known))
}

/// Extension of an archive member name, without the dot.
fn member_extension(name: &str) -> Option<&str> {
    Path::new(name).extension().and_then(|ext| ext.to_str())
}

/// Build a record for a confirmed archive. `None` when the member table cannot
/// be parsed; the caller counts that as an error and moves on.
fn index_archive(root: &Path, path: &Path) -> Option<ArchiveRecord> {
    // Partial read of header + entry table + name table only, which is what
    // keeps a 4,500-archive scan cheap.
    let members = crate::xpck::scan_members(path).ok()?;

    let mut prm_count = 0usize;
    let mut xi_count = 0usize;
    let mut mbn_count = 0usize;
    for (name, _size) in &members {
        let Some(ext) = member_extension(name) else {
            continue;
        };
        if ext.eq_ignore_ascii_case("prm") {
            prm_count += 1;
        } else if ext.eq_ignore_ascii_case("xi") {
            xi_count += 1;
        } else if ext.eq_ignore_ascii_case("mbn") {
            mbn_count += 1;
        }
    }

    let relative = relative_key(root, path);
    let file_name = path
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| relative.clone());

    Some(ArchiveRecord {
        search_key: relative.to_lowercase(),
        category: category_of(&relative),
        member_count: members.len(),
        prm_count,
        xi_count,
        mbn_count,
        size: std::fs::metadata(path).map(|meta| meta.len()).unwrap_or(0),
        path: path.to_path_buf(),
        file_name,
        relative,
    })
}

/// `path` relative to `root`, with forward slashes.
fn relative_key(root: &Path, path: &Path) -> String {
    let tail = path.strip_prefix(root).unwrap_or(path);
    let mut out = String::new();
    for component in tail.components() {
        if let Component::Normal(part) = component {
            let piece = part.to_string_lossy();
            if piece.is_empty() {
                continue;
            }
            if !out.is_empty() {
                out.push('/');
            }
            out.push_str(&piece);
        }
    }
    if out.is_empty() {
        out = path
            .file_name()
            .map(|name| name.to_string_lossy().into_owned())
            .unwrap_or_default();
    }
    out
}

/// First path component of a relative key, or `(root)` for a top-level file.
fn category_of(relative: &str) -> String {
    match relative.split_once('/') {
        Some((first, _)) if !first.is_empty() => first.to_string(),
        _ => ROOT_CATEGORY.to_string(),
    }
}

/// Search + filter state driving the archive list.
#[derive(Clone, Debug, Default)]
pub struct SearchFilter {
    /// Space-separated terms; every term must match (AND), case-insensitive.
    pub query: String,
    pub only_with_models: bool,
    pub only_with_textures: bool,
    /// `None` means every category.
    pub category: Option<String>,
}

impl SearchFilter {
    pub fn is_active(&self) -> bool {
        !self.query.trim().is_empty()
            || self.only_with_models
            || self.only_with_textures
            || self.category.is_some()
    }
}

/// Indices of the records matching `filter`, preserving input order.
pub fn filter_records(records: &[ArchiveRecord], filter: &SearchFilter) -> Vec<usize> {
    if !filter.is_active() {
        return (0..records.len()).collect();
    }

    // One small allocation per call; `search_key` is already lowercased so the
    // per-record work below is pure substring matching.
    let terms: Vec<String> = filter
        .query
        .split_whitespace()
        .map(|term| term.to_lowercase())
        .collect();
    let category = filter.category.as_deref();

    let mut matched = Vec::new();
    for (index, record) in records.iter().enumerate() {
        if filter.only_with_models && record.prm_count == 0 {
            continue;
        }
        if filter.only_with_textures && record.xi_count == 0 {
            continue;
        }
        if let Some(wanted) = category {
            if record.category != wanted {
                continue;
            }
        }
        if !terms
            .iter()
            .all(|term| record.search_key.contains(term.as_str()))
        {
            continue;
        }
        matched.push(index);
    }
    matched
}

/// Sorted unique category list, for the category selector.
pub fn categories(records: &[ArchiveRecord]) -> Vec<String> {
    let mut found: Vec<String> = records
        .iter()
        .map(|record| record.category.clone())
        .collect();
    found.sort();
    found.dedup();
    found
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicUsize;

    fn record(relative: &str, prm: usize, xi: usize) -> ArchiveRecord {
        let relative = relative.to_string();
        let file_name = relative
            .rsplit('/')
            .next()
            .unwrap_or(relative.as_str())
            .to_string();
        ArchiveRecord {
            path: PathBuf::from(&relative),
            search_key: relative.to_lowercase(),
            category: category_of(&relative),
            file_name,
            member_count: prm + xi,
            prm_count: prm,
            xi_count: xi,
            mbn_count: 0,
            size: 4096,
            relative,
        }
    }

    fn sample() -> Vec<ArchiveRecord> {
        vec![
            record("chr/ms001000/MS001000_p000.xc", 6, 5),
            record("chr/ms002000/ms002000_p000.xc", 4, 0),
            record("map/e1101.xc", 20, 9),
            record("eff/ef_common.xc", 0, 3),
            record("top.xc", 0, 0),
        ]
    }

    fn query(text: &str) -> SearchFilter {
        SearchFilter {
            query: text.to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn empty_query_matches_every_record() {
        let records = sample();
        assert_eq!(filter_records(&records, &query("")), vec![0, 1, 2, 3, 4]);
        assert_eq!(filter_records(&records, &query("   ")), vec![0, 1, 2, 3, 4]);
        assert_eq!(
            filter_records(&records, &SearchFilter::default()),
            vec![0, 1, 2, 3, 4]
        );
    }

    #[test]
    fn multi_term_query_uses_and_semantics() {
        let records = sample();
        assert_eq!(filter_records(&records, &query("chr p000")), vec![0, 1]);
        assert_eq!(filter_records(&records, &query("ms001 p000")), vec![0]);
        // No record can be under both areas at once.
        assert!(filter_records(&records, &query("chr map")).is_empty());
    }

    #[test]
    fn query_matching_is_case_insensitive() {
        let records = sample();
        // Mixed-case record name, mixed-case query, both directions.
        assert_eq!(filter_records(&records, &query("MS001000_P000")), vec![0]);
        assert_eq!(filter_records(&records, &query("ms001000_p000")), vec![0]);
        assert_eq!(filter_records(&records, &query("CHR")), vec![0, 1]);
    }

    #[test]
    fn model_and_texture_flags_filter_records() {
        let records = sample();

        let models = SearchFilter {
            only_with_models: true,
            ..Default::default()
        };
        assert_eq!(filter_records(&records, &models), vec![0, 1, 2]);

        let textures = SearchFilter {
            only_with_textures: true,
            ..Default::default()
        };
        assert_eq!(filter_records(&records, &textures), vec![0, 2, 3]);

        let both = SearchFilter {
            only_with_models: true,
            only_with_textures: true,
            ..Default::default()
        };
        assert_eq!(filter_records(&records, &both), vec![0, 2]);
    }

    #[test]
    fn category_filter_selects_one_area() {
        let records = sample();

        let chr = SearchFilter {
            category: Some("chr".to_string()),
            ..Default::default()
        };
        assert_eq!(filter_records(&records, &chr), vec![0, 1]);

        let root = SearchFilter {
            category: Some(ROOT_CATEGORY.to_string()),
            ..Default::default()
        };
        assert_eq!(filter_records(&records, &root), vec![4]);

        let missing = SearchFilter {
            category: Some("snd".to_string()),
            ..Default::default()
        };
        assert!(filter_records(&records, &missing).is_empty());
    }

    #[test]
    fn query_and_flags_combine() {
        let records = sample();

        let models_in_chr = SearchFilter {
            query: "P000".to_string(),
            only_with_models: true,
            only_with_textures: true,
            category: Some("chr".to_string()),
            ..Default::default()
        };
        assert_eq!(filter_records(&records, &models_in_chr), vec![0]);

        // Same query, but the texture requirement rules the second chr archive out.
        let textures_only = SearchFilter {
            query: "chr".to_string(),
            only_with_textures: true,
            ..Default::default()
        };
        assert_eq!(filter_records(&records, &textures_only), vec![0]);

        // Category and query disagree.
        let conflicting = SearchFilter {
            query: "e1101".to_string(),
            category: Some("chr".to_string()),
            ..Default::default()
        };
        assert!(filter_records(&records, &conflicting).is_empty());
    }

    #[test]
    fn filter_records_preserves_input_order() {
        // Deliberately unsorted input: the result must follow input order,
        // not alphabetical order.
        let records = vec![
            record("map/e9999.xc", 1, 1),
            record("chr/ms001000/ms001000_p000.xc", 1, 1),
            record("btl/b0001.xc", 1, 1),
            record("chr/ms002000/ms002000_p000.xc", 1, 1),
        ];
        assert_eq!(filter_records(&records, &query("")), vec![0, 1, 2, 3]);
        assert_eq!(filter_records(&records, &query(".xc")), vec![0, 1, 2, 3]);
        assert_eq!(filter_records(&records, &query("ms00")), vec![1, 3]);
    }

    #[test]
    fn categories_are_sorted_and_deduplicated() {
        let records = vec![
            record("map/e1101.xc", 0, 0),
            record("chr/ms001000/a.xc", 0, 0),
            record("map/e1102.xc", 0, 0),
            record("btl/b0001.xc", 0, 0),
            record("chr/ms002000/a.xc", 0, 0),
            record("top.xc", 0, 0),
        ];
        assert_eq!(
            categories(&records),
            vec![
                ROOT_CATEGORY.to_string(),
                "btl".to_string(),
                "chr".to_string(),
                "map".to_string(),
            ]
        );
        assert!(categories(&[]).is_empty());
    }

    #[test]
    fn is_active_is_false_only_for_the_default_filter() {
        assert!(!SearchFilter::default().is_active());
        assert!(!query("   ").is_active());

        assert!(query("chr").is_active());
        assert!(
            SearchFilter {
                only_with_models: true,
                ..Default::default()
            }
            .is_active()
        );
        assert!(
            SearchFilter {
                only_with_textures: true,
                ..Default::default()
            }
            .is_active()
        );
        assert!(
            SearchFilter {
                category: Some("chr".to_string()),
                ..Default::default()
            }
            .is_active()
        );
    }

    #[test]
    fn category_of_falls_back_to_root_marker() {
        assert_eq!(category_of("chr/ms001000/a.xc"), "chr");
        assert_eq!(category_of("map/e1101.xc"), "map");
        assert_eq!(category_of("top.xc"), ROOT_CATEGORY);
        assert_eq!(category_of(""), ROOT_CATEGORY);
    }

    #[test]
    fn archive_extension_detection_is_case_insensitive() {
        assert!(has_archive_extension(Path::new("a/b/c.xc")));
        assert!(has_archive_extension(Path::new("a/b/c.XC")));
        assert!(has_archive_extension(Path::new("a/b/c.xb")));
        assert!(has_archive_extension(Path::new("a/b/c.xk")));
        assert!(!has_archive_extension(Path::new("a/b/c.prm")));
        assert!(!has_archive_extension(Path::new("a/b/c")));
    }

    // ---- synthetic tree scanning (no game data required) -------------------

    /// Temporary directory tree, removed on drop.
    struct TempTree {
        root: PathBuf,
    }

    impl TempTree {
        fn new(tag: &str) -> Self {
            static COUNTER: AtomicUsize = AtomicUsize::new(0);
            let unique = COUNTER.fetch_add(1, Ordering::Relaxed);
            let root = std::env::temp_dir().join(format!(
                "age_viewer_index_{}_{tag}_{unique}",
                std::process::id()
            ));
            let _ = std::fs::remove_dir_all(&root);
            std::fs::create_dir_all(&root).expect("create temp root");
            Self { root }
        }

        fn root(&self) -> &Path {
            &self.root
        }

        fn write(&self, relative: &str, bytes: &[u8]) {
            let path = self.root.join(relative.replace('/', std::path::MAIN_SEPARATOR_STR));
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent).expect("create temp dir");
            }
            std::fs::write(&path, bytes).expect("write temp file");
        }
    }

    impl Drop for TempTree {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.root);
        }
    }

    /// Minimal XPCK archive with an uncompressed name table, mirroring the
    /// layout `xpck::scan_members` expects.
    fn synthetic_xpck(members: &[(&str, usize)]) -> Vec<u8> {
        const HEADER_SIZE: usize = 20;
        const ENTRY_SIZE: usize = 12;

        let mut names: Vec<u8> = Vec::new();
        let mut name_offsets: Vec<u16> = Vec::new();
        for (name, _) in members {
            name_offsets.push(names.len() as u16);
            names.extend_from_slice(name.as_bytes());
            names.push(0);
        }
        // Level-5 block header: (size << 3) | method, method 0 = stored.
        let mut name_block = ((names.len() as u32) << 3).to_le_bytes().to_vec();
        name_block.extend_from_slice(&names);
        while name_block.len() % 4 != 0 {
            name_block.push(0);
        }

        let file_info_offset = HEADER_SIZE;
        let entry_table_size = members.len() * ENTRY_SIZE;
        let filename_table_offset = file_info_offset + entry_table_size;
        let data_offset = filename_table_offset + name_block.len();

        let mut payload: Vec<u8> = Vec::new();
        let mut member_offsets: Vec<usize> = Vec::new();
        for (_, size) in members {
            member_offsets.push(payload.len());
            payload.extend(std::iter::repeat_n(0xABu8, *size));
            while payload.len() % 4 != 0 {
                payload.push(0);
            }
        }

        let mut out = vec![0u8; data_offset + payload.len()];
        out[0..4].copy_from_slice(crate::xpck::MAGIC);
        out[4] = (members.len() & 0xFF) as u8;
        out[5] = 0x70u8 | (((members.len() >> 8) & 0x0F) as u8);
        out[6..8].copy_from_slice(&((file_info_offset as u16) >> 2).to_le_bytes());
        out[8..10].copy_from_slice(&((filename_table_offset as u16) >> 2).to_le_bytes());
        out[10..12].copy_from_slice(&((data_offset as u16) >> 2).to_le_bytes());
        out[12..14].copy_from_slice(&((entry_table_size as u16) >> 2).to_le_bytes());
        out[14..16].copy_from_slice(&((name_block.len() as u16) >> 2).to_le_bytes());
        out[16..20].copy_from_slice(&((payload.len() as u32) >> 2).to_le_bytes());

        for (index, (_, size)) in members.iter().enumerate() {
            let base = file_info_offset + index * ENTRY_SIZE;
            let offset_words = member_offsets[index] >> 2;
            out[base..base + 4].copy_from_slice(&(index as u32).to_le_bytes());
            out[base + 4..base + 6].copy_from_slice(&name_offsets[index].to_le_bytes());
            out[base + 6..base + 8].copy_from_slice(&((offset_words & 0xFFFF) as u16).to_le_bytes());
            out[base + 8..base + 10].copy_from_slice(&((*size & 0xFFFF) as u16).to_le_bytes());
            out[base + 10] = ((offset_words >> 16) & 0xFF) as u8;
            out[base + 11] = ((*size >> 16) & 0xFF) as u8;
        }
        out[filename_table_offset..filename_table_offset + name_block.len()]
            .copy_from_slice(&name_block);
        out[data_offset..data_offset + payload.len()].copy_from_slice(&payload);
        out
    }

    fn synthetic_tree() -> TempTree {
        let tree = TempTree::new("scan");
        tree.write(
            "chr/ms001000/ms001000_p000.xc",
            &synthetic_xpck(&[
                ("000.prm", 32),
                ("001.prm", 16),
                ("000.xi", 64),
                ("root.mbn", 8),
                ("hip.MBN", 8),
            ]),
        );
        tree.write(
            "map/e1101.xc",
            &synthetic_xpck(&[("000.prm", 12), ("000.xi", 12)]),
        );
        tree.write("top.xc", &synthetic_xpck(&[("info.cfg.bin", 4)]));
        tree.write("notes.txt", b"not an archive at all");
        // XPCK magic but the entry table is missing: scan_members must fail.
        tree.write(
            "chr/broken.xc",
            &synthetic_xpck(&[("000.prm", 32)])[..24].to_vec(),
        );
        // Archive extension but no XPCK magic: silently ignored, not an error.
        tree.write("chr/fake.xc", b"NOTXPCK-just-some-bytes-here");
        tree
    }

    #[test]
    fn scan_root_indexes_a_synthetic_tree() {
        let tree = synthetic_tree();
        let cancel = AtomicBool::new(false);
        let mut updates: Vec<ScanProgress> = Vec::new();
        let mut sink = |progress: ScanProgress| updates.push(progress);

        let records = scan_root(tree.root(), &cancel, &mut sink);

        assert_eq!(
            records.iter().map(|r| r.relative.as_str()).collect::<Vec<_>>(),
            vec![
                "chr/ms001000/ms001000_p000.xc",
                "map/e1101.xc",
                "top.xc"
            ],
            "records must be sorted by relative path"
        );

        let chr = &records[0];
        assert_eq!(chr.file_name, "ms001000_p000.xc");
        assert_eq!(chr.category, "chr");
        assert_eq!(chr.search_key, "chr/ms001000/ms001000_p000.xc");
        assert_eq!(chr.member_count, 5);
        assert_eq!(chr.prm_count, 2);
        assert_eq!(chr.xi_count, 1);
        assert_eq!(chr.mbn_count, 2, "member extensions match case-insensitively");
        assert!(chr.has_models() && chr.has_textures());
        assert!(chr.size > 0);
        assert!(chr.path.is_file());

        assert_eq!(records[2].category, ROOT_CATEGORY);
        assert_eq!(records[2].prm_count, 0);
        assert!(!records[2].has_models());

        assert_eq!(categories(&records), vec!["(root)", "chr", "map"]);

        let last = updates.last().expect("at least one progress update");
        assert_eq!(last.files_seen, 6);
        assert_eq!(last.archives_found, 3);
        assert_eq!(last.errors, 1, "the truncated archive is counted and skipped");
    }

    #[test]
    fn scan_root_stops_when_cancelled() {
        let tree = synthetic_tree();
        let cancel = AtomicBool::new(true);
        let mut updates: Vec<ScanProgress> = Vec::new();
        let mut sink = |progress: ScanProgress| updates.push(progress);

        let records = scan_root(tree.root(), &cancel, &mut sink);

        assert!(records.is_empty());
        assert_eq!(updates.len(), 1, "still reports once at the end");
    }

    #[test]
    fn scan_root_returns_nothing_for_a_missing_root() {
        let mut updates: Vec<ScanProgress> = Vec::new();
        let mut sink = |progress: ScanProgress| updates.push(progress);
        let cancel = AtomicBool::new(false);
        let missing = std::env::temp_dir().join("age_viewer_index_missing_root_9c1f");

        let records = scan_root(&missing, &cancel, &mut sink);

        assert!(records.is_empty());
        assert_eq!(updates.len(), 1);
    }

    #[test]
    fn spawn_scan_finishes_with_the_records_it_found() {
        let tree = synthetic_tree();
        let handle = spawn_scan(tree.root().to_path_buf());

        let mut terminal = None;
        while let Ok(message) = handle.receiver.recv_timeout(Duration::from_secs(10)) {
            match message {
                ScanMessage::Progress(_) => {}
                other => {
                    assert!(terminal.is_none(), "exactly one terminal message");
                    terminal = Some(other);
                }
            }
        }

        match terminal.expect("terminal message") {
            ScanMessage::Finished(records) => assert_eq!(records.len(), 3),
            other => panic!("unexpected terminal message: {other:?}"),
        }
        assert!(!handle.is_cancelled());
    }

    #[test]
    fn spawn_scan_fails_for_an_unusable_root() {
        let missing = std::env::temp_dir().join("age_viewer_index_missing_root_4b7e");
        let _ = std::fs::remove_dir_all(&missing);
        let handle = spawn_scan(missing);

        match handle
            .receiver
            .recv_timeout(Duration::from_secs(10))
            .expect("a terminal message")
        {
            ScanMessage::Failed(reason) => assert!(reason.contains("does not exist")),
            other => panic!("unexpected message: {other:?}"),
        }

        handle.cancel();
        assert!(handle.is_cancelled());
    }
}
