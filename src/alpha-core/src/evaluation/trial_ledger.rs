//! Append-only trial ledger with deduplication and persistence.
//!
//! Every backtest configuration that is ever evaluated must be recorded
//! here so that multiple-testing corrections (see `deflated_sharpe`) can
//! use the true number of trials. The ledger is append-only: entries are
//! never removed or rewritten. Duplicate configurations - identical
//! code version, parameters, and data range - are detected via a 64-bit
//! FNV-1a hash and reported to the caller instead of silently inflating
//! the unique trial count.
//!
//! Pure Rust, no external dependencies.

use std::collections::HashSet;
use std::fs;
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

/// One recorded trial in the ledger.
#[derive(Debug, Clone)]
pub struct TrialEntry {
    /// Hash of code_version + params + data_range (FNV-1a 64-bit).
    pub config_hash: u64,
    /// Brief result description.
    pub result_summary: String,
    /// ISO-8601 UTC timestamp of the moment the trial was recorded.
    pub timestamp: String,
}

/// Append-only ledger of every trial run against the data.
///
/// `entries` keeps every record in insertion order; `seen_hashes` provides
/// O(1) duplicate detection.
pub struct TrialLedger {
    entries: Vec<TrialEntry>,
    seen_hashes: HashSet<u64>,
}

impl Default for TrialLedger {
    fn default() -> Self {
        Self::new()
    }
}

impl TrialLedger {
    /// Create an empty ledger.
    pub fn new() -> Self {
        Self {
            entries: Vec::new(),
            seen_hashes: HashSet::new(),
        }
    }

    /// Record one trial. The configuration identity is the combination of
    /// `code_version`, `params`, and `data_range`; `result` is stored as a
    /// free-form summary line.
    ///
    /// Returns `true` if this configuration had not been seen before,
    /// `false` if it is a duplicate (the entry is still appended, keeping
    /// the ledger append-only; use `unique_count` for deflation inputs).
    pub fn record(
        &mut self,
        code_version: &str,
        params: &str,
        data_range: &str,
        result: &str,
    ) -> bool {
        let h = config_hash(code_version, params, data_range);
        let is_new = self.seen_hashes.insert(h);
        self.entries.push(TrialEntry {
            config_hash: h,
            result_summary: result.to_string(),
            timestamp: iso_timestamp_now(),
        });
        is_new
    }

    /// Number of distinct configurations tried (the N for deflation).
    pub fn unique_count(&self) -> usize {
        self.seen_hashes.len()
    }

    /// Total number of recorded runs, duplicates included.
    pub fn total_count(&self) -> usize {
        self.entries.len()
    }

    /// Read-only view of all entries in insertion order.
    pub fn entries(&self) -> &[TrialEntry] {
        &self.entries
    }

    /// True if this exact configuration has already been recorded.
    pub fn contains(&self, code_version: &str, params: &str, data_range: &str) -> bool {
        self.seen_hashes
            .contains(&config_hash(code_version, params, data_range))
    }

    /// Estimate the effective number of independent trials by clustering
    /// correlated trials.
    ///
    /// `pnl_matrix` supplies the similarity information between trials:
    /// - If it is square (N x N), it is interpreted as a precomputed
    ///   correlation / similarity matrix with rows and columns indexed by
    ///   trial.
    /// - Otherwise each row is interpreted as one trial's PnL series and
    ///   Pearson correlations are computed pairwise over the common
    ///   length.
    ///
    /// Two trials belong to the same cluster when their correlation is at
    /// least `correlation_threshold` (single-linkage greedy clustering).
    /// The effective N is the number of resulting clusters: a family of
    /// near-identical parameter tweaks counts as one trial, not many.
    /// Returns 0 for an empty matrix.
    pub fn effective_n(&self, correlation_threshold: f64, pnl_matrix: &[Vec<f64>]) -> usize {
        let n = pnl_matrix.len();
        if n == 0 {
            return 0;
        }
        let sim = similarity_matrix(pnl_matrix);

        let mut parent: Vec<usize> = (0..n).collect();
        // Union-find with path compression.
        fn find(parent: &mut Vec<usize>, i: usize) -> usize {
            let mut root = i;
            while parent[root] != root {
                root = parent[root];
            }
            let mut cur = i;
            while parent[cur] != root {
                let next = parent[cur];
                parent[cur] = root;
                cur = next;
            }
            root
        }
        for i in 0..n {
            for j in (i + 1)..n {
                let c = sim[i][j];
                if c.is_finite() && c >= correlation_threshold {
                    let ri = find(&mut parent, i);
                    let rj = find(&mut parent, j);
                    if ri != rj {
                        parent[ri] = rj;
                    }
                }
            }
        }
        (0..n)
            .map(|i| find(&mut parent, i))
            .collect::<HashSet<usize>>()
            .len()
    }

