---
doc_id: DEC-011
title: Two Telegram alert channels - DATA_ and TRADING_ bot pairs, superseding the shared single pair
type: decision
owner: research
status: resolved
version: 1.0
components: [0, 1, 6, 7]
tags: [telegram, alerts, channels, separation]
source: "owner request 2026-08-30: dedicated bots for quant_core, separated from the two legacy nox bots"
design: [STG-1-CANONICAL-SIM]
code: [src/market_data/notify.py, apps/data/daily/pipeline.py, apps/trading/paper.py, .env.example]
test: []
---

# DEC-011 - Two Telegram Alert Channels (DATA_ / TRADING_)

## 1. Decision

Alerting uses two independent bot pairs instead of the single shared pair of DEC-009:

- **Data ingest bot** - `DATA_TELEGRAM_BOT_TOKEN` / `DATA_TELEGRAM_CHAT_ID`, consumed by `market_data.notify.data_notifier_from_env()` and used by the daily ETL entrypoint `apps/data/daily/pipeline.py`.
- **Live trading bot** - `TRADING_TELEGRAM_BOT_TOKEN` / `TRADING_TELEGRAM_CHAT_ID`, consumed by `market_data.notify.trading_notifier_from_env()` and used by `apps/trading/paper.py`.

Each pair must be set together or omitted; there is no hidden fallback between channels. This supersedes the DEC-009 statement that one pair drives all alerts. Both channels keep the same failure-safe transport (alerting errors never break the pipeline or trading loop).

## 2. Rationale

- Operator separation: data-run notifications and trading alerts have different audiences/severities and are easier to triage in separate chats.
- The two legacy nox bots stay untouched; quant_core gets its own bot identities (created via BotFather, e.g. `@quantcore_data_bot` and `@quantcore_trading_bot`).

## Related notes

- [DEC-009](DEC-009-data-sources-and-telegram-alerts.md) - superseded in part (single shared pair)
