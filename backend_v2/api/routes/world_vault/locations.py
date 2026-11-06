import asyncio
from datetime import datetime, timezone
import os

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, model_validator
from sqlmodel import Session, select, func

from api.deps import get_session, get_location_repo, get_session_sync
from infrastructure.repositories.location_repo import LocationRepository
from services.reference_cleanup import scrub_entity_references
from services.world_ownership import apply_world_id, require_world
from core.entities import Location
from core.exceptions import NotFoundError, ValidationError
from core.sql_search import LIKE_ESCAPE_CHAR, like_contains
from core.upload_validation import (
    MAX_AVATAR_SIZE_MB,
    inspect_image,
    read_upload_bounded,
    require_declared_size,
)
import config as app_config

router = APIRouter()

MAX_LOCATION_IMAGE_BYTES = MAX_AVATAR_SIZE_MB * 1024 * 1024
# Ceiling on the location search term, in characters.
MAX_SEARCH_LENGTH = 200


class LocationCreate(BaseModel):
    name: str
    description: str | None = None
    atmosphere: str | None = None
    tags: list[str] | None = None
    image_path: str | None = None
    map_x: float | None = None
    map_y: float | None = None
    # Which World this entity belongs to. Ownership of record lives on the
    # member, not in an array on the `worlds` row — see `services/
    # world_ownership.py`. Absent means "leave alone"; an explicit null detaches.
    world_id: str | None = None


class LocationUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    atmosphere: str | None = None
    tags: list[str] | None = None
    image_path: str | None = None
    map_x: float | None = None
    map_y: float | None = None
    # Which World this entity belongs to. Ownership of record lives on the
    # member, not in an array on the `worlds` row — see `services/
    # world_ownership.py`. Absent means "leave alone"; an explicit null detaches.
    world_id: str | None = None

    @model_validator(mode="after")
    def _reject_null_name(self):
        # name is a NOT NULL column: an explicit {"name": null} is a client bug
        # and must surface as a 422 instead of an IntegrityError (500).
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


@router.get("", response_model=list[Location])
def list_locations(session: Session = Depends(get_session), location_repo: LocationRepository = Depends(get_location_repo)):
    return location_repo.list()


@router.post("", response_model=Location)
def create_location(location_in: LocationCreate, session: Session = Depends(get_session), location_repo: LocationRepository = Depends(get_location_repo)):
    if location_in.image_path:
        raise ValidationError("Use the image upload endpoint to set image_path")
    require_world(session, location_in.world_id)
    location = Location(
        name=location_in.name,
        description=location_in.description,
        atmosphere=location_in.atmosphere,
        tags=location_in.tags or [],
        image_path=location_in.image_path,
        map_x=location_in.map_x,
        map_y=location_in.map_y,
        world_id=location_in.world_id,
    )
    location.created_at = datetime.now(timezone.utc)
    location.updated_at = location.created_at
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


@router.get("/search", response_model=list[Location])
def search_locations(
    q: str = Query(..., max_length=MAX_SEARCH_LENGTH),
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_session),
    location_repo: LocationRepository = Depends(get_location_repo),
):
    pattern = func.lower(like_contains(q))
    # `.limit(limit)` is the point of the parameter that was added above it.
    # Without it a bare `.all()` returns every matching location — on a large
    # world vault that is the whole table, JSON-serialised into the response,
    # for an autocomplete.
    return session.exec(
        select(Location).where(
            func.lower(Location.name).like(pattern, escape=LIKE_ESCAPE_CHAR)
            | func.lower(Location.description).like(pattern, escape=LIKE_ESCAPE_CHAR)
        ).order_by(Location.name).limit(limit)
    ).all()


@router.get("/{location_id}", response_model=Location)
def get_location(location_id: str, session: Session = Depends(get_session), location_repo: LocationRepository = Depends(get_location_repo)):
    location = location_repo.get(location_id)
    if not location:
        raise NotFoundError("Location", location_id)
    return location


@router.put("/{location_id}", response_model=Location)
def update_location(location_id: str, update_data: LocationUpdate, session: Session = Depends(get_session), location_repo: LocationRepository = Depends(get_location_repo)):
    return patch_location(location_id, update_data, session, location_repo)


@router.patch("/{location_id}", response_model=Location)
def patch_location(location_id: str, update_data: LocationUpdate, session: Session = Depends(get_session), location_repo: LocationRepository = Depends(get_location_repo)):
    location = location_repo.get(location_id)
    if not location:
        raise NotFoundError("Location", location_id)

    update_dict = update_data.model_dump(exclude_unset=True)
    if update_dict.get("image_path"):
        raise ValidationError("Use the image upload endpoint to set image_path")
    apply_world_id(session, location, update_dict)
    update_dict.pop("world_id", None)
    for key, value in update_dict.items():
        setattr(location, key, value)

    location.updated_at = datetime.now(timezone.utc)
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


@router.delete("/{location_id}")
def delete_location(location_id: str, session: Session = Depends(get_session), location_repo: LocationRepository = Depends(get_location_repo)):
    location = location_repo.get(location_id)
    if not location:
        raise NotFoundError("Location", location_id)
    scrub_entity_references(session, "location", location_id)
    session.delete(location)
    session.commit()
    return {"message": "Location deleted"}


@router.post("/{location_id}/image")
async def upload_location_image(location_id: str, file: UploadFile = File(...)):
    # threads with their own thread-local session.
    await asyncio.to_thread(_require_location, location_id)

    # Bounded + content-verified: the client-supplied extension is replaced by
    # the detected format so the stored path always matches the bytes.
    require_declared_size(file, MAX_LOCATION_IMAGE_BYTES)
    content = await read_upload_bounded(file, MAX_LOCATION_IMAGE_BYTES)
    _, _, ext = inspect_image(content, field="file", label="Location image")

    base_dir = app_config.settings.location_image_dir
    image_path = f"{base_dir}/{location_id}/image{ext}"

    def _write_image(base_dir: str, location_id: str, image_path: str, content: bytes) -> str:
        # Blocking filesystem work off the event loop.
        os.makedirs(f"{base_dir}/{location_id}", exist_ok=True)
        with open(image_path, "wb") as buffer:
            buffer.write(content)
        return image_path

    await asyncio.to_thread(_write_image, base_dir, location_id, image_path, content)

    await asyncio.to_thread(_save_location_image, location_id, image_path)
    return {"message": "Image uploaded", "image_path": image_path}


def _require_location(location_id: str) -> None:
    """404 before the upload is consumed, off the event loop."""
    with get_session_sync() as db_session:
        repo = LocationRepository(db_session)
        if not repo.get(location_id):
            raise NotFoundError("Location", location_id)


def _save_location_image(
    location_id: str,
    image_path: str,
) -> None:
    """Persist the stored image path on the location."""
    with get_session_sync() as db_session:
        repo = LocationRepository(db_session)
        location = repo.get(location_id)
        if location is None:
            return
        location.image_path = image_path
        location.updated_at = datetime.now(timezone.utc)
        db_session.add(location)
        db_session.commit()