    /// Persist the ledger as newline-delimited records:
    /// `config_hash<TAB>escaped_timestamp<TAB>escaped_summary`.
    /// Strings are escaped for tab, newline, carriage return, and
    /// backslash, so summaries containing any text round-trip exactly.
    /// The parent directory of `path` must already exist.
    pub fn save(&self, path: &str) -> io::Result<()> {
        let file = fs::File::create(Path::new(path))?;
        let mut w = BufWriter::new(file);
        for e in &self.entries {
            writeln!(
                w,
                "{}\t{}\t{}",
                e.config_hash,
                escape_field(&e.timestamp),
                escape_field(&e.result_summary)
            )?;
        }
        w.flush()
    }

    /// Load a ledger previously written by [`TrialLedger::save`].
    /// Malformed lines are rejected with `InvalidData`.
    pub fn load(path: &str) -> io::Result<Self> {
        let file = fs::File::open(Path::new(path))?;
        let reader = BufReader::new(file);
        let mut ledger = TrialLedger::new();
        for (idx, line) in reader.lines().enumerate() {
            let line = line?;
            if line.trim().is_empty() {
                continue;
            }
            let parts: Vec<&str> = line.splitn(3, '\t').collect();
            if parts.len() != 3 {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("trial ledger: malformed record on line {}", idx + 1),
                ));
            }
            let hash: u64 = parts[0].parse().map_err(|_| {
                io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("trial ledger: bad hash on line {}", idx + 1),
                )
            })?;
            let entry = TrialEntry {
                config_hash: hash,
                timestamp: unescape_field(parts[1]).ok_or_else(|| {
                    io::Error::new(
                        io::ErrorKind::InvalidData,
                        format!("trial ledger: bad escape on line {}", idx + 1),
                    )
                })?,
                result_summary: unescape_field(parts[2]).ok_or_else(|| {
                    io::Error::new(
                        io::ErrorKind::InvalidData,
                        format!("trial ledger: bad escape on line {}", idx + 1),
                    )
                })?,
            };
            ledger.seen_hashes.insert(entry.config_hash);
            ledger.entries.push(entry);
        }
        Ok(ledger)
    }
}

/// FNV-1a 64-bit hash over `code_version | params | data_range`.
/// Deterministic across processes and platforms (unlike DefaultHasher).
pub fn config_hash(code_version: &str, params: &str, data_range: &str) -> u64 {
    const FNV_OFFSET: u64 = 0xcbf2_9ce4_8422_2325;
    const FNV_PRIME: u64 = 0x0000_0100_0000_01b3;
    let mut h = FNV_OFFSET;
    let mut feed = |bytes: &[u8]| {
        for &b in bytes {
            h ^= b as u64;
            h = h.wrapping_mul(FNV_PRIME);
        }
    };
    feed(code_version.as_bytes());
    feed(b"|");
    feed(params.as_bytes());
    feed(b"|");
    feed(data_range.as_bytes());
    h
}

