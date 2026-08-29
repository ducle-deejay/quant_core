pub mod canonical;
pub mod combination;
pub mod evaluation;
pub mod harness_config;
pub mod notation;
pub mod orthogonalization;
pub mod pool;
#[cfg(feature = "python-bindings")]
pub mod python_bindings;
pub mod strategies;

pub use canonical::mapping::CanonicalResult;
pub use canonical::metrics::{max_drawdown, sharpe};
pub use canonical::pnl::PnlResult;
pub use combination::composite_score;
pub use evaluation::deflated_sharpe::{deflated_sharpe_probability, deflated_threshold};
pub use evaluation::gates::{evaluate_gate, GateCriteria, GateInput};
pub use evaluation::ic_ladder::ic_ladder;
pub use evaluation::plateau_sweep::{detect_plateau, make_grid, PlateauResult};
pub use evaluation::trial_ledger::{TrialEntry, TrialLedger};
pub use harness_config::HarnessConfig;
pub use orthogonalization::orthogonalize;
