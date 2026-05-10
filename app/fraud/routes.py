from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from app.fraud.detector import run_all_rules
from app.fraud.explainer import explain_transaction

router = APIRouter(prefix="/fraud", tags=["Fraud Intelligence"])

REDIS_ANALYSIS_KEY = "fraud:latest_analysis"
REDIS_SUMMARY_KEY = "fraud:latest_summary"
ANALYSIS_TTL_SEC = 3600

REQUIRED_COLUMNS = [
    "transaction_id",
    "account_id",
    "amount_usd",
    "merchant_name",
    "location",
    "timestamp",
    "transaction_type",
    "Class",
]


class TransactionAlert(BaseModel):
    transaction_id: str
    account_id: str | None = None
    amount_usd: float | None = None
    merchant_name: str | None = None
    location: str | None = None
    timestamp: str | None = None
    transaction_type: str | None = None
    rules_triggered: list[str] = Field(default_factory=list)
    risk_score: int | None = None
    risk_label: str | None = None
    flagged_at: str | None = None


class FraudAnalysisSummary(BaseModel):
    total_analyzed: int
    total_flagged: int
    by_rule: dict[str, int]
    by_risk_label: dict[str, int]
    alerts: list[TransactionAlert]


class ExplainResponse(BaseModel):
    transaction_id: str
    ai_explanation: str
    cached: bool


class FraudStats(BaseModel):
    total_analyzed: int = 0
    total_alerts: int
    by_risk_label: dict[str, int]
    by_rule: dict[str, int]
    top_accounts: list[dict[str, Any]]
    analysis_timestamp: str


def _row_to_alert(row: pd.Series) -> TransactionAlert:
    rt = row.get("rules_triggered")
    if isinstance(rt, str):
        try:
            rt = json.loads(rt)
        except Exception:
            rt = [rt]
    if not isinstance(rt, list):
        rt = []
    return TransactionAlert(
        transaction_id=str(row["transaction_id"]),
        account_id=None if pd.isna(row.get("account_id")) else str(row["account_id"]),
        amount_usd=None if pd.isna(row.get("amount_usd")) else float(row["amount_usd"]),
        merchant_name=None if pd.isna(row.get("merchant_name")) else str(row["merchant_name"]),
        location=None if pd.isna(row.get("location")) else str(row["location"]),
        timestamp=None if pd.isna(row.get("timestamp")) else str(row["timestamp"]),
        transaction_type=None if pd.isna(row.get("transaction_type")) else str(row["transaction_type"]),
        rules_triggered=[str(x) for x in rt],
        risk_score=None if pd.isna(row.get("risk_score")) else int(row["risk_score"]),
        risk_label=None if pd.isna(row.get("risk_label")) else str(row["risk_label"]),
        flagged_at=None if pd.isna(row.get("flagged_at")) else str(row["flagged_at"]),
    )


async def _load_analysis_df(redis: Any) -> pd.DataFrame | None:
    try:
        raw = await redis.get(REDIS_ANALYSIS_KEY)
    except Exception:
        raw = None
    if raw is None:
        return None
    try:
        return pd.read_json(io.StringIO(raw), orient="records")
    except Exception:
        return None