/// Build the pairwise similarity matrix used by clustering: square input
/// is taken as-is, anything else gets Pearson correlations between rows.
fn similarity_matrix(rows: &[Vec<f64>]) -> Vec<Vec<f64>> {
    let n = rows.len();
    let square = rows.iter().all(|r| r.len() == n);
    let mut sim = vec![vec![0.0f64; n]; n];
    for i in 0..n {
        for j in 0..n {
            if i == j {
                sim[i][j] = 1.0;
            } else if square {
                sim[i][j] = rows[i][j];
            } else {
                sim[i][j] = pearson(&rows[i], &rows[j]);
            }
        }
    }
    sim
}

/// Pearson correlation over the overlapping prefix of two series.
/// Returns 0.0 when fewer than 2 overlapping points or zero variance.
fn pearson(a: &[f64], b: &[f64]) -> f64 {
    let n = a.len().min(b.len());
    if n < 2 {
        return 0.0;
    }
    let (mut sa, mut sb) = (0.0f64, 0.0f64);
    for k in 0..n {
        sa += a[k];
        sb += b[k];
    }
    let (ma, mb) = (sa / n as f64, sb / n as f64);
    let (mut cov, mut va, mut vb) = (0.0f64, 0.0f64, 0.0f64);
    for k in 0..n {
        let da = a[k] - ma;
        let db = b[k] - mb;
        cov += da * db;
        va += da * da;
        vb += db * db;
    }
    if va <= 1e-24 || vb <= 1e-24 {
        return 0.0;
    }
    cov / (va.sqrt() * vb.sqrt())
}

/// Escape tab, newline, carriage return, and backslash for storage.
fn escape_field(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 8);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            _ => out.push(c),
        }
    }
    out
}

/// Inverse of [`escape_field`]. Returns None on a trailing lone backslash.
fn unescape_field(s: &str) -> Option<String> {
    let mut out = String::with_capacity(s.len());
    let mut chars = s.chars();
    while let Some(c) = chars.next() {
        if c != '\\' {
            out.push(c);
            continue;
        }
        match chars.next()? {
            '\\' => out.push('\\'),
            't' => out.push('\t'),
            'n' => out.push('\n'),
            'r' => out.push('\r'),
            _ => return None,
        }
    }
    Some(out)
}

/// Current time as an ISO-8601 UTC string, computed from the Unix epoch
/// without external date libraries.
fn iso_timestamp_now() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    format_epoch_utc(secs)
}

/// Format seconds-since-epoch as `YYYY-MM-DDTHH:MM:SSZ`.
pub(crate) fn format_epoch_utc(secs: i64) -> String {
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    let (y, m, d) = civil_from_days(days);
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        y,
        m,
        d,
        rem / 3600,
        (rem % 3600) / 60,
        rem % 60
    )
}

