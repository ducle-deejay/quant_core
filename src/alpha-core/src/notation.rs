pub struct NotationRegistry;

impl NotationRegistry {

    pub const P: &'static str = "P";

    pub const Z: &'static str = "Z";

    pub const R: &'static str = "R";

    pub const VOL_TARGET: &'static str = "VOL_TARGET";

    pub const VOL_EST: &'static str = "VOL_EST";

    pub const C: &'static str = "C";

    pub const COST_FLOOR: &'static str = "COST_FLOOR";

    pub const L: &'static str = "L";

    pub const TO: &'static str = "TO";

    pub const TO_FLOOR: &'static str = "TO_FLOOR";

    pub const IC_H: &'static str = "IC_H";

    pub const ICIR: &'static str = "ICIR";

    pub const R_ANN: &'static str = "R_ANN";

    pub const H_STAR: &'static str = "H_STAR";

    pub const N_EFF: &'static str = "N_EFF";

    pub const W_I: &'static str = "W_I";

    pub const N_ALPHA: &'static str = "N_ALPHA";

    pub const LAMBDA_S: &'static str = "LAMBDA_S";

    pub const SPAN: &'static str = "SPAN";

    pub const MEAN_W: &'static str = "MEAN_W";

    pub const STD_W: &'static str = "STD_W";

    pub const W_WINDOW: &'static str = "W_WINDOW";

    pub const M_DRAWDOWN: &'static str = "M_DRAWDOWN";

    pub const M_REGIME: &'static str = "M_REGIME";

    pub const M_META: &'static str = "M_META";

    pub const M_RAMPUP: &'static str = "M_RAMPUP";

    pub const BAND: &'static str = "BAND";

    pub const ALL_SYMBOLS: [&'static str; 27] = [

        Self::P,
        Self::Z,
        Self::R,

        Self::VOL_TARGET,
        Self::VOL_EST,

        Self::C,
        Self::COST_FLOOR,

        Self::L,

        Self::TO,
        Self::TO_FLOOR,

        Self::IC_H,
        Self::ICIR,
        Self::R_ANN,
        Self::H_STAR,
        Self::N_EFF,

        Self::W_I,
        Self::N_ALPHA,

        Self::LAMBDA_S,
        Self::SPAN,
        Self::MEAN_W,
        Self::STD_W,
        Self::W_WINDOW,

        Self::M_DRAWDOWN,
        Self::M_REGIME,
        Self::M_META,
        Self::M_RAMPUP,

        Self::BAND,
    ];
}

pub fn validate_symbol(name: &str) -> bool {
    NotationRegistry::ALL_SYMBOLS.contains(&name)
}

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
