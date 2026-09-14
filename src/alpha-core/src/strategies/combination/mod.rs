pub mod inverse_vol;

pub trait CombineMethod {

    fn combine(&self, scores: &[Vec<f64>]) -> Vec<f64>;

    fn name(&self) -> &str;
}
