from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis
import os
import uuid
from app.models.audit import AuditRequest
from app.services.truth_check import TruthCheckService
from app.fraud.routes import router as fraud_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
    app.state.truth_checker = TruthCheckService(app.state.redis)
    yield
    await app.state.redis.close()

app = FastAPI(title="log24x Gateway", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fraud_router)

@app.post("/v1/audit")
async def audit_interaction(payload: AuditRequest):
    audit_id = str(uuid.uuid4())
    result = await app.state.truth_checker.run_audit(payload, audit_id)
    return {"audit_id": audit_id, "results": result}

@app.get("/v1/history")
async def get_history():
    # Fetch latest 20 audit IDs
    ids = await app.state.redis.lrange("audit_history", 0, 19)
    logs = []
    for aid in ids:
        data = await app.state.redis.hgetall(f"audit:{aid}")
        if data:
            logs.append(data)
    return {"logs": logs}



@app.get("/v1/metrics")
async def get_metrics():
    # 1. Get all keys from the history list
    keys = await app.state.redis.lrange("audit_history", 0, -1)
    
    if not keys:
        return {
            "total_audits": 0, 
            "avg_score": 0, 
            "hallucination_rate": 0, 
            "disagreement_rate": 0
        }

    total_audits = len(keys)
    total_score = 0.0
    hallucinations = 0
    disagreements = 0

    for key in keys:
        # 2. Fetch the actual hash data for each audit
        audit_data = await app.state.redis.hgetall(f"audit:{key}")
        if audit_data:
            score = float(audit_data.get("trust_score", 0))
            total_score += score
            
            if audit_data.get("verdict") == "Fail":
                hallucinations += 1
            
            # Logic for judge disagreement
            g_score = float(audit_data.get("gemini_score", 0))
            q_score = float(audit_data.get("groq_score", 0))
            if abs(g_score - q_score) > 0.4:
                disagreements += 1

    return {
        "total_audits": total_audits,
        "avg_score": round(total_score / total_audits, 2),
        "hallucination_rate": round((hallucinations / total_audits) * 100, 1),
        "disagreement_rate": round((disagreements / total_audits) * 100, 1)
    }

@app.get("/health")
async def health():
    await app.state.redis.ping()
    return {"status": "ok"}

