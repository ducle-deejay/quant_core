"""Quick entrade demo credential check (never prints secrets).

Verifies the .env credentials against the entrade API and, on success,
prints the investorId needed for ENTRADE_INVESTOR_ID.

Usage: .venv/bin/python3 apps/trading/check_auth.py [--env .env]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from trading.adapters.entrade.client import EntradeClient
from trading.adapters.entrade.client import investor_id_from_token
from trading.adapters.entrade.transport import EntradeClientConfig
from trading.adapters.entrade.transport import EntradeEnvironment


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Check entrade demo credentials")
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    load_dotenv(args.env, override=True)

    import os

    username = os.getenv("ENTRADE_USERNAME", "").strip()
    password = os.getenv("ENTRADE_PASSWORD", "")
    print(
        f"username: {'set' if username else 'EMPTY'} "
        f"(len={len(username)}, digits={username.isdigit()})",
    )
    print(f"password: {'set' if password else 'EMPTY'} (len={len(password)})")
    if not username or not password:
        print("RESULT: credentials missing - fill .env first")
        sys.exit(2)

    client = EntradeClient(EntradeClientConfig(environment=EntradeEnvironment.DEMO))
    try:
        token = client.authenticate(username, password)
    except Exception as error:
        print(f"RESULT: AUTH FAILED - {type(error).__name__}: {error}")
        print(
            "Hints: (1) username must be the entrade partnership account code "
            "(10-digit number), not the DNSE securities account; "
            "(2) check whether a separate trading/API password exists; "
            "(3) the demo account may be expired - re-activate via support.",
        )
        sys.exit(1)

    investor_id = investor_id_from_token(token)
    print("RESULT: AUTH OK")
    print(f"ENTRADE_INVESTOR_ID={investor_id}" if investor_id else
          "ENTRADE_INVESTOR_ID=<not found in token>")


if __name__ == "__main__":
    main()
