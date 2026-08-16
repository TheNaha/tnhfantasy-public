from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_session, get_campaign_repo, get_character_repo, get_story_repo, get_chat_repo, get_location_repo
from infrastructure.repositories.campaign_repo import CampaignRepository
from infrastructure.repositories.character_repo import CharacterRepository
from infrastructure.repositories.story_repo import StoryRepository
from infrastructure.repositories.chat_repo import ChatRepository
from infrastructure.repositories.location_repo import LocationRepository
from core.entities import Campaign, Location, Character, Story, Chat
from core.exceptions import NotFoundError
from sqlmodel import Session, select

router = APIRouter()


class CampaignCreate(BaseModel):
    name: str
    description: str | None = None
    character_ids: list[str] | None = None
    story_ids: list[str] | None = None
    chat_ids: list[str] | None = None
    location_ids: list[str] | None = None


class CampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    character_ids: list[str] | None = None
    story_ids: list[str] | None = None
    chat_ids: list[str] | None = None
    location_ids: list[str] | None = None


@router.get("", response_model=list[Campaign])
def list_campaigns(session: Session = Depends(get_session), campaign_repo: CampaignRepository = Depends(get_campaign_repo)):
    return campaign_repo.list()


@router.post("", response_model=Campaign)
def create_campaign(campaign_in: CampaignCreate, session: Session = Depends(get_session), campaign_repo: CampaignRepository = Depends(get_campaign_repo)):
    campaign = Campaign(
        name=campaign_in.name,
        description=campaign_in.description,
        character_ids=campaign_in.character_ids or [],
        story_ids=campaign_in.story_ids or [],
        chat_ids=campaign_in.chat_ids or [],
        location_ids=campaign_in.location_ids or [],
    )
    campaign.created_at = datetime.now(timezone.utc)
    campaign.updated_at = campaign.created_at
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


@router.get("/{campaign_id}", response_model=Campaign)
def get_campaign(campaign_id: str, session: Session = Depends(get_session), campaign_repo: CampaignRepository = Depends(get_campaign_repo)):
    campaign = campaign_repo.get(campaign_id)
    if not campaign:
        raise NotFoundError("Campaign", campaign_id)
    return campaign


@router.put("/{campaign_id}", response_model=Campaign)
def update_campaign(campaign_id: str, update_data: CampaignUpdate, session: Session = Depends(get_session), campaign_repo: CampaignRepository = Depends(get_campaign_repo)):
    campaign = campaign_repo.get(campaign_id)
    if not campaign:
        raise NotFoundError("Campaign", campaign_id)

    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(campaign, key, value)

    campaign.updated_at = datetime.now(timezone.utc)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: str, session: Session = Depends(get_session), campaign_repo: CampaignRepository = Depends(get_campaign_repo)):
    campaign = campaign_repo.get(campaign_id)
    if not campaign:
        raise NotFoundError("Campaign", campaign_id)
    session.delete(campaign)
    session.commit()
    return {"message": "Campaign deleted"}


@router.get("/{campaign_id}/dashboard")
def get_campaign_dashboard(campaign_id: str, session: Session = Depends(get_session), campaign_repo: CampaignRepository = Depends(get_campaign_repo)):
    campaign = campaign_repo.get(campaign_id)
    if not campaign:
        raise NotFoundError("Campaign", campaign_id)

    characters = session.exec(select(Character).where(Character.id.in_(campaign.character_ids or []))).all()
    stories = session.exec(select(Story).where(Story.id.in_(campaign.story_ids or []))).all()
    chats = session.exec(select(Chat).where(Chat.id.in_(campaign.chat_ids or []))).all()
    locations = session.exec(select(Location).where(Location.id.in_(campaign.location_ids or []))).all()

    return {
        "campaign": campaign,
        "characters": [{"id": c.id, "name": c.name} for c in characters],
        "stories": [{"id": s.id, "title": s.title} for s in stories],
        "chats": [{"id": c.id, "name": c.name} for c in chats],
        "locations": [{"id": l.id, "name": l.name} for l in locations],
    }
