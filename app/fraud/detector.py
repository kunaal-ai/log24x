"""
Rule-based fraud detection on enriched transaction data.
Pure pandas/numpy; no I/O or LLM.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.fraud.constants import US_CITIES

RULE_ORDER = [
    "STRUCTURING",
    "RAPID_MOVEMENT",
    "INTL_SPIKE",
    "ROUND_AMOUNT",
    "HIGH_VELOCITY",
]


def _parse_ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def detect_structuring(df: pd.DataFrame) -> pd.DataFrame:
    """3+ transactions between $8k–$9.9k in a rolling 24h window (per account)."""
    work = df.copy()
    work["_ts"] = _parse_ts(work["timestamp"])
    band = work[(work["amount_usd"].astype(float) >= 8000) & (work["amount_usd"].astype(float) <= 9900)].copy()
    if band.empty:
        return pd.DataFrame()

    bad_accounts: set[str] = set()
    for acc, g in band.groupby("account_id", sort=False):
        g = g.sort_values("_ts")
        for _, row in g.iterrows():
            t = row["_ts"]
            if pd.isna(t):
                continue
            lo = t - pd.Timedelta(hours=24)
            cnt = int(((g["_ts"] > lo) & (g["_ts"] <= t)).sum())
            if cnt >= 3:
                bad_accounts.add(str(acc))
                break

    if not bad_accounts:
        return pd.DataFrame()

    out = band[band["account_id"].isin(bad_accounts)].copy()
    out["rule_name"] = "STRUCTURING"
    out["rule_description"] = (
        "Multiple transactions between $8,000 and $9,900 landed within 24 hours, "
        "consistent with structuring to stay under reporting thresholds."
    )
    return out.drop(columns=["_ts"], errors="ignore")


def detect_rapid_movement(df: pd.DataFrame) -> pd.DataFrame:
    """Debit outflow >85% of credit inflow in a rolling 48h window, with credit > $5k."""
    work = df.copy()
    work["_ts"] = _parse_ts(work["timestamp"])
    flagged_rows: list[int] = []
    for _, g in work.groupby("account_id", sort=False):
        g = g.sort_values("_ts")
        for idx, row in g.iterrows():
            t = row["_ts"]
            if pd.isna(t):
                continue
            win = g[(g["_ts"] > t - pd.Timedelta(hours=48)) & (g["_ts"] <= t)]
            deb = float(win.loc[win["transaction_type"] == "DEBIT", "amount_usd"].astype(float).sum())
            cred = float(win.loc[win["transaction_type"] == "CREDIT", "amount_usd"].astype(float).sum())
            if cred > 5000 and deb / cred > 0.85:
                flagged_rows.append(idx)

    if not flagged_rows:
        return pd.DataFrame()

    out = work.loc[flagged_rows].copy()
    out["rule_name"] = "RAPID_MOVEMENT"
    out["rule_description"] = (
        "Outbound debits consumed more than 85% of inbound credits within 48 hours with material credit volume, "
        "suggesting rapid movement of funds."
    )
    return out.drop(columns=["_ts"], errors="ignore")


def detect_international_spike(df: pd.DataFrame) -> pd.DataFrame:
    """International share spikes vs. mostly domestic history for the account."""
    work = df.copy()
    work["_intl"] = ~work["location"].isin(US_CITIES)
    bad_accounts: set[str] = set()
    for acc, g in work.groupby("account_id", sort=False):
        total = len(g)
        if total < 5:
            continue
        intl_n = int(g["_intl"].sum())
        if intl_n >= 2 and (intl_n / total) > 0.3:
            bad_accounts.add(str(acc))

    if not bad_accounts:
        return pd.DataFrame()

    out = work[work["account_id"].isin(bad_accounts)].copy()
    out["rule_name"] = "INTL_SPIKE"
    out["rule_description"] = (
        "A mostly domestic profile now shows a concentrated burst of international activity, "
        "which often warrants geography and beneficiary review."
    )
    return out.drop(columns=["_intl"], errors="ignore")


def detect_round_numbers(df: pd.DataFrame) -> pd.DataFrame:
    """Large, exact thousand-dollar wires/transfers."""
    amt = df["amount_usd"].astype(float).to_numpy()
    rem = np.remainder(amt, 1000)
    is_round_thousand = (amt >= 5000) & np.isclose(rem, 0.0, rtol=0.0, atol=1e-6)
    out = df.loc[is_round_thousand].copy()
    if out.empty:
        return pd.DataFrame()
    out["rule_name"] = "ROUND_AMOUNT"
    out["rule_description"] = (
        "The amount is a large round thousand-dollar figure, a pattern frequently seen in manually staged fraud transfers."
    )
    return out


def detect_velocity(df: pd.DataFrame) -> pd.DataFrame:
    """More than eight transactions in any rolling one-hour window."""
    work = df.copy()
    work["_ts"] = _parse_ts(work["timestamp"])
    flagged_rows: list[int] = []
    for _, g in work.groupby("account_id", sort=False):
        g = g.sort_values("_ts")
        for idx, row in g.iterrows():
            t = row["_ts"]
            if pd.isna(t):
                continue
            win = g[(g["_ts"] > t - pd.Timedelta(hours=1)) & (g["_ts"] <= t)]
            if len(win) > 8:
                flagged_rows.append(idx)

    if not flagged_rows:
        return pd.DataFrame()

    out = work.loc[flagged_rows].copy()
    out["rule_name"] = "HIGH_VELOCITY"
    out["rule_description"] = (
        "Transaction frequency spiked to more than eight events within an hour, well outside typical retail pacing."
    )
    return out.drop(columns=["_ts"], errors="ignore")


def run_all_rules(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Run all detectors, merge multi-rule hits per transaction, score and label.
    Returns (flagged_sorted_desc_by_risk, summary_dict).
    """
    detectors = [
        detect_structuring,
        detect_rapid_movement,
        detect_international_spike,
        detect_round_numbers,
        detect_velocity,
    ]
    parts: list[pd.DataFrame] = []
    for fn in detectors:
        try:
            flagged = fn(df)
        except Exception:
            flagged = pd.DataFrame()
        if flagged is not None and not flagged.empty:
            parts.append(flagged)

    summary = {
        "total_analyzed": int(len(df)),
        "total_flagged": 0,
        "by_rule": {name: 0 for name in RULE_ORDER},
        "by_risk_label": {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CONFIRMED_FRAUD": 0},
    }

    if not parts:
        return pd.DataFrame(), summary

    stacked = pd.concat(parts, ignore_index=True)
    for name in RULE_ORDER:
        summary["by_rule"][name] = int(
            stacked.loc[stacked["rule_name"] == name, "transaction_id"].nunique()
        )

    merged_rows: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for _, g in stacked.groupby("transaction_id", sort=False):
        rules = list(dict.fromkeys(g["rule_name"].astype(str).tolist()))
        base = g.iloc[0]
        cls = int(base.get("Class", 0) or 0)
        n_rules = len(rules)
        if cls == 1:
            score = 100
        elif n_rules >= 3:
            score = 90
        elif n_rules == 2:
            score = 60
        else:
            score = 30

        if score == 100:
            label = "CONFIRMED_FRAUD"
        elif score == 90:
            label = "HIGH"
        elif score == 60:
            label = "MEDIUM"
        else:
            label = "LOW"

        merged_rows.append(
            {
                "transaction_id": str(base["transaction_id"]),
                "account_id": str(base["account_id"]),
                "amount_usd": float(base["amount_usd"]),
                "merchant_name": str(base["merchant_name"]),
                "location": str(base["location"]),
                "timestamp": str(base["timestamp"]),
                "transaction_type": str(base["transaction_type"]),
                "Class": cls,
                "rules_triggered": rules,
                "risk_score": score,
                "risk_label": label,
                "flagged_at": now,
            }
        )

    out_df = pd.DataFrame(merged_rows)
    out_df = out_df.sort_values("risk_score", ascending=False, kind="mergesort").reset_index(drop=True)

    summary["total_flagged"] = int(len(out_df))
    for lbl, cnt in out_df["risk_label"].value_counts().items():
        summary["by_risk_label"][str(lbl)] = int(cnt)

    return out_df, summary
