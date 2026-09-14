#[derive(Debug, Clone, PartialEq)]
pub struct HarnessConfig {

    pub span: usize,

    pub z_window: usize,

    pub band: f64,

    pub cap: f64,

    pub cost_per_side: f64,
}

impl Default for HarnessConfig {
    fn default() -> Self {
        Self {
            span: 8,
            z_window: 480,
            band: 0.35,
            cap: 2.0,
            cost_per_side: 0.0001,
        }
    }
}
