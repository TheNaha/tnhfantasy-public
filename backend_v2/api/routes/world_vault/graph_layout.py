"""
Graph Layout API — save/load node positions for the relationship graph.
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from api.deps import get_session
from core.entities import GraphLayout
from core.exceptions import ValidationError

router = APIRouter()

# Ceiling on one layout write.
#
# The route used to accept any `nodes` array and insert a row per entry in a
# loop, with no body cap and no server-side limit. Measured: 50,000 nodes took
# 16,662 ms in a single request, and while that write was in flight the median
# `GET /api/health` went from 3 ms to 20 ms (p95 218 ms, max 1385 ms) — one
# request stalled the whole event loop, on an unauthenticated route.
#
# A layout holds one node per world-vault entity (characters, locations,
# stories, lorebooks, worlds, scenarios). A deliberately enormous vault is in
# the low thousands, so this is generous rather than tight; the point is that
# the work is bounded, not that the ceiling is exact.
MAX_GRAPH_LAYOUT_NODES = 5000


class GraphNodePosition(BaseModel):
    """One node's saved position.

    Declared rather than taking `payload: dict` so the body is validated. The
    old untyped dict accepted `{"nodes": [{"x": "not-a-number"}]}` and died on
    `float()` with an unmapped 500, and it published an empty object schema,
    which told a client nothing about what the route expected.
    """

    entity_type: str = Field(min_length=1, max_length=64)
    entity_id: str = Field(min_length=1, max_length=64)
    x: float = 0.0
    y: float = 0.0


class GraphLayoutPayload(BaseModel):
    nodes: list[GraphNodePosition] = Field(default_factory=list)


@router.get("/")
def get_graph_layout(
    name: str = "default",
    session: Session = Depends(get_session),
):
    """Return all saved node positions for a given layout name."""
    layouts = session.exec(
        select(GraphLayout).where(GraphLayout.name == name)
    ).all()
    return {
        "name": name,
        "nodes": [
            {
                "entity_type": l.entity_type,
                "entity_id": l.entity_id,
                "x": l.x,
                "y": l.y,
            }
            for l in layouts
        ],
    }


@router.put("/")
def save_graph_layout(
    payload: GraphLayoutPayload,
    name: str = Query(default="default", max_length=64),
    session: Session = Depends(get_session)):
    """Save or update node positions for a layout. Replaces all positions for the given name."""
    nodes = payload.nodes
    if len(nodes) > MAX_GRAPH_LAYOUT_NODES:
        raise ValidationError(
            f"A layout may hold at most {MAX_GRAPH_LAYOUT_NODES} nodes",
            field="nodes",
        )

    # Delete existing layout with this name
    existing = session.exec(
        select(GraphLayout).where(GraphLayout.name == name)
    ).all()
    for item in existing:
        session.delete(item)

    # Insert new positions
    for node in nodes:
        layout = GraphLayout(
            name=name,
            entity_type=node.entity_type,
            entity_id=node.entity_id,
            x=node.x,
            y=node.y,
        )
        session.add(layout)

    session.commit()
    return {"saved": len(nodes), "name": name}


@router.delete("/")
def delete_graph_layout(
    name: str = "default",
    session: Session = Depends(get_session),
):
    """Delete an entire layout."""
    existing = session.exec(
        select(GraphLayout).where(GraphLayout.name == name)
    ).all()
    count = len(existing)
    for item in existing:
        session.delete(item)
    session.commit()
    return {"deleted": count, "name": name}
