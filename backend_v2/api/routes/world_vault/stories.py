from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import get_session
from core.entities import Story, StoryBeatRole, StoryChapter, Lorebook, LorebookEntry
from core.events import wait_for_job_completion
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

@router.get("", response_model=list[Story])
def list_stories(session: Session = Depends(get_session)):
    return session.exec(select(Story).where(Story.is_archived == False).order_by(Story.updated_at.desc())).all()

@router.post("", response_model=Story)
def create_story(story: Story, session: Session = Depends(get_session)):
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
        raise HTTPException(status_code=404, detail="Story not found")
    return story

@router.put("/{story_id}", response_model=Story)
def update_story(story_id: str, story_update: Story, session: Session = Depends(get_session)):
    story = session.get(Story, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    
    update_data = story_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key in ['title', 'description', 'genre', 'character_ids', 'lorebook_ids', 'llm_model', 'memory', 'scenario_id']:
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
        raise HTTPException(status_code=404, detail="Story not found")
    
    chapters = session.exec(select(StoryChapter).where(StoryChapter.story_id == story_id)).all()
    for ch in chapters:
        session.delete(ch)
        
    session.delete(story)
    session.commit()
    return {"message": "Story deleted"}

@router.get("/{story_id}/chapters", response_model=list[StoryChapter])
def list_chapters(story_id: str, session: Session = Depends(get_session)):
    return session.exec(select(StoryChapter).where(StoryChapter.story_id == story_id).order_by(StoryChapter.chapter_number)).all()

@router.post("/{story_id}/chapters", response_model=StoryChapter)
def create_chapter(story_id: str, chapter: StoryChapter, session: Session = Depends(get_session)):
    story = session.get(Story, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
        
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
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter

@router.put("/{story_id}/chapters/{chapter_id}", response_model=StoryChapter)
def update_chapter(story_id: str, chapter_id: str, chapter_update: StoryChapter, session: Session = Depends(get_session)):
    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
        
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
        raise HTTPException(status_code=404, detail="Chapter not found")
        
    session.delete(chapter)
    session.commit()
    return {"message": "Chapter deleted"}

@router.post("/{story_id}/chapters/{chapter_id}/continue")
async def continue_story(story_id: str, chapter_id: str, data: StoryContinueRequest, session: Session = Depends(get_session)):
    from services.job_service import JobService

    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise HTTPException(status_code=404, detail="Chapter not found")

    story = session.get(Story, story_id)
        
    prompt = data.prompt
    if prompt:
        chapter.beats.append({"role": StoryBeatRole.USER, "content": prompt})
        chapter.content += f"\n\n> {prompt}\n\n"
        session.add(chapter)
        session.commit()
        session.refresh(chapter)
        
    messages = []
    system_prompt = (
        "You are a collaborative AI storyteller. Your task is to continue the story naturally "
        "from the provided text. Maintain the tone and style. Do not include conversational filler "
        "(e.g. 'Sure, here is the continuation:'). Just output the next part of the prose."
    )
    
    story = session.get(Story, story_id)
    if story and story.genre:
        system_prompt += f"\nThe genre is {story.genre}."
        
    if story and story.memory:
        system_prompt += f"\n\nGlobal Story Memory (Author's Note):\n{story.memory}\n"
        
    if story and story.character_ids:
        from core.entities import Character
        characters_content = []
        for char_id in story.character_ids:
            char = session.get(Character, char_id)
            if char:
                char_text = f"Character: {char.name}\n"
                if char.description:
                    char_text += f"Description: {char.description}\n"
                if char.personality:
                    char_text += f"Personality: {char.personality}\n"
                if char.scenario:
                    char_text += f"Scenario: {char.scenario}\n"
                characters_content.append(char_text)
        if characters_content:
            system_prompt += "\n\nStory Characters:\n" + "\n".join(characters_content)
        
    if story and story.lorebook_ids:
        lorebooks_content = []
        for lorebook_id in story.lorebook_ids:
            lb = session.get(Lorebook, lorebook_id)
            if lb:
                entries = session.exec(select(LorebookEntry).where(LorebookEntry.lorebook_id == lb.id)).all()
                if entries:
                    lb_text = f"Lorebook: {lb.name}\n"
                    for entry in entries:
                        keys_str = ", ".join(entry.keys) if entry.keys else "General"
                        lb_text += f"- [{keys_str}]: {entry.content}\n"
                    lorebooks_content.append(lb_text)
        
        if lorebooks_content:
            system_prompt += "\n\nRelevant World Lore:\n" + "\n".join(lorebooks_content)
        
    messages.append({"role": "system", "content": system_prompt})
    
    user_context = "Here is the story so far. Please write the next few paragraphs to continue it:\n\n"
    user_context += chapter.content.strip()
    
    messages.append({"role": "user", "content": user_context})
        
    job_service = JobService(session)
    job = await job_service.create_job(
        task_type="llm",
        workflow={
            "messages": messages,
            "story_id": story_id,
            "chapter_id": chapter_id,
            "type": "story_continue",
            "model": (story.llm_model if story else None) or _get_default_llm_model(),
        },
        metadata={"story_id": story_id, "chapter_id": chapter_id, "workspace": "story"}
    )
    
    await queue_manager.enqueue(job.id, task_type="llm")
    return {"job_id": job.id}

@router.post("/{story_id}/chapters/{chapter_id}/beats")
def add_beat(story_id: str, chapter_id: str, data: StoryBeatRequest, session: Session = Depends(get_session)):
    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
        
    content = data.content
    role = data.role
    
    chapter.beats.append({"role": role, "content": content})
    if role == StoryBeatRole.USER.value:
        chapter.content += f"\n\n> {content}\n\n"
    else:
        chapter.content += f"\n\n{content}\n\n"
        
    chapter.updated_at = datetime.now(timezone.utc)
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter

@router.post("/{story_id}/chapters/{chapter_id}/illustrate")
async def illustrate_chapter(
    story_id: str,
    chapter_id: str,
    data: StoryIllustrateRequest,
    session: Session = Depends(get_session),
):
    from services.job_service import JobService
    from services.job_submission_service import JobSubmissionService

    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise HTTPException(status_code=404, detail="Chapter not found")

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
        from services.job_submission_service import JobSubmissionService
        submission_service = JobSubmissionService(session)

        image_workflow = build_image_workflow(
            prompt=data.image_prompt,
            checkpoint=checkpoint,
            filename_prefix="ComfyUI",
        )
        img_job = await submission_service.create_and_enqueue_job(
            workflow=image_workflow,
            metadata={
                "story_id": story_id,
                "chapter_id": chapter_id,
                "prompt": data.image_prompt,
            }
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
    prompt_job = await job_service.create_job(
        task_type="llm",
        workflow={
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Chapter text:\n{chapter.content[-3000:]}"}
            ],
            "model": (story.llm_model if story else None) or _get_default_llm_model(),
        },
        metadata={
            "source": "story_illustrate_prompt",
            "story_id": story_id,
            "chapter_id": chapter_id,
            "scene_checkpoint": checkpoint,
        }
    )
    await queue_manager.enqueue(prompt_job.id, task_type="llm")

    return {"job_id": prompt_job.id, "status": "queued", "message": "Illustration prompt generation started"}


@router.get("/{story_id}/images")
def list_story_images(story_id: str, session: Session = Depends(get_session)):
    """List all images across the story's chapters (workspace gallery)."""
    story = session.get(Story, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

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
