pub mod mapping;
pub mod metrics;
pub mod pnl;

pub use mapping::{canonical_map, CanonicalResult};
pub use metrics::{max_drawdown, sharpe};
pub use pnl::compute_pnl;
