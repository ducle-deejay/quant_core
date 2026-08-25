pub mod deflated_sharpe;
pub mod gates;
pub mod ic_ladder;
pub mod plateau_sweep;
pub mod screening;
pub mod trial_ledger;
pub mod walk_forward;

pub use deflated_sharpe::{deflated_sharpe_probability, deflated_threshold};
pub use ic_ladder::{ic_ladder, IcResult};
pub use plateau_sweep::{detect_plateau, make_grid, PlateauResult};
pub use screening::{rank_survivors, screen_candidates, ScreeningFunnel, ScreeningThresholds};
pub use trial_ledger::{TrialEntry, TrialLedger};
