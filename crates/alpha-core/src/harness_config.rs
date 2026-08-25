/// Versioned harness parameters shared across all alphas.
///
/// Changing any field constitutes a new harness version and requires
/// re-running the entire registry. Tuned once per timeframe on train data,
/// selected by plateau center (never peak).
#[derive(Debug, Clone, PartialEq)]
pub struct HarnessConfig {
    /// EWMA smoothing span in bars (Component 1 step A)
    pub span: usize,
    /// Rolling z-score window length in bars (Component 1 step B)
    pub z_window: usize,
    /// No-trade dead-zone threshold in z units (Component 1 step C)
    pub band: f64,
    /// Leverage cap policy, multiples of capital (Component 1 step D)
    pub cap: f64,
    /// Cost per unit notional per side = fee + half_spread + buffer
    pub cost_per_side: f64,
}

impl Default for HarnessConfig {
    fn default() -> Self {
        Self {
            span: 8,
            z_window: 480,
            band: 0.35,
            cap: 2.0,
            cost_per_side: 0.0001, // ~1 bp per side
        }
    }
}
