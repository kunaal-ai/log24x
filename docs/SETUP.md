# Setup & Running log24x

## Prerequisites

- Docker & docker-compose
- Node.js (for the dashboard dev server)
- A Google Gemini API key
- A Groq API key

## 1. Get the Dataset

Download the [Kaggle Credit Card Fraud Detection](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud) dataset. Place `creditcard.csv` inside the `data/` folder at the repo root.

```
data/creditcard.csv   ← 284,807 transactions, ~143MB
```

## 2. Environment Variables

```bash
cp .env.example .env
```

Open `.env` and fill in your keys:

```bash
REDIS_URL=redis://localhost:6379/0
GOOGLE_API_KEY=your-gemini-key
GROQ_API_KEY=your-groq-key

# Fraud module config (defaults are fine)
FRAUD_DATA_PATH=data/creditcard_enriched.csv
FRAUD_CACHE_TTL=86400
FRAUD_MAX_EXPLAIN_BATCH=50
FRAUD_GEMINI_MODEL=gemini-2.5-flash
```

## 3. Start the Backend

```bash
docker-compose build
docker-compose up
```

This spins up the FastAPI server on port 8000 and a Redis instance on 6379. The API waits for Redis to be healthy before accepting requests.

## 4. Enrich the Data (One Time)

```bash
python app/fraud/enrich.py
```

This takes the raw Kaggle CSV and adds account IDs, merchant names, locations, timestamps, and transaction types. Output goes to `data/creditcard_enriched.csv`. You only need to run this once.

## 5. Start the Dashboard

```bash
cd dashboard
npm install
npm run dev
```

Dashboard runs on `http://localhost:5173`. API calls proxy to `localhost:8000` automatically.

## 6. Use It

1. Open `http://localhost:5173`
2. Click **Fraud Intelligence** in the nav bar
3. Upload `data/creditcard_enriched.csv`
4. Wait a few seconds for analysis to complete
5. Browse the alert queue, filter by risk level or rule
6. Click any alert to see the AI-generated investigation briefing

## API-Only Testing

If you just want to test the API without the dashboard:

```bash
# Upload and analyze
curl -X POST http://localhost:8000/fraud/analyze \
  -F "file=@data/creditcard_enriched.csv"

# Get alerts (paginated, filterable)
curl http://localhost:8000/fraud/alerts?risk_label=HIGH&page=1

# Get AI explanation for a specific transaction
curl http://localhost:8000/fraud/alerts/TXN-000001/explain

# Get aggregate stats
curl http://localhost:8000/fraud/stats
```

Swagger docs are at `http://localhost:8000/docs` — all fraud endpoints are under the **Fraud Intelligence** tag.

## Running Tests

```bash
# Rule engine — verifies all 5 rules fire correctly
python tests/test_detector.py

# AI explainer — verifies Gemini responds and Redis caching works
# (needs running Redis + GOOGLE_API_KEY in env)
python tests/test_explainer.py
```