/// Days since 1970-01-01 to (year, month, day) in the proleptic Gregorian
/// calendar (Howard Hinnant's civil-from-days algorithm).
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097); // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365; // [0, 399]
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32; // [1, 12]
    (if m <= 2 { y + 1 } else { y }, m, d)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn records_and_counts() {
        let mut led = TrialLedger::new();
        assert_eq!(led.unique_count(), 0);
        assert_eq!(led.total_count(), 0);

        assert!(led.record("v1", "{\"ma\":20}", "2020-01:2021-12", "sharpe 1.2"));
        assert!(led.record("v1", "{\"ma\":50}", "2020-01:2021-12", "sharpe 0.7"));
        assert_eq!(led.unique_count(), 2);
        assert_eq!(led.total_count(), 2);
        assert!(led.contains("v1", "{\"ma\":20}", "2020-01:2021-12"));
        assert!(!led.contains("v1", "{\"ma\":200}", "2020-01:2021-12"));
    }

    #[test]
    fn duplicate_detection() {
        let mut led = TrialLedger::new();
        assert!(led.record("v1", "p=1", "2020:2021", "first"));
        // Same triple, different summary: still a duplicate config.
        assert!(!led.record("v1", "p=1", "2020:2021", "rerun after tweak"));
        assert_eq!(led.unique_count(), 1);
        // The rerun is still appended: ledger stays append-only.
        assert_eq!(led.total_count(), 2);
        // Different code version counts as a different trial.
        assert!(led.record("v2", "p=1", "2020:2021", "after bug fix"));
        assert_eq!(led.unique_count(), 2);
        assert_eq!(led.total_count(), 3);
        assert_eq!(led.entries()[1].result_summary, "rerun after tweak");
    }

    #[test]
    fn config_hash_is_stable_and_order_sensitive() {
        let h1 = config_hash("v1", "p=1", "2020:2021");
        assert_eq!(h1, config_hash("v1", "p=1", "2020:2021"));
        assert_ne!(h1, config_hash("v2", "p=1", "2020:2021"));
        // Field boundaries matter: ("ab","c") vs ("a","bc").
        assert_ne!(config_hash("ab", "c", ""), config_hash("a", "bc", ""));
    }

    #[test]
    fn iso_formatting_known_values() {
        assert_eq!(format_epoch_utc(0), "1970-01-01T00:00:00Z");
        assert_eq!(format_epoch_utc(1_700_000_000), "2023-11-14T22:13:20Z");
        // Leap-day boundary: 2024-02-29T00:00:00Z.
        assert_eq!(format_epoch_utc(1_709_164_800), "2024-02-29T00:00:00Z");
        assert_eq!(format_epoch_utc(-1), "1969-12-31T23:59:59Z");
    }

    #[test]
    fn effective_n_clusters_correlated_pnl_rows() {
        let mut led = TrialLedger::new();
        led.record("v", "x", "r", "s");
        // Three PnL series: row1 is a scaled copy of row0 (corr = 1.0),
        // row2 is the inverted row0 (corr = -1.0). At threshold 0.9 only
        // rows 0 and 1 merge => effective N is 2.
        let pnl = vec![
            vec![1.0, 2.0, 3.0, 4.0],
            vec![2.0, 4.0, 6.0, 8.0],
            vec![4.0, 3.0, 2.0, 1.0],
        ];
        assert_eq!(led.effective_n(0.9, &pnl), 2);
        // Loose threshold merges everything.
        assert_eq!(led.effective_n(0.5, &pnl), 2);
        // Impossible threshold keeps every trial separate.
        assert_eq!(led.effective_n(1.5, &pnl), 3);
        assert_eq!(led.effective_n(0.9, &[]), 0);
    }

    #[test]
    fn effective_n_accepts_precomputed_correlation_matrix() {
        let led = TrialLedger::new();
        // Square input: treated as a correlation matrix directly.
        let corr = vec![
            vec![1.0, 0.95, 0.10],
            vec![0.95, 1.0, 0.20],
            vec![0.10, 0.20, 1.0],
        ];
        assert_eq!(led.effective_n(0.5, &corr), 2);
        // Chained correlations collapse into a single cluster at 0.8:
        // 0-1 and 1-2 are linked even though 0-2 is not (single linkage).
        let chain = vec![
            vec![1.0, 0.85, 0.70],
            vec![0.85, 1.0, 0.85],
            vec![0.70, 0.85, 1.0],
        ];
        assert_eq!(led.effective_n(0.8, &chain), 1);
    }

    #[test]
    fn save_load_round_trip_with_special_characters() {
        let mut led = TrialLedger::new();
        led.record("v1", "p\t1", "2020:2021", "has\ttab and\nnewline \\ slash");
        led.record("v1", "p=2", "2020:2021", "plain");
        led.record("v1", "p=2", "2020:2021", "duplicate run");

        let path = std::env::temp_dir().join(format!(
            "trial_ledger_test_{}.txt",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));

        led.save(path.to_str().unwrap()).expect("save failed");
        let loaded = TrialLedger::load(path.to_str().unwrap()).expect("load failed");

        assert_eq!(loaded.unique_count(), led.unique_count());
        assert_eq!(loaded.total_count(), led.total_count());
        assert_eq!(
            loaded.entries()[0].result_summary,
            "has\ttab and\nnewline \\ slash"
        );
        assert_eq!(
            loaded.entries()[0].config_hash,
            led.entries()[0].config_hash
        );
        assert!(!loaded.entries()[0].timestamp.is_empty());

        let _ = std::fs::remove_file(&path);
    }
}
