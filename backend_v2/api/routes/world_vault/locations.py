from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select, func

from api.deps import get_session
from services.reference_cleanup import scrub_entity_references
from core.entities import Location
from core.exceptions import NotFoundError

router = APIRouter()


class LocationCreate(BaseModel):
    name: str
    description: str | None = None
    atmosphere: str | None = None
    tags: list[str] | None = None
    image_path: str | None = None


class LocationUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    atmosphere: str | None = None
    tags: list[str] | None = None
    image_path: str | None = None


@router.get("", response_model=list[Location])
def list_locations(session: Session = Depends(get_session)):
    return session.exec(select(Location).order_by(Location.name)).all()


@router.post("", response_model=Location)
def create_location(location_in: LocationCreate, session: Session = Depends(get_session)):
    location = Location(
        name=location_in.name,
        description=location_in.description,
        atmosphere=location_in.atmosphere,
        tags=location_in.tags or [],
        image_path=location_in.image_path,
    )
    location.created_at = datetime.now(timezone.utc)
    location.updated_at = location.created_at
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


@router.get("/search", response_model=list[Location])
def search_locations(q: str, session: Session = Depends(get_session)):
    pattern = f"%{q}%"
    return session.exec(
        select(Location).where(
            func.lower(Location.name).like(func.lower(pattern))
            | func.lower(Location.description).like(func.lower(pattern))
        ).order_by(Location.name)
    ).all()


@router.get("/{location_id}", response_model=Location)
def get_location(location_id: str, session: Session = Depends(get_session)):
    location = session.get(Location, location_id)
    if not location:
        raise NotFoundError("Location", location_id)
    return location


@router.put("/{location_id}", response_model=Location)
def update_location(location_id: str, update_data: LocationUpdate, session: Session = Depends(get_session)):
    location = session.get(Location, location_id)
    if not location:
        raise NotFoundError("Location", location_id)

    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(location, key, value)

    location.updated_at = datetime.now(timezone.utc)
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


@router.patch("/{location_id}", response_model=Location)
def patch_location(location_id: str, update_data: LocationUpdate, session: Session = Depends(get_session)):
    location = session.get(Location, location_id)
    if not location:
        raise NotFoundError("Location", location_id)

    update_dict = update_data.model_dump(exclude_unset=True)
    update_dict = {k: v for k, v in update_dict.items() if v is not None}
    for key, value in update_dict.items():
        setattr(location, key, value)

    location.updated_at = datetime.now(timezone.utc)
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


@router.delete("/{location_id}")
def delete_location(location_id: str, session: Session = Depends(get_session)):
    location = session.get(Location, location_id)
    if not location:
        raise NotFoundError("Location", location_id)
    scrub_entity_references(session, "location", location_id)
    session.delete(location)
    session.commit()
    return {"message": "Location deleted"}
