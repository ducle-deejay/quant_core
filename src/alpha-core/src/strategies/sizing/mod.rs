pub mod drawdown_overlay;
pub mod vol_target;

/// Trait for position sizing methods.
/// Implementations convert composite scores + risk estimates into target positions.
pub trait SizingMethod {
    /// Compute target positions from scores and volatility estimates.
    ///
    /// Arguments:
    /// - score: standardized composite score series
    /// - vol_est: estimated volatility per bar (same length as score)
    ///
    /// Returns: target positions, same length as input, in multiples of capital notional.
    fn compute(&self, score: &[f64], vol_est: &[f64]) -> Vec<f64>;

    /// Human-readable name for logging/debugging
    fn name(&self) -> &str;
}
