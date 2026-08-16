from datetime import datetime, timezone

from core.exceptions import NotFoundError


def get_or_404(repo, id, entity_type):
    entity = repo.get(id)
    if not entity:
        raise NotFoundError(entity_type, id)
    return entity


def persist(session, entity):
    session.add(entity)
    session.commit()
    session.refresh(entity)
    return entity


def apply_patch(entity, update_dict, timestamp_fields=("updated_at",)):
    for key, value in update_dict.items():
        setattr(entity, key, value)
    for field in timestamp_fields:
        if hasattr(entity, field):
            setattr(entity, field, datetime.now(timezone.utc))
    return entity


def delete_entity(session, repo, id, entity_type):
    entity = get_or_404(repo, id, entity_type)
    session.delete(entity)
    session.commit()
    return entity
