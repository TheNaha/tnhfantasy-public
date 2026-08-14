from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import get_session
from core.entities import Story, StoryBeatRole, StoryChapter, Lorebook, LorebookEntry
from core.exceptions import NotFoundError
from core.workflow_builder import build_image_workflow
from services.job_queue import queue_manager

router = APIRouter()


from services.llm_config import get_default_llm_model as _get_default_llm_model
from services.model_availability_service import ModelAvailabilityService


class StoryContinueRequest(BaseModel):
    prompt: str = ""


class StoryBeatRequest(BaseModel):
    content: str
    role: str = "user"


class StoryIllustrateRequest(BaseModel):
    image_prompt: str = ""


class StoryBranchRequest(BaseModel):
    from_beat_id: str
    prompt: str = ""


class CreateStoryRequest(BaseModel):
    title: str
    description: str | None = None
    genre: str | None = None
    character_ids: list[str] = []
    lorebook_ids: list[str] = []
    scenario_id: str | None = None
    llm_model: str | None = None
    memory: str | None = None
    max_agentic_depth: int | None = None


class UpdateStoryRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    genre: str | None = None
    character_ids: list[str] | None = None
    lorebook_ids: list[str] | None = None
    scenario_id: str | None = None
    llm_model: str | None = None
    memory: str | None = None
    is_archived: bool | None = None
    max_agentic_depth: int | None = None


def _ensure_beat_ids(session: Session, chapter: StoryChapter) -> None:
    """Assign stable ids to beats that predate branching support.

    Beats are stored as JSON dicts; branching needs a per-beat id to fork
    from. Legacy beats have none, so backfill them lazily (idempotent).

    NOTE: MutableList does NOT track in-place mutation of its dict members,
    so the list must be rebuilt (assignment) for the change to persist.
    """
    if not chapter.beats:
        return
    rebuilt = []
    changed = False
    for beat in chapter.beats:
        if not isinstance(beat, dict) or beat.get("id"):
            rebuilt.append(beat)
            continue
        rebuilt.append({**beat, "id": str(uuid4()), "parent_beat_id": None})
        changed = True
    if changed:
        chapter.beats = rebuilt
        session.add(chapter)
        session.commit()
        session.refresh(chapter)


@router.get("", response_model=list[Story])
def list_stories(session: Session = Depends(get_session)):
    return session.exec(select(Story).where(Story.is_archived == False).order_by(Story.updated_at.desc())).all()

@router.post("", response_model=Story)
def create_story(req: CreateStoryRequest, session: Session = Depends(get_session)):
    story = Story(
        title=req.title,
        description=req.description,
        genre=req.genre,
        character_ids=req.character_ids,
        lorebook_ids=req.lorebook_ids,
        scenario_id=req.scenario_id,
        llm_model=req.llm_model,
        memory=req.memory,
        max_agentic_depth=req.max_agentic_depth,
    )
    story.created_at = datetime.now(timezone.utc)
    story.updated_at = story.created_at
    session.add(story)
    session.commit()
    session.refresh(story)
    return story

@router.get("/{story_id}", response_model=Story)
def get_story(story_id: str, session: Session = Depends(get_session)):
    story = session.get(Story, story_id)
    if not story:
        raise NotFoundError("Story", story_id)
    return story

@router.put("/{story_id}", response_model=Story)
def update_story(story_id: str, req: UpdateStoryRequest, session: Session = Depends(get_session)):
    story = session.get(Story, story_id)
    if not story:
        raise NotFoundError("Story", story_id)
    
    update_data = req.model_dump(exclude_unset=True)
    allowed = {'title', 'description', 'genre', 'character_ids', 'lorebook_ids', 'llm_model', 'memory', 'scenario_id', 'is_archived', 'max_agentic_depth'}
    for key, value in update_data.items():
        if key in allowed:
            setattr(story, key, value)
            
    story.updated_at = datetime.now(timezone.utc)
    session.add(story)
    session.commit()
    session.refresh(story)
    return story

