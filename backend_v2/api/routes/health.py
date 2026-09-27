from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from api.deps import get_session

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "2.0.0"}


@router.get("/api/ready")
# Plain `def` on purpose: the readiness probe is polled by the orchestrator on a
# tight interval, and `SELECT 1` on the event loop made every health check
# contend with real request traffic.
def ready(session=Depends(get_session)):
    try:
        session.exec(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ready", "version": "2.0.0"}
