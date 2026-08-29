pub mod inverse_vol;

/// Trait for combining multiple alpha scores into one composite score.
pub trait CombineMethod {
    /// Combine standardized alpha scores into composite scores.
    ///
    /// Arguments:
    /// - scores: matrix where row i = score series for alpha i, columns = time bars
    /// - Returns: one composite score series (length = number of bars)
    fn combine(&self, scores: &[Vec<f64>]) -> Vec<f64>;

    fn name(&self) -> &str;
}