@router.delete("/{story_id}")
def delete_story(story_id: str, session: Session = Depends(get_session)):
    story = session.get(Story, story_id)
    if not story:
        raise NotFoundError("Story", story_id)
    
    chapters = session.exec(select(StoryChapter).where(StoryChapter.story_id == story_id)).all()
    for ch in chapters:
        session.delete(ch)
        
    session.delete(story)
    session.commit()
    return {"message": "Story deleted"}

@router.get("/{story_id}/chapters", response_model=list[StoryChapter])
def list_chapters(story_id: str, session: Session = Depends(get_session)):
    chapters = session.exec(select(StoryChapter).where(StoryChapter.story_id == story_id).order_by(StoryChapter.chapter_number)).all()
    return chapters

@router.post("/{story_id}/chapters", response_model=StoryChapter)
def create_chapter(story_id: str, chapter: StoryChapter, session: Session = Depends(get_session)):
    story = session.get(Story, story_id)
    if not story:
        raise NotFoundError("Story", story_id)
        
    max_chapter = session.exec(select(StoryChapter).where(StoryChapter.story_id == story_id).order_by(StoryChapter.chapter_number.desc())).first()
    chapter.chapter_number = max_chapter.chapter_number + 1 if max_chapter else 1
    chapter.story_id = story_id
    chapter.created_at = datetime.now(timezone.utc)
    chapter.updated_at = chapter.created_at
    
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter

@router.get("/{story_id}/chapters/{chapter_id}", response_model=StoryChapter)
def get_chapter(story_id: str, chapter_id: str, session: Session = Depends(get_session)):
    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)
    return chapter

@router.put("/{story_id}/chapters/{chapter_id}", response_model=StoryChapter)
def update_chapter(story_id: str, chapter_id: str, chapter_update: StoryChapter, session: Session = Depends(get_session)):
    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)
        
    if chapter_update.content is not None:
        chapter.content = chapter_update.content
    if chapter_update.beats is not None:
        chapter.beats = chapter_update.beats
        
    chapter.updated_at = datetime.now(timezone.utc)
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter

@router.delete("/{story_id}/chapters/{chapter_id}")
def delete_chapter(story_id: str, chapter_id: str, session: Session = Depends(get_session)):
    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)
        
    session.delete(chapter)
    session.commit()
    return {"message": "Chapter deleted"}

@router.post("/{story_id}/chapters/{chapter_id}/continue")
async def continue_story(story_id: str, chapter_id: str, data: StoryContinueRequest, session: Session = Depends(get_session)):
    from services.context_builder import build_chat_context_async
    from services.job_queue import queue_manager
    from services.llm_config import get_default_llm_model as _get_default_llm_model

    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)

    story = session.get(Story, story_id)
        
    prompt = data.prompt
    if prompt:
        _ensure_beat_ids(session, chapter)
        chapter.beats.append({
            "id": str(uuid4()),
            "parent_beat_id": (chapter.beats[-1].get("id") if chapter.beats else None),
            "role": StoryBeatRole.USER.value,
            "content": prompt,
        })
        chapter.content += f"\n\n> {prompt}\n\n"
        session.add(chapter)
        session.commit()
        session.refresh(chapter)
    
    # Build story context using the shared context builder so we get
    # semantic lorebook injection, context pruning, and consistent formatting.
    base_prompt = (
        "You are a collaborative AI storyteller. Your task is to continue the story naturally "
        "from the provided text. Maintain the tone and style. Do not include conversational filler "
        "(e.g. 'Sure, here is the continuation:'). Just output the next part of the prose."
    )
    
    system_prompt, context = await build_chat_context_async(
        session,
        [{"role": "user", "content": chapter.content.strip()}],
        lorebook_ids=story.lorebook_ids or None,
        system_prompt_override=base_prompt,
        story_genre=story.genre,
        story_memory=story.memory,
        story_character_ids=story.character_ids or None,
    )
    
    from services.llm_workflow import build_llm_workflow
    from services.job_service import JobService

    job_service = JobService(session)
    workflow, metadata = build_llm_workflow(
        messages=context,
        type_="story_continue",
        story_id=story_id,
        chapter_id=chapter_id,
        model=(story.llm_model if story else None) or _get_default_llm_model(),
        workspace="story",
        extra_metadata={"max_agentic_depth": story.max_agentic_depth} if story.max_agentic_depth is not None else None,
    )
    job = await job_service.create_job(
        task_type="llm",
        workflow=workflow,
        metadata=metadata,
    )
    
    await queue_manager.enqueue(job.id, task_type="llm")
    return {"job_id": job.id}

