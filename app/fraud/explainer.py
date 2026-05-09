"""
Gemini-backed fraud explanations with Redis caching (async).
Uses the same google-genai client pattern as the rest of the app.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from google import genai

SYSTEM_PROMPT = """
You are a senior fraud analyst at a bank reviewing flagged transactions.
Your job is to write a brief, plain English explanation of why a transaction
looks suspicious, what fraud typology it most likely matches, and what you
would investigate next. Write 3 to 5 sentences maximum. Write like you are
briefing a junior analyst, not writing a formal report. Do not use bullet
points. Do not start with 'This transaction'. Be direct and specific.
"""

FALLBACK = (
    "Automated explanation temporarily unavailable. Review transaction details and triggered rules manually."
)


def build_prompt(txn: dict) -> str:
    rules = txn.get("rules_triggered") or []
    if isinstance(rules, str):
        rules_list = [rules]
    else:
        rules_list = list(rules)
    amt = float(txn.get("amount_usd", 0.0))
    return f"""
Review this flagged transaction and explain what looks suspicious:

Transaction ID: {txn["transaction_id"]}
Account: {txn["account_id"]}
Amount: ${amt:,.2f}
Merchant: {txn["merchant_name"]}
Location: {txn["location"]}
Time: {txn["timestamp"]}
Transaction Type: {txn["transaction_type"]}
Rules Triggered: {", ".join(rules_list)}
Risk Score: {txn["risk_score"]}/100
Risk Level: {txn["risk_label"]}

What specifically looks suspicious here and what would you investigate next?
"""


def _txn_cache_key(transaction_id: str) -> str:
    return f"fraud:explain:{transaction_id}"


async def explain_transaction(redis: Any, txn: dict) -> tuple[str, bool]:
    """
    Returns (explanation, cached_bool).
    `redis` must be redis.asyncio client with decode_responses=True.
    """
    ttl = int(os.getenv("FRAUD_CACHE_TTL", "86400"))
    key = _txn_cache_key(str(txn["transaction_id"]))
    try:
        cached = await redis.get(key)
    except Exception:
        cached = None
    if cached:
        return str(cached), True

    model = os.getenv("FRAUD_GEMINI_MODEL", "gemini-2.0-flash")
    api_key = os.getenv("GOOGLE_API_KEY")
    user_block = build_prompt(txn)
    full_prompt = f"{SYSTEM_PROMPT.strip()}\n\n{user_block.strip()}"

    try:
        if not api_key:
            return FALLBACK, False

        client = genai.Client(api_key=api_key)

        def _call() -> str:
            response = client.models.generate_content(model=model, contents=full_prompt)
            return (response.text or "").strip()

        text = await asyncio.to_thread(_call)
        if not text:
            return FALLBACK, False
        try:
            await redis.set(key, text, ex=ttl)
        except Exception:
            pass
        return text, False
    except Exception:
        return FALLBACK, False


async def explain_batch(redis: Any, txns: list[dict]) -> list[dict]:
    limit = int(os.getenv("FRAUD_MAX_EXPLAIN_BATCH", "50"))
    out: list[dict] = []
    for raw in txns[:limit]:
        txn = dict(raw)
        expl, _cached = await explain_transaction(redis, txn)
        txn["ai_explanation"] = expl
        out.append(txn)
    return out
