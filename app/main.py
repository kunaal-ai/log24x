from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis
import os
import uuid
from app.models.audit import AuditRequest
from app.services.truth_check import TruthCheckService

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

@app.get("/health")
async def health():
    await app.state.redis.ping()
    return {"status": "ok"}