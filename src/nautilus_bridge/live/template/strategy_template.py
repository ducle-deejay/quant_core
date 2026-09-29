"""Strategy template — the complete public surface of nautilus_trader Strategy."""
from nautilus_trader.trading import Strategy
from nautilus_trader.config import StrategyConfig

class MyStrategyConfig(StrategyConfig):
    def __init__(self, **_kwargs) -> None:
        super().__init__()

class MyStrategy(Strategy):
    def __init__(self, config: MyStrategyConfig) -> None:
        super().__init__(config)

    # Properties inherited from the base class (never override): cache, clock, config, log, order_factory, portfolio, registered_indicators, strategy_id, trader_id

    # Lifecycle hooks
    def on_bar(self, bar) -> None:
        raise NotImplementedError
    def on_book(self, book) -> None:
        raise NotImplementedError
    def on_book_deltas(self, deltas) -> None:
        raise NotImplementedError
    def on_book_depth(self, depth) -> None:
        raise NotImplementedError
    def on_data(self, data) -> None:
        raise NotImplementedError
    def on_degrade(self) -> None:
        raise NotImplementedError
    def on_dispose(self) -> None:
        raise NotImplementedError
    def on_fault(self) -> None:
        raise NotImplementedError
    def on_funding_rate(self, funding_rate) -> None:
        raise NotImplementedError
    def on_historical_bars(self, bars) -> None:
        raise NotImplementedError
    def on_historical_book_deltas(self, deltas) -> None:
        raise NotImplementedError
    def on_historical_book_depth(self, depths) -> None:
        raise NotImplementedError
    def on_historical_data(self, data) -> None:
        raise NotImplementedError
    def on_historical_funding_rates(self, funding_rates) -> None:
        raise NotImplementedError
    def on_historical_index_prices(self, index_prices) -> None:
        raise NotImplementedError
    def on_historical_mark_prices(self, mark_prices) -> None:
        raise NotImplementedError
    def on_historical_quotes(self, quotes) -> None:
        raise NotImplementedError
    def on_historical_trades(self, trades) -> None:
        raise NotImplementedError
    def on_index_price(self, index_price) -> None:
        raise NotImplementedError
    def on_instrument(self, instrument) -> None:
        raise NotImplementedError
    def on_instrument_close(self, close) -> None:
        raise NotImplementedError
    def on_instrument_status(self, status) -> None:
        raise NotImplementedError
    def on_load(self, state) -> None:
        raise NotImplementedError
    def on_mark_price(self, mark_price) -> None:
        raise NotImplementedError
    def on_market_exit(self) -> None:
        raise NotImplementedError
    def on_option_chain(self, slice) -> None:
        raise NotImplementedError
    def on_option_greeks(self, greeks) -> None:
        raise NotImplementedError
    def on_order_accepted(self, event) -> None:
        raise NotImplementedError
    def on_order_cancel_rejected(self, event) -> None:
        raise NotImplementedError
    def on_order_canceled(self, event) -> None:
        raise NotImplementedError
    def on_order_denied(self, event) -> None:
        raise NotImplementedError
    def on_order_emulated(self, event) -> None:
        raise NotImplementedError
    def on_order_event(self, event) -> None:
        raise NotImplementedError
    def on_order_expired(self, event) -> None:
        raise NotImplementedError
    def on_order_fill_voided(self, event) -> None:
        raise NotImplementedError
    def on_order_filled(self, event) -> None:
        raise NotImplementedError
    def on_order_initialized(self, event) -> None:
        raise NotImplementedError
    def on_order_modify_rejected(self, event) -> None:
        raise NotImplementedError
    def on_order_pending_cancel(self, event) -> None:
        raise NotImplementedError
    def on_order_pending_update(self, event) -> None:
        raise NotImplementedError
    def on_order_rejected(self, event) -> None:
        raise NotImplementedError
    def on_order_released(self, event) -> None:
        raise NotImplementedError
    def on_order_submitted(self, event) -> None:
        raise NotImplementedError
    def on_order_triggered(self, event) -> None:
        raise NotImplementedError
    def on_order_updated(self, event) -> None:
        raise NotImplementedError
    def on_position_changed(self, event) -> None:
        raise NotImplementedError
    def on_position_closed(self, event) -> None:
        raise NotImplementedError
    def on_position_event(self, event) -> None:
        raise NotImplementedError
    def on_position_opened(self, event) -> None:
        raise NotImplementedError
    def on_queue_state(self, event) -> None:
        raise NotImplementedError
    def on_quote(self, quote) -> None:
        raise NotImplementedError
    def on_reset(self) -> None:
        raise NotImplementedError
    def on_resume(self) -> None:
        raise NotImplementedError
    def on_save(self) -> None:
        raise NotImplementedError
    def on_signal(self, signal) -> None:
        raise NotImplementedError
    def on_socket_state(self, event) -> None:
        raise NotImplementedError
    def on_start(self) -> None:
        raise NotImplementedError
    def on_stop(self) -> None:
        raise NotImplementedError
    def on_time_event(self, event) -> None:
        raise NotImplementedError
    def on_trade(self, trade) -> None:
        raise NotImplementedError

    # Indicators
    def indicators_initialized(self) -> None:
        raise NotImplementedError
    def register_indicator_for_bars(self, bar_type, indicator) -> None:
        raise NotImplementedError
    def register_indicator_for_quote_ticks(self, instrument_id, indicator) -> None:
        raise NotImplementedError
    def register_indicator_for_trade_ticks(self, instrument_id, indicator) -> None:
        raise NotImplementedError

    # Orders & positions
    def cancel_all_orders(self, instrument_id, order_side=None, client_id=None, strategy_only=True, params=None) -> None:
        raise NotImplementedError
    def cancel_gtd_expiry(self, order) -> None:
        raise NotImplementedError
    def cancel_order(self, client_order_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def cancel_orders(self, client_order_ids, client_id=None, params=None) -> None:
        raise NotImplementedError
    def close_all_positions(self, instrument_id, position_side=None, client_id=None, tags=None, time_in_force=None, reduce_only=None, quote_quantity=None, params=None) -> None:
        raise NotImplementedError
    def close_position(self, position, client_id=None, tags=None, time_in_force=None, reduce_only=None, quote_quantity=None, params=None) -> None:
        raise NotImplementedError
    def is_exiting(self) -> None:
        raise NotImplementedError
    def market_exit(self) -> None:
        raise NotImplementedError
    def modify_order(self, client_order_id, quantity=None, price=None, trigger_price=None, client_id=None, params=None) -> None:
        raise NotImplementedError
    def modify_orders(self, updates, client_id=None, params=None) -> None:
        raise NotImplementedError
    def post_market_exit(self) -> None:
        raise NotImplementedError
    def query_account(self, account_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def query_order(self, order, client_id=None, params=None) -> None:
        raise NotImplementedError
    def set_external_order_instrument_ids(self, instrument_ids) -> None:
        raise NotImplementedError
    def submit_order(self, order, position_id=None, client_id=None, params=None) -> None:
        raise NotImplementedError
    def submit_order_list(self, order_list, position_id=None, client_id=None, params=None) -> None:
        raise NotImplementedError

    # Synthetic instruments
    def add_synthetic(self, synthetic) -> None:
        raise NotImplementedError
    def update_synthetic(self, synthetic) -> None:
        raise NotImplementedError

    # Component control (system-called; delete these overrides in a real component)
    def degrade(self) -> None:
        raise NotImplementedError
    def dispose(self) -> None:
        raise NotImplementedError
    def fault(self) -> None:
        raise NotImplementedError
    def is_degraded(self) -> None:
        raise NotImplementedError
    def is_disposed(self) -> None:
        raise NotImplementedError
    def is_faulted(self) -> None:
        raise NotImplementedError
    def is_ready(self) -> None:
        raise NotImplementedError
    def is_running(self) -> None:
        raise NotImplementedError
    def is_stopped(self) -> None:
        raise NotImplementedError
    def load(self, state) -> None:
        raise NotImplementedError
    def reconnect_socket(self, client_id, endpoint) -> None:
        raise NotImplementedError
    def reset(self) -> None:
        raise NotImplementedError
    def resume(self) -> None:
        raise NotImplementedError
    def save(self) -> None:
        raise NotImplementedError
    def shutdown_system(self, reason=None) -> None:
        raise NotImplementedError
    def start(self) -> None:
        raise NotImplementedError
    def state(self) -> None:
        raise NotImplementedError
    def stop(self) -> None:
        raise NotImplementedError

    # Remaining surface
    def publish_data(self, data_type, data) -> None:
        raise NotImplementedError
    def publish_message(self, topic, message) -> None:
        raise NotImplementedError
    def publish_signal(self, name, value, ts_event=0) -> None:
        raise NotImplementedError
    def request_bars(self, bar_type, start=None, end=None, limit=None, client_id=None, params=None) -> None:
        raise NotImplementedError
    def request_book_deltas(self, instrument_id, start=None, end=None, limit=None, client_id=None, params=None) -> None:
        raise NotImplementedError
    def request_book_depth(self, instrument_id, start=None, end=None, limit=None, depth=None, client_id=None, params=None) -> None:
        raise NotImplementedError
    def request_book_snapshot(self, instrument_id, depth=None, client_id=None, params=None) -> None:
        raise NotImplementedError
    def request_data(self, data_type, client_id, start=None, end=None, limit=None, params=None) -> None:
        raise NotImplementedError
    def request_funding_rates(self, instrument_id, start=None, end=None, limit=None, client_id=None, params=None) -> None:
        raise NotImplementedError
    def request_instrument(self, instrument_id, start=None, end=None, client_id=None, params=None) -> None:
        raise NotImplementedError
    def request_instruments(self, venue=None, start=None, end=None, client_id=None, params=None) -> None:
        raise NotImplementedError
    def request_quotes(self, instrument_id, start=None, end=None, limit=None, client_id=None, params=None) -> None:
        raise NotImplementedError
    def request_trades(self, instrument_id, start=None, end=None, limit=None, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_bars(self, bar_type, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_book_at_interval(self, instrument_id, book_type, interval_ms, depth=None, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_book_deltas(self, instrument_id, book_type, depth=None, client_id=None, managed=False, params=None) -> None:
        raise NotImplementedError
    def subscribe_book_depth10(self, instrument_id, book_type, client_id=None, managed=False, params=None) -> None:
        raise NotImplementedError
    def subscribe_data(self, data_type, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_funding_rates(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_index_prices(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_instrument(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_instrument_close(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_instrument_status(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_instruments(self, venue, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_mark_prices(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_option_chain(self, series_id, strike_range, snapshot_interval_ms=None, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_option_greeks(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_queue_state(self, channel=None, priority=None) -> None:
        raise NotImplementedError
    def subscribe_quotes(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def subscribe_signal(self, name='', priority=None) -> None:
        raise NotImplementedError
    def subscribe_socket_state(self, client_id=None, endpoint=None, priority=None) -> None:
        raise NotImplementedError
    def subscribe_topic(self, topic, handler, priority=0) -> None:
        raise NotImplementedError
    def subscribe_trades(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_bars(self, bar_type, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_book_at_interval(self, instrument_id, interval_ms, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_book_deltas(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_book_depth10(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_data(self, data_type, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_funding_rates(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_index_prices(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_instrument(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_instrument_close(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_instrument_status(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_instruments(self, venue, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_mark_prices(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_option_chain(self, series_id, client_id=None) -> None:
        raise NotImplementedError
    def unsubscribe_option_greeks(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_queue_state(self, channel=None) -> None:
        raise NotImplementedError
    def unsubscribe_quotes(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
    def unsubscribe_signal(self, name) -> None:
        raise NotImplementedError
    def unsubscribe_socket_state(self, client_id=None, endpoint=None) -> None:
        raise NotImplementedError
    def unsubscribe_topic(self, topic, handler) -> None:
        raise NotImplementedError
    def unsubscribe_trades(self, instrument_id, client_id=None, params=None) -> None:
        raise NotImplementedError
