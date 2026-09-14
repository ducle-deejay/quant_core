pub mod drawdown_overlay;
pub mod vol_target;

pub trait SizingMethod {

    fn compute(&self, score: &[f64], vol_est: &[f64]) -> Vec<f64>;

    fn name(&self) -> &str;
}
