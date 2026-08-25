//! Volatility targeting position sizing.
//!
//! Financial logic: volatility targeting normalizes a standardized composite
//! score (a z-score-like signal) into a target position whose expected risk
//! is a fixed fraction of capital. The position is proportional to
//! `score * target_vol / realized_vol`, so the same signal takes a smaller
//! position in turbulent regimes and a larger one in calm regimes, holding
//! the dollar risk of the book roughly constant through time.

use super::SizingMethod;

/// Plain volatility targeting: position = score * target_vol_daily / vol_est.
///
/// When realized volatility doubles, the position halves, so the expected
/// per-bar PnL variance contribution stays near `target_vol_daily^2`.
pub struct VolTarget {
    /// Daily volatility target as fraction of capital
    /// (e.g. 0.01 targets 1% daily vol, roughly 16% annualized at 250 bars/year).
    pub target_vol_daily: f64,
}

impl VolTarget {
    /// Construct a plain vol-target sizer.
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

/// Volatility targeting with a minimum-volatility floor on the risk estimate.
///
/// Financial logic: a raw vol-target rule scales positions up without bound as
/// realized vol collapses toward zero (e.g. holiday-thinned liquidity or a
/// stale/underestimated vol forecast), which can produce extreme leverage from
/// a noisy denominator. Applying an effective volatility
/// `vol_eff = max(vol_est, vol_floor)` caps the leverage multiplier at
/// `target_vol_daily / vol_floor`: once estimated vol falls below the floor,
/// the position stops growing. The floor should be set to the smallest vol
/// level for which the estimate is still trusted.
pub struct VolTargetWithFloor {
    /// Daily volatility target as fraction of capital.
    pub target_vol_daily: f64,
    /// Minimum trusted daily volatility used in the denominator
    /// (same units as `target_vol_daily`, e.g. 0.005 = 0.5% daily).
    pub vol_floor: f64,
}

impl VolTargetWithFloor {
    /// Construct a floored vol-target sizer.
    ///
    /// Panics if `vol_floor` is not positive; a non-positive floor would be
    /// equivalent to no floor and silently reintroduce unbounded leverage.
    pub fn new(target_vol_daily: f64, vol_floor: f64) -> Self {
        assert!(vol_floor > 0.0, "vol_floor must be positive");
        Self {
            target_vol_daily,
            vol_floor,
        }
    }

    /// Effective volatility used in the denominator after applying the floor.
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
                // v_eff >= vol_floor > 0 by construction, so the division is safe;
                // zero/near-zero inputs are still handled explicitly for clarity.
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

    const TARGET: f64 = 0.01; // 1% daily vol target

    #[test]
    fn vol_target_scales_score_by_target_over_vol() {
        let sizer = VolTarget::new(TARGET);
        let score = [2.0, -1.0, 0.5];
        let vol = [0.02, 0.01, 0.005];

        let pos = sizer.compute(&score, &vol);

        assert_eq!(pos.len(), 3);
        assert!((pos[0] - (2.0 * TARGET / 0.02)).abs() < 1e-12); // 1.0
        assert!((pos[1] - (-1.0 * TARGET / 0.01)).abs() < 1e-12); // -1.0
        assert!((pos[2] - (0.5 * TARGET / 0.005)).abs() < 1e-12); // 1.0
    }

    #[test]
    fn vol_target_zero_vol_is_safe() {
        let sizer = VolTarget::new(TARGET);
        let score = [3.0, -3.0, 1.0];
        let vol = [0.0, 1e-15, 0.01];

        let pos = sizer.compute(&score, &vol);

        // Zero and denormal vol estimates must yield flat positions, not inf/NaN.
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
        let floor = 0.005; // 0.5% daily vol floor
        let sizer = VolTargetWithFloor::new(TARGET, floor);

        // Calm regime: vol well below the floor.
        let score = [1.0];
        let vol = [0.001];

        let pos = sizer.compute(&score, &vol);

        // Without a floor this would be 1.0 * 0.01 / 0.001 = 10x leverage.
        // With the floor it is capped at 0.01 / 0.005 = 2x.
        assert!((pos[0] - (TARGET / floor)).abs() < 1e-12);
        assert!(pos[0].abs() < 10.0 + 1e-12);
    }

    #[test]
    fn floor_is_inert_when_vol_above_floor() {
        let floor = 0.005;
        let sizer = VolTargetWithFloor::new(TARGET, floor);
        let plain = VolTarget::new(TARGET);

        let score = [2.0, -0.75];
        let vol = [0.02, 0.008]; // both above the floor

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

        // Explicit zero-vol guard wins over the floor: flat, finite positions.
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
        let vol = [0.0005]; // deep below the floor

        let plain_pos = methods[0].compute(&score, &vol)[0];
        let floored_pos = methods[1].compute(&score, &vol)[0];

        // Floor must strictly reduce extreme leverage implied by tiny vol.
        assert!(floored_pos.abs() < plain_pos.abs());
        assert_eq!(methods[0].name(), "vol_target");
        assert_eq!(methods[1].name(), "vol_target_with_floor");
    }
}
