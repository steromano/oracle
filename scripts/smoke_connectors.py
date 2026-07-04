#!/usr/bin/env python
"""Live smoke test for Oracle connectors — hits REAL endpoints.

This script is intentionally NOT imported by the pytest suite. Run it manually
to confirm the documented API shapes still match reality and to capture fresh
fixtures:

    uv run python scripts/smoke_connectors.py

It degrades gracefully: connectors without credentials are reported as skipped,
never errors.
"""

from __future__ import annotations

import sys
import traceback

from oracle.connectors import doctor, registry


def _hr(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    _hr("doctor()")
    for name, available, detail in doctor():
        flag = "OK " if available else "-- "
        print(f"  {flag}{name:12s} {detail}")

    reg = registry()

    for name in ("manifold", "metaculus", "polymarket"):
        conn = reg[name]
        _hr(f"{name}.search_markets('interest rate')")
        try:
            matches = conn.search_markets("interest rate")
            print(f"  {len(matches)} matches")
            for m in matches[:3]:
                print(f"    [{m.market_id}] {m.title}  ({m.url})")
            if matches:
                mid = matches[0].market_id
                pp = conn.get_price(mid)
                print(f"  get_price({mid}) -> {pp.price}")
                snap = conn.fetch_snapshot(mid)
                print(
                    f"  fetch_snapshot -> price={snap.price} "
                    f"n_forecasters={snap.n_forecasters} liquidity={snap.liquidity}"
                )
        except Exception:  # pragma: no cover - live network
            traceback.print_exc()

    _hr("fred.get_series('CPIAUCSL')")
    fred = reg["fred"]
    if fred.available():
        try:
            series = fred.get_series("CPIAUCSL")
            print(f"  {len(series)} observations; last -> {series[-1] if series else None}")
        except Exception:  # pragma: no cover - live network
            traceback.print_exc()
    else:
        print("  skipped (FRED_API_KEY not set)")

    _hr("asknews")
    ask = reg["asknews"]
    print(f"  available={ask.available()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
