# Architecture & Technical Deep Dive

## System Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────┐
│  React Dashboard │────▶│  FastAPI Backend  │────▶│  Redis  │
│  (Vite + TS)     │◀────│  (Python 3.12)   │◀────│  (7)    │
└─────────────────┘     └──────────────────┘     └─────────┘
     Port 5173               Port 8000              6379
                                │
                         ┌──────┴──────┐
                         │ Google      │
                         │ Gemini API  │
                         └─────────────┘
```

Everything runs in Docker containers. The dashboard dev server proxies API requests to the backend.

## Project Structure

```
app/
├── main.py                 # FastAPI app init, Redis connection, route registration
├── fraud/
│   ├── constants.py        # US cities + international cities (shared between enrichment and detection)
│   ├── enrich.py           # One-time script: raw Kaggle CSV → enriched CSV
│   ├── detector.py         # 5 fraud detection rules (pure pandas/numpy, no I/O)
│   ├── explainer.py        # Gemini AI explanations with Redis cache layer
│   └── routes.py           # 4 API endpoints + Pydantic response models
├── models/
│   └── audit.py            # Pydantic models for truth-checking feature
└── services/
    └── truth_check.py      # Dual-LLM hallucination detection (separate feature)

dashboard/src/
├── App.tsx                 # Simple router: Ground Truth vs Fraud Intelligence
└── pages/
    ├── AuditHome.tsx       # Truth-checking dashboard
    └── FraudDashboard.tsx  # Upload, stats, alert queue, AI explain panel

tests/
├── test_detector.py        # Rule engine assertions
└── test_explainer.py       # Gemini + Redis cache latency verification
```

## Data Pipeline

```
Raw Kaggle CSV (284,807 rows, 31 columns)
    │
    ▼  enrich.py (run once)
Enriched CSV (same rows, added: account_id, merchant_name, location, timestamp, transaction_type, amount_usd)
    │
    ▼  POST /fraud/analyze (upload)
detector.py — run_all_rules()
    │
    ├─▶ detect_structuring()
    ├─▶ detect_rapid_movement()
    ├─▶ detect_international_spike()
    ├─▶ detect_round_numbers()
    └─▶ detect_velocity()
    │
    ▼  Merge, deduplicate, score, label
Flagged DataFrame → stored in Redis (fraud:latest_analysis, 1hr TTL)
    │
    ▼  GET /fraud/alerts/{id}/explain
explainer.py — explain_transaction()
    │
    ├─▶ Check Redis cache (fraud:explain:{transaction_id})
    ├─▶ Cache miss → call Gemini → cache result (24hr TTL)
    └─▶ Return explanation + cached flag
```

## API Endpoints

All routes are on the `/fraud` prefix, tagged **Fraud Intelligence** in Swagger.

### `POST /fraud/analyze`

Accepts a CSV file upload. Validates required columns exist (`transaction_id`, `account_id`, `amount_usd`, `merchant_name`, `location`, `timestamp`, `transaction_type`, `Class`). Runs the full detection pipeline and stores results in Redis. Returns summary stats + first 100 alerts.

### `GET /fraud/alerts`

Paginated alert queue. Query params:
- `risk_label` — filter by `CONFIRMED_FRAUD`, `HIGH`, `MEDIUM`, `LOW`
- `rule_name` — filter by `STRUCTURING`, `RAPID_MOVEMENT`, `INTL_SPIKE`, `ROUND_AMOUNT`, `HIGH_VELOCITY`
- `page` / `page_size` — pagination (default 20 per page)

### `GET /fraud/alerts/{transaction_id}/explain`

Returns the AI-generated explanation for a specific alert. Response includes a `cached` boolean — `true` if it came from Redis, `false` if it was a live Gemini call.

### `GET /fraud/stats`

Aggregate data for dashboard charts: total alerts, breakdown by risk label, breakdown by rule, top 10 accounts by alert count.

## Pydantic Response Models

```python
class TransactionAlert(BaseModel):
    transaction_id: str
    account_id: str | None
    amount_usd: float | None
    merchant_name: str | None
    location: str | None
    timestamp: str | None
    transaction_type: str | None
    rules_triggered: list[str]
    risk_score: int | None
    risk_label: str | None
    flagged_at: str | None

