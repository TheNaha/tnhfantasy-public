from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from api.deps import get_session

router = APIRouter(tags=["health"])


# Liveness, and deliberately the *only* thing it claims: the process is up and
# serving. It checks nothing — no database, no disk — which is the point of a
# liveness probe, and also why it is not what the compose healthcheck uses.
#
# This was `/api/health`, which returned this same constant and had no callers
# outside a test and some docs: not the compose healthcheck, not the frontend,
# not the providers. Three names for two concepts across the stack — `/live` on
# the provider workers, `/api/ready` here, and a redundant third. It is now
# `/api/live`, which matches what the provider containers already expose.
@router.get("/api/live")
def live():
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