@router.post("/{story_id}/chapters/{chapter_id}/beats")
def add_beat(story_id: str, chapter_id: str, data: StoryBeatRequest, session: Session = Depends(get_session)):
    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)
        
    content = data.content
    role = data.role

    _ensure_beat_ids(session, chapter)
    chapter.beats.append({
        "id": str(uuid4()),
        "parent_beat_id": (chapter.beats[-1].get("id") if chapter.beats else None),
        "role": role,
        "content": content,
    })
    if role == StoryBeatRole.USER.value:
        chapter.content += f"\n\n> {content}\n\n"
    else:
        chapter.content += f"\n\n{content}\n\n"
        
    chapter.updated_at = datetime.now(timezone.utc)
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter

@router.post("/{story_id}/chapters/{chapter_id}/branch", response_model=StoryChapter)
def branch_chapter(story_id: str, chapter_id: str, data: StoryBranchRequest, session: Session = Depends(get_session)):
    """Fork the story at a specific beat into a new chapter.

    The new chapter keeps the shared history up to (and including) the
    branch point, then continues from there. Content is rebuilt from beats
    so the editor stays consistent with the beat list.
    """
    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)

    _ensure_beat_ids(session, chapter)
    beats = chapter.beats or []

    idx = None
    for i, beat in enumerate(beats):
        if isinstance(beat, dict) and beat.get("id") == data.from_beat_id:
            idx = i
            break
    if idx is None:
        raise NotFoundError("StoryBeat", chapter_id)

    prefix = [dict(b) for b in beats[: idx + 1]]

    prompt = data.prompt.strip()
    if prompt:
        prefix.append({
            "id": str(uuid4()),
            "parent_beat_id": data.from_beat_id,
            "role": StoryBeatRole.USER.value,
            "content": prompt,
        })

    content_parts = []
    for beat in prefix:
        text = (beat.get("content") or "").strip()
        if not text:
            continue
        if beat.get("role") == StoryBeatRole.USER.value:
            content_parts.append(f"\n\n> {text}\n\n")
        else:
            content_parts.append(f"\n\n{text}\n\n")
    new_content = "".join(content_parts).strip()

    max_chapter = session.exec(
        select(StoryChapter).where(StoryChapter.story_id == story_id).order_by(StoryChapter.chapter_number.desc())
    ).first()

    now = datetime.now(timezone.utc)
    branch = StoryChapter(
        story_id=story_id,
        chapter_number=(max_chapter.chapter_number + 1 if max_chapter else 1),
        title=f"Branch from {chapter.title or f'Chapter {chapter.chapter_number}'}",
        content=new_content,
        beats=prefix,
        created_at=now,
        updated_at=now,
    )
    session.add(branch)
    session.commit()
    session.refresh(branch)
    return branch
