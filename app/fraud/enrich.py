"""
One-shot enrichment: raw Kaggle creditcard.csv -> data/creditcard_enriched.csv.
Idempotent under fixed seeds (run twice -> identical bytes).
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

from app.fraud.constants import INTERNATIONAL_CITIES, US_CITIES

RAW_PATH = Path(__file__).resolve().parents[2] / "data" / "creditcard.csv"
OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "creditcard_enriched.csv"

EXPECTED_ROWS = 284_807
EXPECTED_COLS = 31


def _pick_merchant(amount: float, is_fraud: bool, rng: np.random.Generator) -> str:
    if is_fraud and rng.random() < 0.7:
        return str(rng.choice(["Wire Transfer", "International Payment", "ATM Withdrawal"]))
    if amount < 10:
        return str(rng.choice(["Gas Station", "Coffee Shop", "Grocery Store"]))
    if amount < 100:
        return str(rng.choice(["Restaurant", "Retail Store", "Pharmacy", "Subscription Service"]))
    if amount <= 1000:
        return str(rng.choice(["Electronics Store", "Hotel", "Airline"]))
    return str(rng.choice(["Wire Transfer", "International Payment", "Peer Transfer"]))


def _pick_txn_type(is_fraud: bool, rng: np.random.Generator) -> str:
    if is_fraud:
        return "DEBIT" if rng.random() < 0.95 else "CREDIT"
    return "DEBIT" if rng.random() < 0.85 else "CREDIT"


def _pick_location(is_fraud: bool, rng: np.random.Generator) -> str:
    if is_fraud:
        if rng.random() < 0.6:
            return str(rng.choice(INTERNATIONAL_CITIES))
        return str(rng.choice(US_CITIES))
    if rng.random() < 0.92:
        return str(rng.choice(US_CITIES))
    return str(rng.choice(INTERNATIONAL_CITIES))


def enrich_dataframe(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Transform validated raw frame into enriched schema."""
    n = len(df)
    base = pd.Timestamp("2024-01-01T00:00:00", tz="UTC")
    times_sec = pd.to_timedelta(df["Time"].astype("float64"), unit="s")
    ts = base + times_sec
    timestamp_iso = ts.map(lambda t: t.isoformat())

    transaction_id = [f"TXN-{i + 1:06d}" for i in range(n)]

    classes = df["Class"].to_numpy()
    is_fraud = classes == 1
    legit = ~is_fraud

    account_id = np.empty(n, dtype=object)
    # Legitimate rows use ACC-0041–ACC-0800 only so fraud-only accounts (ACC-0001–ACC-0040) stay
    # interpretable for typologies like international-activity spikes.
    account_id[legit] = np.array([f"ACC-{int(x) + 1:04d}" for x in rng.integers(40, 800, size=int(legit.sum()))])
    account_id[is_fraud] = np.array(
        [f"ACC-{int(x) + 1:04d}" for x in rng.integers(0, 40, size=int(is_fraud.sum()))]
    )

    amounts = df["Amount"].astype("float64").to_numpy()
    amount_usd = np.round(amounts, 2)
    # Rare real amounts in the $8k–$9.9k band are spread across accounts; cluster them so
    # structuring-style monitoring can surface on this dataset without changing row count.
    struct_mask = (amount_usd >= 8000) & (amount_usd <= 9900)
    account_id[struct_mask] = "ACC-0800"

    merchant_name = np.empty(n, dtype=object)
    transaction_type = np.empty(n, dtype=object)
    location = np.empty(n, dtype=object)
    for i in range(n):
        fraud_row = bool(is_fraud[i])
        merchant_name[i] = _pick_merchant(float(amounts[i]), fraud_row, rng)
        transaction_type[i] = _pick_txn_type(fraud_row, rng)
        location[i] = _pick_location(fraud_row, rng)

    v_cols = sorted((c for c in df.columns if c.startswith("V")), key=lambda x: int(x[1:]))
    out = pd.DataFrame(
        {
            "transaction_id": transaction_id,
            "timestamp": timestamp_iso,
            "account_id": account_id,
            "merchant_name": merchant_name,
            "transaction_type": transaction_type,
            "location": location,
            "amount_usd": amount_usd,
            "Amount": df["Amount"].values,
            "Class": df["Class"].values,
        }
    )
    for c in v_cols:
        out[c] = df[c].values
    out["Time"] = df["Time"].values
    return out


def main() -> None:
    random.seed(42)
    rng = np.random.default_rng(42)

    if not RAW_PATH.is_file():
        print(f"Missing dataset: {RAW_PATH}", file=sys.stderr)
        sys.exit(1)

    try:
        df = pd.read_csv(RAW_PATH)
    except Exception as e:
        print(f"Failed to read CSV: {e}", file=sys.stderr)
        sys.exit(1)

    if df.shape[0] != EXPECTED_ROWS or df.shape[1] != EXPECTED_COLS:
        raise ValueError(
            f"Expected shape ({EXPECTED_ROWS}, {EXPECTED_COLS}), got {df.shape[0]}, {df.shape[1]}"
        )

    enriched = enrich_dataframe(df, rng)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        enriched.to_csv(OUT_PATH, index=False)
    except Exception as e:
        print(f"Failed to write enriched CSV: {e}", file=sys.stderr)
        sys.exit(1)

    fraud_rows = int((enriched["Class"] == 1).sum())
    legit_rows = int((enriched["Class"] == 0).sum())
    fraud_accounts = enriched.loc[enriched["Class"] == 1, "account_id"].nunique()
    unique_merchants = enriched["merchant_name"].nunique()

    print(f"total rows: {len(enriched)}")
    print(f"fraud rows: {fraud_rows}")
    print(f"legitimate rows: {legit_rows}")
    print(f"unique accounts in fraud set: {fraud_accounts}")
    print(f"unique merchants: {unique_merchants}")
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
