"""Phase 3 verification: Gemini explainer + Redis cache."""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import redis.asyncio as redis

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fraud.detector import run_all_rules  # noqa: E402
from app.fraud.explainer import FALLBACK, explain_transaction  # noqa: E402

ENRICHED = ROOT / "data" / "creditcard_enriched.csv"


async def _main_async() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        raise SystemExit("GOOGLE_API_KEY is required for explainer verification.")

    if not ENRICHED.is_file():
        raise SystemExit(f"Missing {ENRICHED} — run enrichment and detector setup first.")

    r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    try:
        df = pd.read_csv(ENRICHED)
        flagged, _summary = run_all_rules(df)
        if flagged.empty:
            raise SystemExit("No flagged transactions to explain.")

        row = flagged.iloc[0]
        rt = row["rules_triggered"]
        if isinstance(rt, np.ndarray):
            rt = rt.tolist()
        if not isinstance(rt, list):
            rt = [str(rt)]
        txn = {
            "transaction_id": str(row["transaction_id"]),
            "account_id": str(row["account_id"]),
            "amount_usd": float(row["amount_usd"]),
            "merchant_name": str(row["merchant_name"]),
            "location": str(row["location"]),
            "timestamp": str(row["timestamp"]),
            "transaction_type": str(row["transaction_type"]),
            "rules_triggered": rt,
            "risk_score": int(row["risk_score"]),
            "risk_label": str(row["risk_label"]),
        }

        cache_key = f"fraud:explain:{txn['transaction_id']}"
        await r.delete(cache_key)

        t0 = time.perf_counter()
        first, cached1 = await explain_transaction(r, txn)
        t1 = time.perf_counter()
        second, cached2 = await explain_transaction(r, txn)
        t2 = time.perf_counter()

        assert isinstance(first, str) and len(first) > 0
        assert first.strip() != FALLBACK.strip(), "expected live Gemini text, got fallback"
        assert cached1 is False
        assert cached2 is True
        assert (t2 - t1) < 0.1

        print("test_explainer: all assertions passed")
        print(first[:500] + ("..." if len(first) > 500 else ""))
    finally:
        await r.aclose()


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
