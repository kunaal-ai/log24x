import nest_asyncio
# Must be called BEFORE any other imports to patch the loop correctly
nest_asyncio.apply()

import os
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
from contextlib import asynccontextmanager
import json

from fastapi import FastAPI, HTTPException, Request, Header
import redis.asyncio as redis

from app.models.audit import AuditRequest, AuditResponse
from app.services.truth_check import TruthCheckService

# Lifespan handles startup and shutdown logic
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize Redis connection
    app.state.redis = redis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"), 
        decode_responses=True  # ensures we get strings back from Redis instead of bytes

    )
    app.state.truth_service = TruthCheckService(redis_client=app.state.redis)
    print("log24x Gateway Started: Redis Connected")
    yield
    # Shutdown: Clean up resources
    await app.state.redis.close()
    print("log24x Gateway Shutting Down")

app = FastAPI(
    title="log24x Enterprise AI Gateway",
    version="1.0.0",
    lifespan=lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For production, you'd specify http://localhost:5173
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.get("/health")
async def health_check():
    """Standard health check for K8s Liveness Probes"""
    try:
        await app.state.redis.ping()
        return {"status": "healthy", "infrastructure": {"redis": "online"}}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

@app.post("/v1/audit", response_model=AuditResponse)
async def audit_interaction(
    payload: AuditRequest,
    request: Request,
    x_openai_key: Optional[str] = Header(None),
):
    """
    The Hallucination Gate with BYOK (Bring Your Own Key) support.
    Verifies output against context and logs the result to Redis.
    """
    try:
        verdict = await request.app.state.truth_service.run_audit(payload, user_key=x_openai_key)
        return verdict
    except Exception as e:
        # Catching the specific error for better debugging
        raise HTTPException(status_code=500, detail=f"Audit failed: {str(e)}")

@app.get("/v1/history")
async def get_audit_history(request: Request, limit: int = 10):
    """
    Retrieves the last N audits from Redis.
    This serves as the backend for the Dashboard.
    """
    try:
        # Find all keys starting with 'audit:'
        keys = await request.app.state.redis.keys("audit:*")
        
        # Sort keys to get newest first (Redis keys aren't naturally sorted)
        # We take the last 'limit' number of entries
        results = []
        for key in keys[-limit:]:
            data = await request.app.state.redis.get(key)
            results.append(json.loads(data))
            
        return {"total_logs": len(keys), "logs": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {str(e)}")