from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont
from sqlmodel import Session, select

from api.deps import get_job_service, get_session, get_queue_manager
from services.reference_cleanup import scrub_entity_references
from core.entities import Story, StoryBeatRole, StoryChapter, Lorebook, LorebookEntry, Character
from core.exceptions import ComfyError, NotFoundError
from services.llm_config import get_default_llm_model as _get_default_llm_model
from services.llm_workflow import build_llm_workflow, build_chat_llm_workflow
from services.job_service import JobService
from services.job_queue import QueueManager, queue_manager
from services.model_availability_service import ModelAvailabilityService

router = APIRouter()


class StoryContinueRequest(BaseModel):
    prompt: str = ""


class ParseStoryRequest(BaseModel):
    story_id: str
    text: str


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


@router.get("/{story_id}/export")
def export_story(story_id: str, format: str = "json", session: Session = Depends(get_session)):
    story = session.get(Story, story_id)
    if not story:
        raise NotFoundError("Story", story_id)
    chapters = session.exec(
        select(StoryChapter).where(StoryChapter.story_id == story_id).order_by(StoryChapter.chapter_number)
    ).all()

    characters = session.exec(
        select(Character).where(Character.id.in_(story.character_ids or []))
    ).all() if story.character_ids else []
    lorebooks = session.exec(
        select(Lorebook).where(Lorebook.id.in_(story.lorebook_ids or []))
    ).all() if story.lorebook_ids else []

    def _serialize_chapter(ch: StoryChapter) -> dict:
        return {
            "id": ch.id,
            "title": ch.title,
            "content": ch.content,
            "chapter_number": ch.chapter_number,
            "beats": ch.beats or [],
            "image_paths": ch.image_paths or [],
            "created_at": ch.created_at.isoformat() if ch.created_at else None,
            "updated_at": ch.updated_at.isoformat() if ch.updated_at else None,
        }

    if format in ("md", "markdown"):
        # Generate Markdown export with inline images
        md_parts = []
        md_parts.append(f"# {story.title}\n")
        if story.description:
            md_parts.append(f"*{story.description}*\n")
        if story.genre:
            md_parts.append(f"**Genre:** {story.genre}\n")
        if story.memory:
            md_parts.append(f"\n## Author's Note\n\n{story.memory}\n")
        if characters:
            md_parts.append("\n## Characters\n")
            for c in characters:
                md_parts.append(f"- **{c.name}**")
                if c.description:
                    md_parts.append(f": {c.description}")
                md_parts.append("\n")
        md_parts.append("\n---\n")
        for ch in chapters:
            md_parts.append(f"## Chapter {ch.chapter_number}: {ch.title or 'Untitled'}\n")
            content = ch.content.strip()
            if content:
                md_parts.append(f"\n{content}\n")
            for path in (ch.image_paths or []):
                md_parts.append(f"\n![Image]({path})\n")
        return {"type": "markdown", "content": "\n".join(md_parts)}

    if format == "epub":
        # Generate a minimal ePub (ZIP with required files)
        import zipfile, io, html as html_lib
        from uuid import uuid4 as _uuid4

        epub_id = str(_uuid4())
        title = story.title or "Untitled Story"

        def _build_epub() -> bytes:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                # mimetype (must be first and uncompressed)
                zf.writestr("mimetype", "application/epub+zip")
                # META-INF/container.xml
                zf.writestr(
                    "META-INF/container.xml",
                    f'''<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
                )
                # OEBPS/content.opf
                manifest_items = '<item id="css" href="style.css" media-type="text/css"/>'
                spine_items = ""
                for idx, ch in enumerate(chapters):
                    manifest_items += f'<item id="chap{idx}" href="chapter{idx}.xhtml" media-type="application/xhtml+xml"/>'
                    spine_items += f'<itemref idref="chap{idx}"/>'
                zf.writestr(
                    "OEBPS/content.opf",
                    f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:identifier id="bookid">{epub_id}</dc:identifier>
    <dc:title>{html_lib.escape(title)}</dc:title>
    <dc:creator>Auto-exported by TNHComfy</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    {manifest_items}
  </manifest>
  <spine>
    {spine_items}
  </spine>
</package>'''
                )
                # CSS
                zf.writestr("OEBPS/style.css", "body { font-family: serif; margin: 2em; line-height: 1.6; } h1 { color: #333; }")
                # Chapters
                for idx, ch in enumerate(chapters):
                    content = html_lib.escape(ch.content.strip() or "")
                    images = "".join(
                        f'<img src="{html_lib.escape(p)}" alt="Illustration" style="max-width:100%;"/>'
                        for p in (ch.image_paths or [])
                    )
                    zf.writestr(
                        f"OEBPS/chapter{idx}.xhtml",
                        f'''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Chapter {idx + 1}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
  <body>
    <h1>Chapter {idx + 1}: {html_lib.escape(ch.title or '')}</h1>
    <p>{content}</p>
    {images}
  </body>
</html>'''
                    )
            return buf.getvalue()

        epub_bytes = _build_epub()
        return Response(
            content=epub_bytes,
            media_type="application/epub+zip",
            headers={
                "Content-Disposition": f'inline; filename="{title.replace(" ", "_")}.epub"',
                "Content-Type": "application/epub+zip",
            },
        )

    if format == "comic":
        comic_pages = []
        panel_w, panel_h = 800, 1200
        margin = 40
        for ch in chapters:
            text = ch.content.strip() or ""
            paragraphs = text.split("\n\n") if text else []
            images = ch.image_paths or []
            combined = []
            for p in paragraphs:
                combined.append(("text", p))
            for img_path in images:
                combined.append(("image", img_path))
            if not combined:
                combined.append(("text", ch.title or "Untitled"))

            page = Image.new("RGB", (panel_w, panel_h), (30, 30, 30))
            draw = ImageDraw.Draw(page)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
            except Exception:
                font = ImageFont.load_default()

            y = margin
            draw.text((margin, y), ch.title or f"Chapter {ch.chapter_number}", fill=(255, 255, 255), font=font)
            y += 60
            for kind, value in combined:
                if kind == "text":
                    lines = value.split("\n")
                    for line in lines:
                        draw.text((margin, y), line, fill=(220, 220, 220), font=font)
                        y += 40
                elif kind == "image":
                    try:
                        img = Image.open(value)
                        img.thumbnail((panel_w - margin * 2, panel_h // 2))
                        page.paste(img, (margin, y))
                        y += img.height + 10
                    except Exception:
                        pass
                if y > panel_h - margin:
                    break
            comic_pages.append(page)

        if not comic_pages:
            comic_pages.append(Image.new("RGB", (panel_w, panel_h), (30, 30, 30)))

        buf = BytesIO()
        comic_pages[0].save(buf, format="PDF", save_all=True, append_images=comic_pages[1:])
        buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{title.replace(" ", "_")}_comic.pdf"',
                "Content-Type": "application/pdf",
            },
        )

    if format == "webtoon":
        webtoon_w = 800
        margin = 40
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        except Exception:
            font = ImageFont.load_default()

        segments = []
        for ch in chapters:
            text = ch.content.strip() or ""
            paragraphs = text.split("\n\n") if text else []
            images = ch.image_paths or []
            for p in paragraphs:
                segments.append(("text", p))
            for img_path in images:
                segments.append(("image", img_path))
            if not segments:
                segments.append(("text", ch.title or "Untitled"))

        total_height = margin
        for kind, value in segments:
            if kind == "text":
                lines = value.split("\n")
                total_height += len(lines) * 40 + 10
            elif kind == "image":
                try:
                    with Image.open(value) as img:
                        ratio = (webtoon_w - margin * 2) / img.width
                        total_height += int(img.height * ratio) + 10
                except Exception:
                    total_height += 200
        total_height += margin

        webtoon = Image.new("RGB", (webtoon_w, total_height), (30, 30, 30))
        draw = ImageDraw.Draw(webtoon)
        y = margin
        for ch in chapters:
            draw.text((margin, y), ch.title or f"Chapter {ch.chapter_number}", fill=(255, 255, 255), font=font)
            y += 60
        for kind, value in segments:
            if kind == "text":
                lines = value.split("\n")
                for line in lines:
                    draw.text((margin, y), line, fill=(220, 220, 220), font=font)
                    y += 40
            elif kind == "image":
                try:
                    img = Image.open(value)
                    ratio = (webtoon_w - margin * 2) / img.width
                    new_h = int(img.height * ratio)
                    img = img.resize((webtoon_w - margin * 2, new_h))
                    webtoon.paste(img, (margin, y))
                    y += new_h + 10
                except Exception:
                    y += 200

        buf = BytesIO()
        webtoon.save(buf, format="PNG")
        buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="image/png",
            headers={
                "Content-Disposition": f'inline; filename="{title.replace(" ", "_")}_webtoon.png"',
                "Content-Type": "image/png",
            },
        )

    # Default: JSON export (existing behaviour)

    payload = {
        "story": {
            "id": story.id,
            "title": story.title,
            "description": story.description,
            "genre": story.genre,
            "memory": story.memory,
            "created_at": story.created_at.isoformat() if story.created_at else None,
            "updated_at": story.updated_at.isoformat() if story.updated_at else None,
        },
        "characters": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "personality": c.personality,
            }
            for c in characters
        ],
        "lorebooks": [
            {
                "id": l.id,
                "name": l.name,
                "description": l.description,
            }
            for l in lorebooks
        ],
        "chapters": [_serialize_chapter(ch) for ch in chapters],
        "meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "chapter_count": len(chapters),
            "character_count": len(characters),
            "lorebook_count": len(lorebooks),
        },
    }
    return payload