@router.post("/{story_id}/chapters/{chapter_id}/illustrate")
async def illustrate_chapter(
    story_id: str,
    chapter_id: str,
    data: StoryIllustrateRequest,
    session: Session = Depends(get_session),
):
    from services.job_service import JobService

    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)

    story = session.get(Story, story_id)

    # Resolve checkpoint: story characters > fallback to an installed model
    checkpoint = _resolve_default_checkpoint(session)
    if story and story.character_ids:
        from core.entities import Character
        char = session.get(Character, story.character_ids[0])
        if char and char.checkpoint:
            checkpoint = _resolve_default_checkpoint(session, char.checkpoint)

    if data.image_prompt:
        # Provided prompt: queue image job directly (non-blocking)
        from core.workflow_builder import build_image_job_workflow
        from services.job_submission_service import JobSubmissionService
        submission_service = JobSubmissionService(session)

        image_workflow, image_metadata = build_image_job_workflow(
            prompt=data.image_prompt,
            checkpoint=checkpoint,
            filename_prefix="ComfyUI",
            workspace="story",
            story_id=story_id,
            chapter_id=chapter_id,
            extra_metadata={"prompt": data.image_prompt},
        )
        img_job = await submission_service.create_and_enqueue_job(
            workflow=image_workflow,
            metadata=image_metadata,
        )
        return {"job_id": img_job.id, "prompt": data.image_prompt}

    # No provided prompt: fire an LLM job to generate one, store context for
    # chaining into an image job when the LLM completes.
    system_prompt = (
        "You are an AI art director for a story. Given the story chapter text, "
        "write a highly detailed ComfyUI prompt (comma-separated Danbooru tags, lighting, "
        "camera angle, subjects, mood) that captures the most vivid scene. "
        "Return ONLY the prompt text."
    )

    if story and story.genre:
        system_prompt += f"\nThe genre is {story.genre}."

    if story and story.character_ids:
        from core.entities import Character
        characters_content = []
        for char_id in story.character_ids:
            char = session.get(Character, char_id)
            if char:
                char_text = f"Character: {char.name}\n"
                if char.visual_tags:
                    char_text += f"Visual Tags: {', '.join(char.visual_tags)}\n"
                if char.description:
                    char_text += f"Description: {char.description}\n"
                characters_content.append(char_text)
        if characters_content:
            system_prompt += "\n\nStory Characters (Use these details for illustration):\n" + "\n".join(characters_content)

    # NOTE: Lorebook context is loaded directly here for the art-director prompt.
    # For high-fidelity semantic retrieval, consider routing through
    # build_system_prompt_sections_async (which uses pgvector top-K retrieval).
    if story and story.lorebook_ids:
        lorebooks_content = []
        for lb_id in story.lorebook_ids:
            lb = session.get(Lorebook, lb_id)
            if lb:
                entries = session.exec(
                    select(LorebookEntry).where(LorebookEntry.lorebook_id == lb.id)
                ).all()
                if entries:
                    lb_text = f"Lorebook: {lb.name}\n"
                    for entry in entries:
                        keys_str = ", ".join(entry.keys) if entry.keys else "General"
                        lb_text += f"- [{keys_str}]: {entry.content}\n"
                    lorebooks_content.append(lb_text)
        if lorebooks_content:
            system_prompt += "\n\nRelevant World Lore:\n" + "\n".join(lorebooks_content)

    job_service = JobService(session)
    from services.llm_workflow import build_llm_workflow

    workflow, metadata = build_llm_workflow(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Chapter text:\n{chapter.content[-3000:]}"}
        ],
        type_="story_illustrate_prompt",
        story_id=story_id,
        chapter_id=chapter_id,
        model=(story.llm_model if story else None) or _get_default_llm_model(),
        workspace="story",
        source="story_illustrate_prompt",
        extra_metadata={"scene_checkpoint": checkpoint},
    )
    prompt_job = await job_service.create_job(
        task_type="llm",
        workflow=workflow,
        metadata=metadata,
    )
    await queue_manager.enqueue(prompt_job.id, task_type="llm")

    return {"job_id": prompt_job.id, "status": "queued", "message": "Illustration prompt generation started"}


@router.get("/{story_id}/images")
def list_story_images(story_id: str, session: Session = Depends(get_session)):
    """List all images across the story's chapters (workspace gallery)."""
    story = session.get(Story, story_id)
    if not story:
        raise NotFoundError("Story", story_id)

    chapters = session.exec(
        select(StoryChapter).where(StoryChapter.story_id == story_id).order_by(StoryChapter.created_at)
    ).all()
    images = []
    for chapter in chapters:
        for path in (chapter.image_paths or []):
            images.append({
                "path": path,
                "chapter_id": chapter.id,
                "chapter_title": chapter.title,
            })
    return images


def _resolve_default_checkpoint(session: Session, preferred: str | None = None) -> str:
    """Find a checkpoint that is actually installed on an enabled provider.

    Falls back to the configured default (sd_xl_base_1.0.safetensors) when
    no providers have checkpoints yet, so the error message from the
    provider-level validation will name a concrete model rather than a
    placeholder.
    """
    service = ModelAvailabilityService(session)
    resolved = service.get_available_checkpoint(preferred)
    if resolved:
        return resolved
    from config import get_config
    return get_config().get("generator", {}).get("default_checkpoint", "sd_xl_base_1.0.safetensors")
