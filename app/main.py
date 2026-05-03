from contextlib import asynccontextmanager
from fastapi import FastAPI
import redis.asyncio as redis
import os

# Lifespan handles startup and shutdown logic
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize Redis connection
    app.state.redis = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
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

@app.get("/health")
async def health_check():
    """Standard health check for K8s Liveness Probes"""
    try:
        # Check if Redis is responsive
        await app.state.redis.ping()
        return {"status": "healthy", "infrastructure": {"redis": "online"}}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

@app.post("/v1/audit")
async def audit_interaction(payload: dict):
    """
    Primary endpoint for AI interaction auditing.
    """
    return {"message": "Audit service is online. Pipeline pending implementation."}