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
        tseg = g["_ts"].to_numpy(dtype="datetime64[ns]")
        if len(tseg) < 3:
            continue
        for i in range(len(tseg)):
            t = tseg[i]
            if np.datetime64("nat") == t:
                continue
            left = t - np.timedelta64(24, "h")
            k = int(np.searchsorted(tseg, left, side="right"))
            if i - k + 1 >= 3:
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
    work = work.sort_values(["account_id", "_ts"], kind="mergesort")
    idx_all = work.index.to_numpy()
    acc_all = work["account_id"].to_numpy()
    times_all = work["_ts"].to_numpy(dtype="datetime64[ns]")
    types_all = work["transaction_type"].to_numpy()
    amt_all = work["amount_usd"].astype(float).to_numpy()

    flagged_rows: list[int] = []
    n = len(work)
    start = 0
    while start < n:
        end = start + 1
        a0 = acc_all[start]
        while end < n and acc_all[end] == a0:
            end += 1
        times = times_all[start:end]
        deb = np.where(types_all[start:end] == "DEBIT", amt_all[start:end], 0.0)
        cred = np.where(types_all[start:end] == "CREDIT", amt_all[start:end], 0.0)
        deb_ps = np.cumsum(deb)
        cred_ps = np.cumsum(cred)
        j = 0
        m = end - start
        for i in range(m):
            t = times[i]
            if np.datetime64("nat") == t:
                continue
            left = t - np.timedelta64(48, "h")
            while j <= i and times[j] <= left:
                j += 1
            deb_sum = deb_ps[i] - (deb_ps[j - 1] if j > 0 else 0.0)
            cred_sum = cred_ps[i] - (cred_ps[j - 1] if j > 0 else 0.0)
            if cred_sum > 5000 and deb_sum / cred_sum > 0.85:
                flagged_rows.append(int(idx_all[start + i]))
        start = end

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
    work = work.sort_values(["account_id", "_ts"], kind="mergesort")
    idx_all = work.index.to_numpy()
    acc_all = work["account_id"].to_numpy()
    times_all = work["_ts"].to_numpy(dtype="datetime64[ns]")

    flagged_rows: list[int] = []
    n = len(work)
    start = 0
    while start < n:
        end = start + 1
        a0 = acc_all[start]
        while end < n and acc_all[end] == a0:
            end += 1
        sub = times_all[start:end]
        for i in range(len(sub)):
            t = sub[i]
            if np.datetime64("nat") == t:
                continue
            left = t - np.timedelta64(1, "h")
            k = int(np.searchsorted(sub, left, side="right"))
            if i - k + 1 > 8:
                flagged_rows.append(int(idx_all[start + i]))
        start = end

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
