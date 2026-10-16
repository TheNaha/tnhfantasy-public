"""
Graph Edges API — explicit, named relationships between any two World Vault
entities. Complements the derived FK-based edges in `world_hub.get_relationships`;
stored edges let users express relationships the static schema cannot
(e.g. "character A is enemy of character B").
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select, func

from api.deps import get_session
from core.entities import WorldEdge
from core.exceptions import NotFoundError, ValidationError

router = APIRouter()

# Ceiling on one edges list page; matches the pattern used by
# `get_relationships` (le=1000) so a client cannot page the whole vault.
MAX_EDGE_PAGE = 1000


class WorldEdgeCreate(BaseModel):
    """Request body for creating a stored graph edge."""

    source_entity_type: str = Field(min_length=1, max_length=64)
    source_entity_id: str = Field(min_length=1, max_length=64)
    target_entity_type: str = Field(min_length=1, max_length=64)
    target_entity_id: str = Field(min_length=1, max_length=64)
    relation_type: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=255)


class WorldEdgeRead(BaseModel):
    """Serialized edge returned to the client."""

    id: str
    source_entity_type: str
    source_entity_id: str
    target_entity_type: str
    target_entity_id: str
    relation_type: str
    label: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


def _edge_to_read(edge: WorldEdge) -> WorldEdgeRead:
    return WorldEdgeRead(
        id=edge.id,
        source_entity_type=edge.source_entity_type,
        source_entity_id=edge.source_entity_id,
        target_entity_type=edge.target_entity_type,
        target_entity_id=edge.target_entity_id,
        relation_type=edge.relation_type,
        label=edge.label,
        created_at=edge.created_at.isoformat() if edge.created_at else None,
        updated_at=edge.updated_at.isoformat() if edge.updated_at else None,
    )


@router.get("")
def list_graph_edges(
    limit: int = Query(default=50, ge=1, le=MAX_EDGE_PAGE),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    """List stored graph edges, newest first."""
    total = session.exec(select(func.count()).select_from(WorldEdge)).one()
    rows = session.exec(
        select(WorldEdge)
        .order_by(WorldEdge.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "edges": [_edge_to_read(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("")
def create_graph_edge(
    payload: WorldEdgeCreate,
    session: Session = Depends(get_session),
):
    """Create a stored graph edge. Rejects duplicates and self-loops."""
    if (
        payload.source_entity_type == payload.target_entity_type
        and payload.source_entity_id == payload.target_entity_id
    ):
        raise ValidationError(
            "An edge cannot connect an entity to itself",
            field="target_entity_id",
        )

    existing = session.exec(
        select(WorldEdge).where(
            WorldEdge.source_entity_type == payload.source_entity_type,
            WorldEdge.source_entity_id == payload.source_entity_id,
            WorldEdge.target_entity_type == payload.target_entity_type,
            WorldEdge.target_entity_id == payload.target_entity_id,
            WorldEdge.relation_type == payload.relation_type,
        )
    ).first()
    if existing is not None:
        raise ValidationError(
            "An edge with these endpoints and relation type already exists",
            field="relation_type",
        )

    edge = WorldEdge(
        source_entity_type=payload.source_entity_type,
        source_entity_id=payload.source_entity_id,
        target_entity_type=payload.target_entity_type,
        target_entity_id=payload.target_entity_id,
        relation_type=payload.relation_type,
        label=payload.label,
    )
    session.add(edge)
    session.commit()
    session.refresh(edge)
    return _edge_to_read(edge)


@router.delete("/{edge_id}")
def delete_graph_edge(
    edge_id: str,
    session: Session = Depends(get_session),
):
    """Delete a stored graph edge by id."""
    edge = session.get(WorldEdge, edge_id)
    if edge is None:
        raise NotFoundError("WorldEdge", edge_id)
    session.delete(edge)
    session.commit()
    return {"deleted": edge_id}
