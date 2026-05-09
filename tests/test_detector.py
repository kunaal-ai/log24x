"""Phase 2 verification for fraud detection rules."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.fraud.detector import RULE_ORDER, run_all_rules  # noqa: E402

ENRICHED = ROOT / "data" / "creditcard_enriched.csv"


def main() -> None:
    if not ENRICHED.is_file():
        raise SystemExit(f"Missing {ENRICHED} — run `python app/fraud/enrich.py` first.")

    df = pd.read_csv(ENRICHED)
    flagged, summary = run_all_rules(df)

    assert summary["total_flagged"] > 0, "expected some flagged transactions"
    for name in RULE_ORDER:
        assert summary["by_rule"].get(name, 0) > 0, f"expected rule {name} to fire at least once"

    assert flagged["risk_score"].isin([30, 60, 90, 100]).all()
    assert flagged["risk_label"].isin(["LOW", "MEDIUM", "HIGH", "CONFIRMED_FRAUD"]).all()
    assert flagged["transaction_id"].is_unique

    print("test_detector: all assertions passed")
    print(summary)


if __name__ == "__main__":
    main()
