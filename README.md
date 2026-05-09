# log24x: Fraud Transaction Intelligence Suite

log24x is a fraud detection and analysis workbench that pairs deterministic, rule-based transaction monitoring with AI-generated explanations. The backend is FastAPI and pandas; the frontend is React with TypeScript; and analyst-style narratives are produced with Google Gemini. The experience is intentionally close to real fraud operations: triage an alert queue, understand risk scoring, and read plain English investigation briefings per transaction.

## The Problem it Solves

Fraud analysts routinely work through hundreds of alerts per shift, yet many monitoring tools stop at a score or a rule code with little narrative context. That friction slows prioritization and makes it harder to explain decisions to partners and compliance stakeholders. This project adds an explanation layer on top of classic rules: each flagged transaction can be summarized in clear language so analysts can decide what to escalate first. The goal is faster, more confident review without replacing human judgment.

## Fraud Detection Rules

| Rule Name | Fraud Typology | Description |
| --- | --- | --- |
| STRUCTURING | Structuring / threshold avoidance | Flags accounts with multiple $8k–$9.9k transactions inside a rolling 24-hour window. |
| RAPID_MOVEMENT | Money mule / funneling | Flags accounts where debits drain more than 85% of recent credits within 48 hours when credits exceed $5k. |
| INTL_SPIKE | Geographic anomaly | Flags accounts that suddenly show international spend versus a mostly domestic history. |
| ROUND_AMOUNT | Wire / manual fraud pattern | Flags large transactions on exact thousand-dollar amounts (e.g., $10,000). |
| HIGH_VELOCITY | Burst / bot-like activity | Flags accounts with more than eight transactions in any rolling one-hour window. |

## How the AI Explanation Works

When you open an alert, the API sends Gemini the full transaction context—amount, merchant, location, timestamp, transaction type, every rule that fired, and the computed risk score/label—and asks for a short, senior-analyst-style briefing. Successful responses are cached in Redis under `fraud:explain:{transaction_id}` with TTL from `FRAUD_CACHE_TTL`, so repeat views avoid redundant model calls.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend API | Python 3.12, FastAPI, Uvicorn |
| Data processing | pandas, NumPy |
| AI | Google Gemini (`google-genai`), Groq (existing audit path) |
| Caching | Redis 7 (via `redis-py` asyncio) |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS |
| Containerization | Docker, docker-compose |

## How to Run

1. Clone this repository.
2. Download the [Kaggle Credit Card Fraud Detection](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud) dataset and place `creditcard.csv` under `data/creditcard.csv` at the repo root.
3. Copy `.env.example` to `.env` and fill in `GOOGLE_API_KEY`, `GROQ_API_KEY`, and `REDIS_URL` (the defaults work with docker-compose Redis).
4. Build and start services: `docker-compose build` then `docker-compose up`.
5. Generate enriched data (one-time): `python app/fraud/enrich.py` (from the repo root; requires the Kaggle CSV).
6. Start the dashboard dev server from `dashboard/` with `npm install` and `npm run dev` (proxies `/v1` and `/fraud` to `http://localhost:8000`).
7. Open `http://localhost:5173`, choose **Fraud Intelligence**, and upload `data/creditcard_enriched.csv` to run the full detection + review flow.

For API-only testing, `POST /fraud/analyze` accepts the enriched CSV; use `GET /docs` to explore the **Fraud Intelligence** tag.

## Dataset

Raw transaction features come from the public [Credit Card Fraud Detection](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud) dataset (ULB). Fields `V1`–`V28` are PCA-transformed and anonymized. Merchant names, locations, account identifiers, and transaction metadata in the enriched file are **synthetic** but the original `Class` fraud labels are preserved for evaluation and demo scenarios.

[Screenshot: fraud dashboard showing alert queue and AI explanation panel] — replace this line with an actual screenshot after your first successful run.

## Verification commands

- `python tests/test_detector.py` — rule engine smoke test (requires `data/creditcard_enriched.csv`).
- `python tests/test_explainer.py` — Gemini + Redis cache latency check (requires Redis, `GOOGLE_API_KEY`, and enriched data).