@router.post("/{story_id}/publish", response_model=dict)
def publish_story(story_id: str, session: Session = Depends(get_session)):
    """Publish a story and generate a shareable token for public reading."""
    from secrets import token_urlsafe

    story = session.get(Story, story_id)
    if not story:
        raise NotFoundError("Story", story_id)

    if not story.is_published:
        story.published_token = token_urlsafe(32)
        story.is_published = True
        story.published_at = datetime.now(timezone.utc)
    else:
        # Regenerate token on re-publish
        story.published_token = token_urlsafe(32)
        story.published_at = datetime.now(timezone.utc)

    session.add(story)
    session.commit()
    session.refresh(story)

    return {
        "story_id": story_id,
        "title": story.title,
        "published_token": story.published_token,
        "is_published": story.is_published,
        "published_at": story.published_at.isoformat() if story.published_at else None,
        "read_url": f"/read/story/{story.published_token}",
    }


@router.post("/{story_id}/unpublish", response_model=dict)
def unpublish_story(story_id: str, session: Session = Depends(get_session)):
    """Unpublish a story (revoke its public token)."""
    story = session.get(Story, story_id)
    if not story:
        raise NotFoundError("Story", story_id)

    story.is_published = False
    story.published_token = None
    session.add(story)
    session.commit()
    session.refresh(story)

    return {
        "story_id": story_id,
        "is_published": False,
        "published_token": None,
    }


