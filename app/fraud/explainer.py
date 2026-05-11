"""
Gemini-backed fraud explanations with Redis caching (async).
Uses the same google-genai client pattern as the rest of the app.

Phase 7: explain_transaction now returns (explanation, confidence) tuple.
The confidence label is parsed from Gemini's response and stored in Redis
as JSON so validator.py can reuse it without an extra API call.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a senior fraud analyst at a bank reviewing flagged transactions.
Follow these rules exactly:
1. Only reference information explicitly provided in the transaction data below.
   Do not infer, assume, or add any details that are not in the input.
2. Write 3 to 5 sentences maximum.
3. Write like you are briefing a junior analyst, not writing a formal report.
4. Do not use bullet points.
5. Do not start with the words 'This transaction'.
6. Be specific about which pattern looks suspicious and why.
7. If the pattern is ambiguous or could have a legitimate explanation, say so.
8. End your response with exactly one of these confidence labels on its own line:
CONFIDENCE: HIGH
CONFIDENCE: MEDIUM
CONFIDENCE: LOW
Use HIGH if multiple clear fraud signals align.
Use MEDIUM if the pattern is suspicious but could have a legitimate explanation.
Use LOW if you are uncertain or the signals are weak.
"""

FALLBACK_EXPLANATION = (
    "Automated explanation temporarily unavailable. Review transaction details and triggered rules manually."
)
FALLBACK_CONFIDENCE = "MEDIUM"

# Match TruthCheckService default; override with FRAUD_GEMINI_MODEL in .env.
_DEFAULT_MODEL = "gemini-2.5-flash"


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
Remember to end with CONFIDENCE: HIGH, CONFIDENCE: MEDIUM, or CONFIDENCE: LOW.
"""


def _txn_cache_key(transaction_id: str) -> str:
    return f"fraud:explain:{transaction_id}"


def _fraud_explain_config() -> types.GenerateContentConfig:
    """Slightly looser safety thresholds — fraud narratives are often classified as sensitive."""
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT.strip(),
        safety_settings=[
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
        ],
    )


def _parse_confidence(text: str) -> tuple[str, str]:
    """
    Extracts the CONFIDENCE label from the end of Gemini's response.
    Returns (clean_explanation, confidence_level).
    Defaults to MEDIUM if the label is missing or unparsable.
    """
    lines = text.strip().split("\n")
    confidence = FALLBACK_CONFIDENCE
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("CONFIDENCE:"):
            extracted = stripped.replace("CONFIDENCE:", "").strip()
            if extracted in ("HIGH", "MEDIUM", "LOW"):
                confidence = extracted
            break
    # Remove the CONFIDENCE line from the explanation
    clean_lines = [l for l in lines if not l.strip().startswith("CONFIDENCE:")]
    clean_explanation = "\n".join(clean_lines).strip()
    return clean_explanation, confidence


def _log_empty_or_blocked_response(response: types.GenerateContentResponse, model: str) -> None:
    parts: list[str] = [f"model={model}"]
    try:
        pf = getattr(response, "prompt_feedback", None)
        if pf is not None:
            parts.append(f"prompt_feedback={pf}")
        cands = getattr(response, "candidates", None) or []
        if not cands:
            parts.append("candidates=[]")
        else:
            c0 = cands[0]
            parts.append(f"finish_reason={getattr(c0, 'finish_reason', None)}")
            sr = getattr(c0, "safety_ratings", None)
            if sr is not None:
                parts.append(f"safety_ratings={sr}")
    except Exception as exc:
        parts.append(f"debug_parse_error={exc}")
    logger.warning("Fraud explainer: no usable text from Gemini (%s)", "; ".join(parts))


async def explain_transaction(redis: Any, txn: dict) -> tuple[str, bool, str]:
    """
    Returns (explanation, cached_bool, confidence).
    `redis` must be redis.asyncio client with decode_responses=True.

    Phase 7 change: now returns a 3-tuple.
    The cache stores JSON {explanation, confidence} so confidence survives restarts.
    Old plain-string cache entries are handled gracefully (confidence defaults to MEDIUM).
    """
    ttl = int(os.getenv("FRAUD_CACHE_TTL", "86400"))
    key = _txn_cache_key(str(txn["transaction_id"]))
    try:
        cached_raw = await redis.get(key)
    except Exception:
        cached_raw = None

    if cached_raw:
        # Try to parse as JSON (Phase 7 format) first
        try:
            cached_data = json.loads(cached_raw)
            if isinstance(cached_data, dict) and "explanation" in cached_data:
                return str(cached_data["explanation"]), True, str(cached_data.get("confidence", FALLBACK_CONFIDENCE))
        except (json.JSONDecodeError, TypeError):
            pass
        # Old format: plain string — return with default confidence
        return str(cached_raw), True, FALLBACK_CONFIDENCE

    model = (os.getenv("FRAUD_GEMINI_MODEL") or _DEFAULT_MODEL).strip()
    api_key = (os.getenv("GOOGLE_API_KEY") or "").strip()
    user_message = build_prompt(txn).strip()
    config = _fraud_explain_config()

    try:
        if not api_key:
            logger.warning("Fraud explainer skipped: GOOGLE_API_KEY is not set")
            return FALLBACK_EXPLANATION, False, FALLBACK_CONFIDENCE

        client = genai.Client(api_key=api_key)

        def _call() -> str:
            response = client.models.generate_content(
                model=model,
                contents=user_message,
                config=config,
            )
            text = (response.text or "").strip()
            if text:
                return text
            _log_empty_or_blocked_response(response, model)
            return ""

        raw_text = await asyncio.to_thread(_call)
        if not raw_text:
            return FALLBACK_EXPLANATION, False, FALLBACK_CONFIDENCE

        explanation, confidence = _parse_confidence(raw_text)

        try:
            cache_value = json.dumps({"explanation": explanation, "confidence": confidence})
            await redis.set(key, cache_value, ex=ttl)
        except Exception:
            pass

        return explanation, False, confidence

    except Exception as e:
        logger.warning("Fraud explainer Gemini call failed (model=%s): %s", model, e, exc_info=True)
        return FALLBACK_EXPLANATION, False, FALLBACK_CONFIDENCE


async def explain_batch(redis: Any, txns: list[dict]) -> list[dict]:
    limit = int(os.getenv("FRAUD_MAX_EXPLAIN_BATCH", "50"))
    out: list[dict] = []
    for raw in txns[:limit]:
        txn = dict(raw)
        expl, _cached, confidence = await explain_transaction(redis, txn)
        txn["ai_explanation"] = expl
        txn["confidence"] = confidence
        out.append(txn)
    return out
