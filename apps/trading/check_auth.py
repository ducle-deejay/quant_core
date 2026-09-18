"""Quick entrade demo credential check (never prints secrets).
Usage: .venv/bin/python3 apps/trading/check_auth.py [--env .env]
On success prints the investorId needed for ENTRADE_INVESTOR_ID.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from trading.adapters.entrade.api.entrade_api import EntradeClient
from trading.adapters.entrade.api.entrade_api import investor_id_from_token
from trading.adapters.entrade.api.entrade_api import EntradeClientConfig
from trading.adapters.entrade.api.entrade_api import EntradeAccount


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    """Verify the .env credentials against the entrade API.

    ENTRADE_USERNAME is the entrade login identifier (an email for this
    account), NOT the numeric investor id - the two are different credentials.
    """
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

    client = EntradeClient(EntradeClientConfig(account=EntradeAccount.DEMO))
    try:
        token = client.authenticate(username, password)
    except Exception as error:
        print(f"RESULT: AUTH FAILED - {type(error).__name__}: {error}")
        payload = getattr(error, "payload", None)
        if payload:
            print(f"server payload: {payload}")
        print(
            "Hints: (1) ENTRADE_USERNAME is the entrade login identifier "
            "(an email for this account), not the numeric investor id - "
            "the two are different credentials; "
            "(2) ENTRADE_INVESTOR_ID is printed by this script on success "
            "and may stay unset in .env (auto-resolved from the token).",
        )
        sys.exit(1)

    investor_id = investor_id_from_token(token)
    print("RESULT: AUTH OK")
    print(f"ENTRADE_INVESTOR_ID={investor_id}" if investor_id else
          "ENTRADE_INVESTOR_ID=<not found in token>")


if __name__ == "__main__":
    main()
