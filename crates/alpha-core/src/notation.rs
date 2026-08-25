//! Typed symbol registry for the mathematical notation used across `alpha-core`.
//!
//! Every formula in the system refers to parameters through these constants
//! instead of hand-written string literals. A typo or an accidental rename is
//! then caught at compile time rather than silently introducing a second,
//! colliding symbol with the same printed name.
//!
//! The registry is intentionally dependency-free so it can be referenced from
//! any module (and compiled standalone) without pulling in the rest of the
//! crate.

/// Registry of validated mathematical symbols and parameter names.
///
/// The struct itself carries no data: it exists purely as a namespace that
/// groups the canonical string constants used by every formula in the system.
///
/// Symbol lookup by string is provided by the free function
/// [`validate_symbol`].
///
/// # Examples
///
/// ```
/// assert_eq!(alpha_core::notation::NotationRegistry::P, "P");
/// assert!(alpha_core::notation::validate_symbol("ICIR"));
/// assert!(!alpha_core::notation::validate_symbol("icir"));
/// ```
pub struct NotationRegistry;

impl NotationRegistry {
    // ------------------------------------------------------------------
    // Position, score, return
    // ------------------------------------------------------------------

    /// Position size (target weight per asset).
    pub const P: &'static str = "P";

    /// Composite score in z units.
    pub const Z: &'static str = "Z";

    /// Realized return over the evaluation horizon.
    pub const R: &'static str = "R";

    // ------------------------------------------------------------------
    // Volatility
    // ------------------------------------------------------------------

    /// Annualized volatility target.
    pub const VOL_TARGET: &'static str = "VOL_TARGET";

    /// Volatility estimate (realized or EWMA based).
    pub const VOL_EST: &'static str = "VOL_EST";

    // ------------------------------------------------------------------
    // Cost
    // ------------------------------------------------------------------

    /// Trading cost per unit notional per side (fee + half spread + buffer).
    pub const C: &'static str = "C";

    /// Minimum cost assumption charged even on costless fills.
    pub const COST_FLOOR: &'static str = "COST_FLOOR";

    // ------------------------------------------------------------------
    // Leverage
    // ------------------------------------------------------------------

    /// Leverage cap, expressed as a multiple of capital.
    pub const L: &'static str = "L";

    // ------------------------------------------------------------------
    // Turnover
    // ------------------------------------------------------------------

    /// One-way portfolio turnover per rebalance.
    pub const TO: &'static str = "TO";

    /// Turnover floor used to keep cost estimates conservative.
    pub const TO_FLOOR: &'static str = "TO_FLOOR";

    // ------------------------------------------------------------------
    // Forecast quality
    // ------------------------------------------------------------------

    /// Information coefficient evaluated at horizon `h`.
    pub const IC_H: &'static str = "IC_H";

    /// Information-coefficient information ratio (mean IC divided by IC std).
    pub const ICIR: &'static str = "ICIR";

    /// Annualized return of a strategy or sleeve.
    pub const R_ANN: &'static str = "R_ANN";

    /// Optimal holding horizon chosen from the IC ladder.
    pub const H_STAR: &'static str = "H_STAR";

    /// Effective number of independent bets.
    pub const N_EFF: &'static str = "N_EFF";

    // ------------------------------------------------------------------
    // Combination weights
    // ------------------------------------------------------------------

    /// Combination weight assigned to alpha `i`.
    pub const W_I: &'static str = "W_I";

    /// Number of alphas entering the combination.
    pub const N_ALPHA: &'static str = "N_ALPHA";

    // ------------------------------------------------------------------
    // Smoothing windows
    // ------------------------------------------------------------------

    /// EWMA decay parameter applied to the score.
    pub const LAMBDA_S: &'static str = "LAMBDA_S";

    /// EWMA smoothing span, in bars.
    pub const SPAN: &'static str = "SPAN";

    /// Rolling mean window length, in bars.
    pub const MEAN_W: &'static str = "MEAN_W";

    /// Rolling standard deviation window length, in bars.
    pub const STD_W: &'static str = "STD_W";

    /// Rolling z-score normalization window length, in bars.
    pub const W_WINDOW: &'static str = "W_WINDOW";

    // ------------------------------------------------------------------
    // Risk multipliers
    // ------------------------------------------------------------------

    /// Position scaler applied while the strategy is in drawdown.
    pub const M_DRAWDOWN: &'static str = "M_DRAWDOWN";

    /// Position scaler applied by the market-regime filter.
    pub const M_REGIME: &'static str = "M_REGIME";

    /// Position scaler produced by the meta model.
    pub const M_META: &'static str = "M_META";

    /// Position scaler applied during the ramp-up period of a new strategy.
    pub const M_RAMPUP: &'static str = "M_RAMPUP";

    // ------------------------------------------------------------------
    // Trade band
    // ------------------------------------------------------------------

    /// No-trade dead-zone threshold, in z units.
    pub const BAND: &'static str = "BAND";

