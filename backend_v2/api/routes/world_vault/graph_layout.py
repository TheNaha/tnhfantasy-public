"""
Graph Layout API — save/load node positions for the relationship graph.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.deps import get_session
from core.entities import GraphLayout

router = APIRouter()


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
    payload: dict,
    name: str = "default",
    session: Session = Depends(get_session)):
    """Save or update node positions for a layout. Replaces all positions for the given name."""
    nodes = payload.get("nodes", [])
    if not isinstance(nodes, list):
        raise HTTPException(status_code=400, detail="nodes must be a list")

    # Delete existing layout with this name
    existing = session.exec(
        select(GraphLayout).where(GraphLayout.name == name)
    ).all()
    for item in existing:
        session.delete(item)

    # Insert new positions
    for node in nodes:
        entity_type = node.get("entity_type")
        entity_id = node.get("entity_id")
        x = node.get("x", 0.0)
        y = node.get("y", 0.0)
        if not entity_type or not entity_id:
            continue
        layout = GraphLayout(
            name=name,
            entity_type=entity_type,
            entity_id=entity_id,
            x=float(x),
            y=float(y),
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