class ExplainResponse(BaseModel):
    transaction_id: str
    ai_explanation: str
    cached: bool

class FraudStats(BaseModel):
    total_analyzed: int
    total_alerts: int
    by_risk_label: dict[str, int]
    by_rule: dict[str, int]
    top_accounts: list[dict]
    analysis_timestamp: str
```

## Detection Engine Design

Every rule function in `detector.py` follows the same contract:
- **Input**: pandas DataFrame
- **Output**: DataFrame of flagged rows with `rule_name` and `rule_description` columns added
- **No side effects**: No database calls, no API calls, no file I/O. Pure data in → data out.

`run_all_rules()` calls all 5 functions, concatenates results, deduplicates by `transaction_id`, merges multiple rule hits into a `rules_triggered` list, then calculates `risk_score` and `risk_label`.

## Data Enrichment Design

The enrichment in `enrich.py` is seeded (`random.seed(42)`, `np.random.default_rng(42)`) so it's fully idempotent — run it twice, get byte-for-byte identical output.

Key design decisions that feed the detection rules:
- Fraud rows cluster on 40 accounts (ACC-0001 to ACC-0040) so account-level patterns are detectable
- 70% of fraud rows get suspicious merchants (Wire Transfer, International Payment, ATM Withdrawal)
- 60% of fraud rows get international locations (feeds the INTL_SPIKE rule)
- Structuring-range amounts ($8K–$9.9K) cluster on ACC-0800 (feeds the STRUCTURING rule)

## AI Explainer Design

The explainer uses this system prompt:

> You are a senior fraud analyst at a bank reviewing flagged transactions. Write a brief, plain English explanation of why a transaction looks suspicious, what fraud typology it most likely matches, and what you would investigate next. 3 to 5 sentences. Write like you are briefing a junior analyst.

Safety settings are loosened to `BLOCK_ONLY_HIGH` because fraud narratives mention sensitive topics (money laundering, stolen funds) that can trigger default content filters.

If Gemini fails for any reason, the code returns a fallback message instead of crashing:

```
"Automated explanation temporarily unavailable. Review transaction details and triggered rules manually."
```

## Redis Usage

Three distinct cache patterns:

| Key Pattern | TTL | Purpose |
|---|---|---|
| `fraud:latest_analysis` | 1 hour | Flagged DataFrame as JSON (so `/alerts` can paginate it) |
| `fraud:latest_summary` | 1 hour | Summary stats dict |
| `fraud:explain:{transaction_id}` | 24 hours | Individual AI explanations |

The Redis connection is initialized once in `main.py` lifespan and shared across all routes via `request.app.state.redis`.

## Docker Setup

**Dockerfile** — Multi-stage build. Dependencies install in a builder stage, only installed packages copy to the runtime image. Runs as non-root `apiuser`.

**docker-compose.yml** — Two services: `api` (FastAPI on 8000) and `redis` (Redis 7 Alpine on 6379). The API has `depends_on` with `service_healthy` condition — it won't start until Redis responds to `redis-cli ping`.

## Dashboard Components

`FraudDashboard.tsx` has 4 components, all in one file:

| Component | What It Does |
|---|---|
| `UploadAnalyze` | File picker + analyze button → `POST /fraud/analyze` |
| `StatsOverview` | 3 cards: bar chart (alerts by rule), donut chart (by risk label), top accounts list |
| `AlertQueue` | Paginated table with risk/rule filter dropdowns, clickable rows |
| `ExplainPanel` | Slide-over panel showing transaction details + AI explanation with cached badge |

Charts are pure CSS (bar widths via percentage, donut via `conic-gradient`). No charting library needed.

State management is just React `useState` at the page level — no Redux or external state library.