    /// Every registered symbol, grouped by category.
    ///
    /// The compile-time uniqueness assertion below this implementation block
    /// guarantees these values stay distinct.
    pub const ALL_SYMBOLS: [&'static str; 27] = [
        // Position, score, return
        Self::P,
        Self::Z,
        Self::R,
        // Volatility
        Self::VOL_TARGET,
        Self::VOL_EST,
        // Cost
        Self::C,
        Self::COST_FLOOR,
        // Leverage
        Self::L,
        // Turnover
        Self::TO,
        Self::TO_FLOOR,
        // Forecast quality
        Self::IC_H,
        Self::ICIR,
        Self::R_ANN,
        Self::H_STAR,
        Self::N_EFF,
        // Combination weights
        Self::W_I,
        Self::N_ALPHA,
        // Smoothing windows
        Self::LAMBDA_S,
        Self::SPAN,
        Self::MEAN_W,
        Self::STD_W,
        Self::W_WINDOW,
        // Risk multipliers
        Self::M_DRAWDOWN,
        Self::M_REGIME,
        Self::M_META,
        Self::M_RAMPUP,
        // Trade band
        Self::BAND,
    ];
}

/// Returns `true` when `name` matches a registered symbol exactly.
///
/// Matching is case-sensitive and rejects surrounding whitespace, so
/// `"BAND"` validates while `"band"` and `"BAND "` do not.
pub fn validate_symbol(name: &str) -> bool {
    NotationRegistry::ALL_SYMBOLS.contains(&name)
}

// ----------------------------------------------------------------------
// Compile-time collision guard
//
// Fails the build if any two entries of `ALL_SYMBOLS` hold the same
// string, so duplicate notation can never be merged silently.
// ----------------------------------------------------------------------

/// Byte-wise equality usable inside `const` contexts.
const fn const_str_eq(a: &str, b: &str) -> bool {
    let (x, y) = (a.as_bytes(), b.as_bytes());
    if x.len() != y.len() {
        return false;
    }
    let mut k = 0;
    while k < x.len() {
        if x[k] != y[k] {
            return false;
        }
        k += 1;
    }
    true
}

/// Asserts pairwise uniqueness of all registered symbols at compile time.
const fn assert_symbols_unique<const N: usize>(symbols: &[&str; N]) {
    let mut i = 0;
    while i < N {
        let mut j = i + 1;
        while j < N {
            if const_str_eq(symbols[i], symbols[j]) {
                panic!("duplicate notation symbol");
            }
            j += 1;
        }
        i += 1;
    }
}

const _: () = assert_symbols_unique(&NotationRegistry::ALL_SYMBOLS);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn constants_hold_their_canonical_names() {
        assert_eq!(NotationRegistry::P, "P");
        assert_eq!(NotationRegistry::Z, "Z");
        assert_eq!(NotationRegistry::R, "R");
        assert_eq!(NotationRegistry::VOL_TARGET, "VOL_TARGET");
        assert_eq!(NotationRegistry::VOL_EST, "VOL_EST");
        assert_eq!(NotationRegistry::C, "C");
        assert_eq!(NotationRegistry::COST_FLOOR, "COST_FLOOR");
        assert_eq!(NotationRegistry::L, "L");
        assert_eq!(NotationRegistry::TO, "TO");
        assert_eq!(NotationRegistry::TO_FLOOR, "TO_FLOOR");
        assert_eq!(NotationRegistry::IC_H, "IC_H");
        assert_eq!(NotationRegistry::ICIR, "ICIR");
        assert_eq!(NotationRegistry::R_ANN, "R_ANN");
        assert_eq!(NotationRegistry::H_STAR, "H_STAR");
        assert_eq!(NotationRegistry::N_EFF, "N_EFF");
        assert_eq!(NotationRegistry::W_I, "W_I");
        assert_eq!(NotationRegistry::N_ALPHA, "N_ALPHA");
        assert_eq!(NotationRegistry::LAMBDA_S, "LAMBDA_S");
        assert_eq!(NotationRegistry::SPAN, "SPAN");
        assert_eq!(NotationRegistry::MEAN_W, "MEAN_W");
        assert_eq!(NotationRegistry::STD_W, "STD_W");
        assert_eq!(NotationRegistry::W_WINDOW, "W_WINDOW");
        assert_eq!(NotationRegistry::M_DRAWDOWN, "M_DRAWDOWN");
        assert_eq!(NotationRegistry::M_REGIME, "M_REGIME");
        assert_eq!(NotationRegistry::M_META, "M_META");
        assert_eq!(NotationRegistry::M_RAMPUP, "M_RAMPUP");
        assert_eq!(NotationRegistry::BAND, "BAND");
    }

    #[test]
    fn all_symbols_are_nonempty_and_unique() {
        let all = NotationRegistry::ALL_SYMBOLS;
        assert_eq!(
            all.len(),
            27,
            "registry count changed; update ALL_SYMBOLS and its type"
        );
        for (i, sym) in all.iter().enumerate() {
            assert!(!sym.is_empty(), "symbol at index {} is empty", i);
            for other in &all[i + 1..] {
                assert_ne!(sym, other, "duplicate symbol value '{}'", sym);
            }
        }
    }

    #[test]
    fn validate_symbol_accepts_every_registered_symbol() {
        for sym in NotationRegistry::ALL_SYMBOLS.iter() {
            assert!(
                validate_symbol(sym),
                "expected '{}' to be a registered symbol",
                sym
            );
        }
    }

    #[test]
    fn validate_symbol_rejects_unknown_names() {
        for bad in [
            "",
            "p",
            "z",
            "band",
            "Band",
            "BANDS",
            "VOL",
            "Vol_Target",
            "VOL_TARGETS",
            "IC",
            "ICIR_2",
            "TOO",
            "M_",
            "L ",
            " P",
            "COST-FLOOR",
        ] {
            assert!(
                !validate_symbol(bad),
                "expected '{:?}' to be rejected as unknown",
                bad
            );
        }
    }
}
