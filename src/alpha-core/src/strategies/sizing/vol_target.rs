use super::SizingMethod;

pub struct VolTarget {

    pub target_vol_daily: f64,
}

impl VolTarget {

    pub fn new(target_vol_daily: f64) -> Self {
        Self { target_vol_daily }
    }
}

impl SizingMethod for VolTarget {
    fn compute(&self, score: &[f64], vol_est: &[f64]) -> Vec<f64> {
        score
            .iter()
            .zip(vol_est)
            .map(|(&z, &v)| {
                if v > 1e-12 {
                    z * self.target_vol_daily / v
                } else {
                    0.0
                }
            })
            .collect()
    }

    fn name(&self) -> &str {
        "vol_target"
    }
}

pub struct VolTargetWithFloor {

    pub target_vol_daily: f64,

    pub vol_floor: f64,
}

impl VolTargetWithFloor {

    pub fn new(target_vol_daily: f64, vol_floor: f64) -> Self {
        assert!(vol_floor > 0.0, "vol_floor must be positive");
        Self {
            target_vol_daily,
            vol_floor,
        }
    }

    fn effective_vol(&self, v: f64) -> f64 {
        if v > self.vol_floor {
            v
        } else {
            self.vol_floor
        }
    }
}

impl SizingMethod for VolTargetWithFloor {
    fn compute(&self, score: &[f64], vol_est: &[f64]) -> Vec<f64> {
        score
            .iter()
            .zip(vol_est)
            .map(|(&z, &v)| {
                let v_eff = self.effective_vol(v);

                if v > 1e-12 {
                    z * self.target_vol_daily / v_eff
                } else {
                    0.0
                }
            })
            .collect()
    }

    fn name(&self) -> &str {
        "vol_target_with_floor"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TARGET: f64 = 0.01;

    #[test]
    fn vol_target_scales_score_by_target_over_vol() {
        let sizer = VolTarget::new(TARGET);
        let score = [2.0, -1.0, 0.5];
        let vol = [0.02, 0.01, 0.005];

        let pos = sizer.compute(&score, &vol);

        assert_eq!(pos.len(), 3);
        assert!((pos[0] - (2.0 * TARGET / 0.02)).abs() < 1e-12);
        assert!((pos[1] - (-1.0 * TARGET / 0.01)).abs() < 1e-12);
        assert!((pos[2] - (0.5 * TARGET / 0.005)).abs() < 1e-12);
    }

    #[test]
    fn vol_target_zero_vol_is_safe() {
        let sizer = VolTarget::new(TARGET);
        let score = [3.0, -3.0, 1.0];
        let vol = [0.0, 1e-15, 0.01];

        let pos = sizer.compute(&score, &vol);

        assert_eq!(pos[0], 0.0);
        assert_eq!(pos[1], 0.0);
        assert!(pos.iter().all(|p| p.is_finite()));
    }

    #[test]
    fn vol_target_empty_input_yields_empty_output() {
        let sizer = VolTarget::new(TARGET);
        let pos = sizer.compute(&[], &[]);
        assert!(pos.is_empty());
    }

    #[test]
    fn floor_caps_leverage_when_vol_below_floor() {
        let floor = 0.005;
        let sizer = VolTargetWithFloor::new(TARGET, floor);

        let score = [1.0];
        let vol = [0.001];

        let pos = sizer.compute(&score, &vol);

        assert!((pos[0] - (TARGET / floor)).abs() < 1e-12);
        assert!(pos[0].abs() < 10.0 + 1e-12);
    }

    #[test]
    fn floor_is_inert_when_vol_above_floor() {
        let floor = 0.005;
        let sizer = VolTargetWithFloor::new(TARGET, floor);
        let plain = VolTarget::new(TARGET);

        let score = [2.0, -0.75];
        let vol = [0.02, 0.008];

        let floored = sizer.compute(&score, &vol);
        let unfloored = plain.compute(&score, &vol);

        for (f, u) in floored.iter().zip(unfloored.iter()) {
            assert!((f - u).abs() < 1e-12);
        }
    }

    #[test]
    fn floor_zero_vol_is_safe_and_floored() {
        let sizer = VolTargetWithFloor::new(TARGET, 0.005);
        let score = [-4.0, 1.5];
        let vol = [0.0, 1e-13];

        let pos = sizer.compute(&score, &vol);

        assert_eq!(pos[0], 0.0);
        assert_eq!(pos[1], 0.0);
        assert!(pos.iter().all(|p| p.is_finite()));
    }

    #[test]
    fn names_are_stable_for_logging() {
        assert_eq!(VolTarget::new(TARGET).name(), "vol_target");
        assert_eq!(
            VolTargetWithFloor::new(TARGET, 0.005).name(),
            "vol_target_with_floor"
        );
    }

    #[test]
    fn trait_object_dispatch_works() {
        let methods: Vec<Box<dyn SizingMethod>> = vec![
            Box::new(VolTarget::new(TARGET)),
            Box::new(VolTargetWithFloor::new(TARGET, 0.005)),
        ];

        let score = [1.0];
        let vol = [0.0005];

        let plain_pos = methods[0].compute(&score, &vol)[0];
        let floored_pos = methods[1].compute(&score, &vol)[0];

        assert!(floored_pos.abs() < plain_pos.abs());
        assert_eq!(methods[0].name(), "vol_target");
        assert_eq!(methods[1].name(), "vol_target_with_floor");
    }
}
