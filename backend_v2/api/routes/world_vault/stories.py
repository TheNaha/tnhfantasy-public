import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import get_job_service, get_job_submission_service, get_session
from core.entities import Story, StoryBeatRole, StoryChapter
from services.job_queue import job_queue

router = APIRouter()


class StoryContinueRequest(BaseModel):
    prompt: str = ""


class StoryBeatRequest(BaseModel):
    content: str
    role: str = "user"


class StoryIllustrateRequest(BaseModel):
    image_prompt: str = ""

@router.get("/", response_model=list[Story])
def list_stories(session: Session = Depends(get_session)):
    return session.exec(select(Story).where(Story.is_archived == False).order_by(Story.updated_at.desc())).all()

@router.post("/", response_model=Story)
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
        if key in ['title', 'description', 'genre', 'character_ids', 'lorebook_ids']:
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
    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
        
    prompt = data.prompt
    if prompt:
        # If user explicitly provided a prompt/action via the "Add Beat" style input
        chapter.beats.append({"role": StoryBeatRole.USER, "content": prompt})
        chapter.content += f"\n\n> {prompt}\n\n"
        session.add(chapter)
        session.commit()
        session.refresh(chapter)
        
    messages = []
    # Base instructions for the AI
    system_prompt = (
        "You are a collaborative AI storyteller. Your task is to continue the story naturally "
        "from the provided text. Maintain the tone and style. Do not include conversational filler "
        "(e.g. 'Sure, here is the continuation:'). Just output the next part of the prose."
    )
    
    story = session.get(Story, story_id)
    if story and story.genre:
        system_prompt += f"\nThe genre is {story.genre}."
        
    if story and story.lorebook_ids:
        from core.entities import Lorebook, LorebookEntry
        from sqlmodel import select
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
    
    # Use the actual full edited content as context
    user_context = "Here is the story so far. Please write the next few paragraphs to continue it:\n\n"
    user_context += chapter.content.strip()
    
    messages.append({"role": "user", "content": user_context})
        
    job_service = get_job_service(session)
    job = await job_service.create_job(
        task_type="text",
        workflow={
            "messages": messages,
            "chat_id": story_id,
            "chapter_id": chapter_id,
            "type": "story_continue"
        },
        metadata={"story_id": story_id, "chapter_id": chapter_id, "workspace": "story"}
    )
    
    await job_queue.enqueue(job.id)
    return {"job_id": job.id}

@router.post("/{story_id}/chapters/{chapter_id}/beats")
def add_beat(story_id: str, chapter_id: str, data: StoryBeatRequest, session: Session = Depends(get_session)):
    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
        
    content = data.content
    role = data.role
    
    chapter.beats.append({"role": role, "content": content})
    if role == StoryBeatRole.USER:
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
    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise HTTPException(status_code=404, detail="Chapter not found")

    story = session.get(Story, story_id)

    if data.image_prompt:
        enriched_prompt = data.image_prompt
    else:
        from core.entities import JobStatus, Lorebook, LorebookEntry
        from services.job_service import JobService

        system_prompt = (
            "You are an AI art director for a story. Given the story chapter text, "
            "write a highly detailed ComfyUI prompt (comma-separated Danbooru tags, lighting, "
            "camera angle, subjects, mood) that captures the most vivid scene. "
            "Return ONLY the prompt text."
        )

        if story and story.genre:
            system_prompt += f"\nThe genre is {story.genre}."

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
            task_type="text",
            workflow={
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Chapter text:\n{chapter.content[-3000:]}"}
                ]
            },
            metadata={"source": "story_illustrate_prompt"}
        )
        await job_queue.enqueue(prompt_job.id)

        enriched_prompt = "beautiful scenery, masterpiece, high quality, highly detailed"
        for _ in range(30):
            status = await job_service.get_job(prompt_job.id)
            if status.status == JobStatus.COMPLETED:
                if status.outputs and len(status.outputs) > 0:
                    enriched_prompt = status.outputs[0].get("content", enriched_prompt)
                break
            elif status.status in (JobStatus.FAILED, JobStatus.CANCELLED):
                break
            await asyncio.sleep(1.0)

    submission_service = get_job_submission_service(session)

    image_workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 0, "steps": 20, "cfg": 7, "sampler_name": "euler",
                "scheduler": "normal", "denoise": 1,
                "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                "latent_image": ["5", 0]
            }
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"batch_size": 1, "width": 1024, "height": 1024}
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": enriched_prompt, "clip": ["4", 1]}
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "worst quality, low quality, bad anatomy, bad hands, missing fingers",
                "clip": ["4", 1]
            }
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]}
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]}
        }
    }

    img_job = await submission_service.create_and_enqueue_job(
        workflow=image_workflow,
        metadata={
            "story_id": story_id,
            "chapter_id": chapter_id,
            "prompt": enriched_prompt,
        }
    )

    return {"job_id": img_job.id, "prompt": enriched_prompt}
