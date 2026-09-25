from datetime import datetime, timezone
import os

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, model_validator
from sqlmodel import Session, select, func

from api.deps import get_session, get_location_repo
from infrastructure.repositories.location_repo import LocationRepository
from services.reference_cleanup import scrub_entity_references
from core.entities import Location
from core.exceptions import NotFoundError, ValidationError
import config as app_config

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
def search_locations(q: str, session: Session = Depends(get_session), location_repo: LocationRepository = Depends(get_location_repo)):
    pattern = f"%{q}%"
    return session.exec(
        select(Location).where(
            func.lower(Location.name).like(func.lower(pattern))
            | func.lower(Location.description).like(func.lower(pattern))
        ).order_by(Location.name)
    ).all()


@router.get("/{location_id}", response_model=Location)
def get_location(location_id: str, session: Session = Depends(get_session), location_repo: LocationRepository = Depends(get_location_repo)):
    location = location_repo.get(location_id)
    if not location:
        raise NotFoundError("Location", location_id)
    return location


@router.put("/{location_id}", response_model=Location)
def update_location(location_id: str, update_data: LocationUpdate, session: Session = Depends(get_session), location_repo: LocationRepository = Depends(get_location_repo)):
    location = location_repo.get(location_id)
    if not location:
        raise NotFoundError("Location", location_id)

    update_dict = update_data.model_dump(exclude_unset=True)
    if update_dict.get("image_path"):
        raise ValidationError("Use the image upload endpoint to set image_path")
    for key, value in update_dict.items():
        setattr(location, key, value)

    location.updated_at = datetime.now(timezone.utc)
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


@router.patch("/{location_id}", response_model=Location)
def patch_location(location_id: str, update_data: LocationUpdate, session: Session = Depends(get_session), location_repo: LocationRepository = Depends(get_location_repo)):
    location = location_repo.get(location_id)
    if not location:
        raise NotFoundError("Location", location_id)

    update_dict = update_data.model_dump(exclude_unset=True)
    if update_dict.get("image_path"):
        raise ValidationError("Use the image upload endpoint to set image_path")
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
async def upload_location_image(location_id: str, file: UploadFile = File(...), session: Session = Depends(get_session), location_repo: LocationRepository = Depends(get_location_repo)):
    location = location_repo.get(location_id)
    if not location:
        raise NotFoundError("Location", location_id)

    base_dir = app_config.settings.location_image_dir
    os.makedirs(f"{base_dir}/{location_id}", exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1] or ".png"
    image_path = f"{base_dir}/{location_id}/image{ext}"

    with open(image_path, "wb") as buffer:
        from shutil import copyfileobj
        copyfileobj(file.file, buffer)

    location.image_path = image_path
    location.updated_at = datetime.now(timezone.utc)
    session.add(location)
    session.commit()
    session.refresh(location)
    return {"message": "Image uploaded", "image_path": image_path}