@router.post("/analyze", response_model=FraudAnalysisSummary)
async def analyze_transactions(request: Request, file: UploadFile = File(...)):
    try:
        redis = request.app.state.redis
        fname = file.filename or ""
        if not fname.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="Upload must be a .csv file")

        try:
            content = await file.read()
            df = pd.read_csv(io.BytesIO(content))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read CSV: {e}") from e

        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required columns: {', '.join(missing)}",
            )

        try:
            flagged, summary = run_all_rules(df)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Detection failed: {e}") from e

        summary = dict(summary)
        summary["analysis_timestamp"] = datetime.now(timezone.utc).isoformat()

        try:
            payload = flagged.to_json(orient="records", date_format="iso")
            await redis.set(REDIS_ANALYSIS_KEY, payload, ex=ANALYSIS_TTL_SEC)
            await redis.set(REDIS_SUMMARY_KEY, json.dumps(summary), ex=ANALYSIS_TTL_SEC)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to persist analysis: {e}") from e

        alerts: list[TransactionAlert] = []
        if not flagged.empty:
            for _, row in flagged.head(100).iterrows():
                alerts.append(_row_to_alert(row))

        return FraudAnalysisSummary(
            total_analyzed=int(summary["total_analyzed"]),
            total_flagged=int(summary["total_flagged"]),
            by_rule=dict(summary["by_rule"]),
            by_risk_label=dict(summary["by_risk_label"]),
            alerts=alerts,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/alerts", response_model=list[TransactionAlert])
async def get_alerts(
    request: Request,
    risk_label: str | None = Query(None),
    rule_name: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    redis = request.app.state.redis
    df = await _load_analysis_df(redis)
    if df is None:
        raise HTTPException(
            status_code=404,
            detail="No analysis results found. Upload a CSV to /fraud/analyze first.",
        )
    if df.empty:
        return []

    out = df
    if risk_label:
        out = out[out["risk_label"].astype(str) == risk_label]
    if rule_name:
        def _has_rule(cell: Any) -> bool:
            if isinstance(cell, list):
                return rule_name in [str(x) for x in cell]
            if isinstance(cell, str):
                try:
                    parsed = json.loads(cell)
                    if isinstance(parsed, list):
                        return rule_name in [str(x) for x in parsed]
                except Exception:
                    return rule_name in cell
            return False

        out = out[out["rules_triggered"].apply(_has_rule)]

    start = (page - 1) * page_size
    chunk = out.iloc[start : start + page_size]
    return [_row_to_alert(row) for _, row in chunk.iterrows()]


@router.get("/alerts/{transaction_id}/explain", response_model=ExplainResponse)
async def explain_alert(request: Request, transaction_id: str):
    redis = request.app.state.redis
    df = await _load_analysis_df(redis)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail="No analysis results found. Upload a CSV to /fraud/analyze first.")

    hit = df[df["transaction_id"].astype(str) == str(transaction_id)]
    if hit.empty:
        raise HTTPException(status_code=404, detail="Transaction not found in latest analysis.")

    row = hit.iloc[0]
    txn = {
        "transaction_id": str(row["transaction_id"]),
        "account_id": str(row["account_id"]),
        "amount_usd": float(row["amount_usd"]),
        "merchant_name": str(row["merchant_name"]),
        "location": str(row["location"]),
        "timestamp": str(row["timestamp"]),
        "transaction_type": str(row["transaction_type"]),
        "rules_triggered": _row_to_alert(row).rules_triggered,
        "risk_score": int(row["risk_score"]),
        "risk_label": str(row["risk_label"]),
    }

    expl, was_cached = await explain_transaction(redis, txn)
    return ExplainResponse(transaction_id=str(transaction_id), ai_explanation=expl, cached=was_cached)


@router.get("/stats", response_model=FraudStats)
async def get_stats(request: Request):
    redis = request.app.state.redis
    df = await _load_analysis_df(redis)
    if df is None:
        raise HTTPException(
            status_code=404,
            detail="No analysis results found. Upload a CSV to /fraud/analyze first.",
        )

    if df.empty:
        ts = ""
        total_analyzed = 0
        try:
            raw_summary = await redis.get(REDIS_SUMMARY_KEY)
            if raw_summary:
                s = json.loads(raw_summary)
                ts = str(s.get("analysis_timestamp", ""))
                total_analyzed = int(s.get("total_analyzed") or 0)
        except Exception:
            pass
        return FraudStats(
            total_analyzed=total_analyzed,
            total_alerts=0,
            by_risk_label={},
            by_rule={},
            top_accounts=[],
            analysis_timestamp=ts,
        )

    try:
        raw_summary = await redis.get(REDIS_SUMMARY_KEY)
        summary = json.loads(raw_summary) if raw_summary else {}
    except Exception:
        summary = {}

    by_risk = dict(summary.get("by_risk_label") or {})
    by_rule = dict(summary.get("by_rule") or {})
    total_alerts = int(summary.get("total_flagged") or len(df))

    if not by_risk and "risk_label" in df.columns:
        by_risk = {str(k): int(v) for k, v in df["risk_label"].value_counts().items()}
    if not by_rule:
        counts: dict[str, int] = {}
        for _, row in df.iterrows():
            for rname in _row_to_alert(row).rules_triggered:
                counts[rname] = counts.get(rname, 0) + 1
        by_rule = counts

    counts = df.groupby("account_id").size().sort_values(ascending=False).head(10)
    top_accounts = [{"account_id": str(acc), "alert_count": int(cnt)} for acc, cnt in counts.items()]

    ts = summary.get("analysis_timestamp")
    if not ts and "flagged_at" in df.columns:
        ts = df["flagged_at"].max()

    total_analyzed = int(summary.get("total_analyzed") or 0)

    return FraudStats(
        total_analyzed=total_analyzed,
        total_alerts=total_alerts,
        by_risk_label=by_risk,
        by_rule=by_rule,
        top_accounts=top_accounts,
        analysis_timestamp=str(ts or ""),
    )