@router.get("/published/{token}")
def read_published_story(token: str, session: Session = Depends(get_session)):
    """Read a published story by its token (public, read-only)."""
    story = session.exec(
        select(Story).where(Story.published_token == token, Story.is_published == True)
    ).first()
    if not story:
        raise NotFoundError("PublishedStory", token)

    chapters = session.exec(
        select(StoryChapter).where(StoryChapter.story_id == story.id).order_by(StoryChapter.chapter_number)
    ).all()

    characters = session.exec(
        select(Character).where(Character.id.in_(story.character_ids or []))
    ).all() if story.character_ids else []

    return {
        "story": {
            "title": story.title,
            "description": story.description,
            "genre": story.genre,
            "memory": story.memory,
            "published_at": story.published_at.isoformat() if story.published_at else None,
        },
        "characters": [
            {"name": c.name, "description": c.description, "personality": c.personality}
            for c in characters
        ],
        "chapters": [
            {
                "chapter_number": ch.chapter_number,
                "title": ch.title,
                "content": ch.content,
                "image_paths": ch.image_paths or [],
            }
            for ch in chapters
        ],
    }


@router.get("/published/{token}/export")
def export_published_story(token: str, format: str = "json", session: Session = Depends(get_session)):
    """Export a published story by its token (public, read-only)."""
    story = session.exec(
        select(Story).where(Story.published_token == token, Story.is_published == True)
    ).first()
    if not story:
        raise NotFoundError("PublishedStory", token)

    # Build a minimal story dict and reuse the same export logic
    # by calling export_story with the resolved story_id
    return export_story(story.id, format=format, session=session)


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


class ChapterReorderRequest(BaseModel):
    chapter_ids: list[str]


@router.post("/{story_id}/chapters/reorder")
def reorder_chapters(story_id: str, req: ChapterReorderRequest, session: Session = Depends(get_session)):
    story = session.get(Story, story_id)
    if not story:
        raise NotFoundError("Story", story_id)
    chapters = session.exec(select(StoryChapter).where(StoryChapter.story_id == story_id)).all()
    chapter_map = {ch.id: ch for ch in chapters}
    for idx, ch_id in enumerate(req.chapter_ids):
        ch = chapter_map.get(ch_id)
        if ch:
            ch.chapter_number = idx + 1
            session.add(ch)
    session.commit()
    return {"message": "Chapters reordered"}


@router.delete("/{story_id}")
def delete_story(story_id: str, session: Session = Depends(get_session)):
    story = session.get(Story, story_id)
    if not story:
        raise NotFoundError("Story", story_id)
    
    scrub_entity_references(session, "story", story_id)
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
    _ensure_beat_ids(session, chapter)
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
        [{"role": "user", "content": chapter.content.strip()}],
        lorebook_ids=story.lorebook_ids or None,
        system_prompt_override=base_prompt,
        story_genre=story.genre,
        story_memory=story.memory,
        story_character_ids=story.character_ids or None,
    )
    

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

    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)

    story = session.get(Story, story_id)

    # Resolve checkpoint: story characters > fallback to an installed model
    checkpoint = _resolve_default_checkpoint(session)
    if story and story.character_ids:
        char = session.get(Character, story.character_ids[0])
        if char and char.checkpoint:
            checkpoint = _resolve_default_checkpoint(session, char.checkpoint)

    if data.image_prompt:
        # Provided prompt: queue image job directly (non-blocking)
        from services.image_submission import submit_image_job

        img_job = await submit_image_job(
            session,
            prompt=data.image_prompt,
            checkpoint=checkpoint,
            filename_prefix="ComfyUI",
            workspace="story",
            story_id=story_id,
            chapter_id=chapter_id,
            extra_metadata={"prompt": data.image_prompt},
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
        chars = session.exec(
            select(Character).where(Character.id.in_(story.character_ids))
        ).all()
        char_map = {c.id: c for c in chars}
        characters_content = []
        for char_id in story.character_ids:
            char = char_map.get(char_id)
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
        # Batch-load all lorebooks + their entries in 2 queries instead of 2N
        lorebooks = session.exec(
            select(Lorebook).where(Lorebook.id.in_(story.lorebook_ids))
        ).all()
        lb_map = {lb.id: lb for lb in lorebooks}
        all_entries = session.exec(
            select(LorebookEntry).where(LorebookEntry.lorebook_id.in_(story.lorebook_ids))
        ).all()
        entries_by_lb: dict[str, list] = {}
        for entry in all_entries:
            entries_by_lb.setdefault(entry.lorebook_id, []).append(entry)
        lorebooks_content = []
        for lb_id in story.lorebook_ids:
            lb = lb_map.get(lb_id)
            if lb:
                entries = entries_by_lb.get(lb.id, [])
                if entries:
                    lb_text = f"Lorebook: {lb.name}\n"
                    for entry in entries:
                        keys_str = ", ".join(entry.keys) if entry.keys else "General"
                        lb_text += f"- [{keys_str}]: {entry.content}\n"
                    lorebooks_content.append(lb_text)
        if lorebooks_content:
            system_prompt += "\n\nRelevant World Lore:\n" + "\n".join(lorebooks_content)

    job_service = JobService(session)

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


@router.post("/{story_id}/chapters/{chapter_id}/narrate", response_model=dict)
async def narrate_chapter(
    story_id: str,
    chapter_id: str,
    session: Session = Depends(get_session),
    job_service: JobService = Depends(get_job_service),
    queue_manager: QueueManager = Depends(get_queue_manager),
):
    """Trigger TTS narration for an entire story chapter."""
    from core.workflow_builder import build_tts_workflow
    from services.chat_utils import resolve_voice_for_character

    story = session.get(Story, story_id)
    if not story:
        raise NotFoundError("Story", story_id)
    chapter = session.get(StoryChapter, chapter_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)

    text = chapter.content.strip()
    if not text:
        raise ComfyError("Chapter has no content to narrate")

    # Resolve voice model from story or first character
    voice_profile = voice_model_id = language = None
    if story.character_ids:
        char = session.get(Character, story.character_ids[0])
        voice_profile, voice_model_id, language = resolve_voice_for_character(session, char)

    workflow, metadata = build_tts_workflow(
        text=text,
        voice_profile=voice_profile,
        voice_model_id=voice_model_id,
        language=language,
        story_id=story_id,
        chapter_id=chapter_id,
        extra_metadata={
            "source": "story_tts",
        }
    )

    job = await job_service.create_job(
        task_type="image",
        workflow=workflow,
        metadata=metadata,
    )
    await queue_manager.enqueue(job.id, task_type="image")

    return {"job_id": job.id, "chapter_id": chapter_id, "story_id": story_id}


def _resolve_default_checkpoint(session: Session, preferred: str | None = None) -> str:
    """Find a checkpoint that is actually installed on an enabled provider.

    Falls back to the configured default when no providers have checkpoints
    yet, so the error message from the provider-level validation will name a
    concrete model rather than a placeholder.

    Delegates to :meth:`ModelAvailabilityService.resolve_checkpoint` which
    consolidates the full resolution chain (preferred → available → config
    default → ``sd_xl_base_1.0.safetensors``).
    """
    return ModelAvailabilityService(session).resolve_checkpoint(preferred)


@router.post("/parse")
async def parse_story(req: ParseStoryRequest, session: Session = Depends(get_session)) -> dict:

    system_prompt = """You are an AI worldbuilder. Parse the provided story text and extract the following:
1. Characters (name, physical appearance, personality)
2. Locations (name, description)
3. Key Lore (important items, concepts, organizations)

Return a strictly valid JSON object in this format:
{
  "characters": [ {"name": "...", "description": "...", "personality": "..."} ],
  "locations": [ {"name": "...", "description": "..."} ],
  "lorebooks": [ {"name": "...", "description": "..."} ]
}
"""
    workflow, metadata = build_chat_llm_workflow(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": req.text[:10000]}  # limit text length
        ],
        chat_id=None,
        character_id=None,
        model=_get_default_llm_model(),
        type_="story_parse"
    )
    metadata["story_id"] = req.story_id
    metadata["workspace"] = "story"
    job_service = get_job_service(session)
    job = await job_service.create_job(task_type="llm", workflow=workflow, metadata=metadata)
    session.commit()
    await queue_manager.enqueue(job.id, task_type="llm")
    return {"job_id": job.id}
