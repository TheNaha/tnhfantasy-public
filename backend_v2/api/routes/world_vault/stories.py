import asyncio
import difflib
import os
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field
from PIL import Image, ImageDraw, ImageFont
from sqlmodel import Session, delete, select

import config as app_config
from api.deps import get_session, get_story_repo, get_story_chapter_repo, get_story_revision_repo, get_chat_repo
from infrastructure.logging import get_logger
from infrastructure.repositories.chat_repo import ChatRepository
from infrastructure.repositories.story_repo import StoryRepository
from infrastructure.repositories.story_chapter_repo import StoryChapterRepository
from infrastructure.repositories.story_revision_repo import StoryChapterRevisionRepository
from services.reference_cleanup import scrub_entity_references
from core.entities import (
    Asset,
    AssetKind,
    Character,
    Chat,
    Location,
    Lorebook,
    Message,
    MessageRole,
    Scenario,
    Story,
    StoryBeatRole,
    StoryChapter,
    StoryChapterRevision,
)
from core.exceptions import ComfyError, NotFoundError, ValidationError
from services.world_integration_service import SOURCE_JOB_ID_METADATA_KEY
from services.llm_workflow import build_llm_workflow, build_chat_llm_workflow, sampler_overrides
from services.rag_pipeline import search_lorebook_entries
from services.job_submission_service import submit_llm_job, submit_tts_job
from services.world_ownership import link_to_world, require_world
from services.model_availability_service import ModelAvailabilityService
from services.world_integration_service import TTS_BEAT_ROLE

# Comic/webtoon export layout dimensions — extracted from the inline literals so
# the values cannot silently drift between the comic and webtoon branches.
_COMIC_PANEL_W, _COMIC_PANEL_H = 800, 1200
_COMIC_MARGIN = 40
_WEBTOON_W = 800
_WEBTOON_MARGIN = 40

# Font path for comic/webtoon PDF text rendering. Overridable via env var so a
# deployment without DejaVu fonts (e.g. slim containers) can point at any
# installed TTF.
_COMIC_FONT_PATH = os.environ.get(
    "COMFY_COMIC_FONT_PATH",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

logger = get_logger("stories_route")
router = APIRouter()

# Page ceiling for the story list. Every sibling list route in this app is
# bounded and documents why; this one was not.
MAX_STORIES_PAGE_SIZE = 200



def _model_for_kind(kind: str, override: str | None, session):
    """Resolve the model for a job kind, honouring a per-chat/Story pin.

    Declared here so the ~10 call sites in this module stay short, but the
    decision itself is `services.llm_config.model_for_kind` — the single
    authority shared with the chat routes.
    """
    from services.llm_config import model_for_kind

    return model_for_kind(kind, override, session)


class StoryContinueRequest(BaseModel):
    prompt: str = ""
    directive: str | None = None
    director_preset: str | None = None


class AdoptWorldbuildingRequest(BaseModel):
    name: str
    category: str = "location"  # "location" | "faction" | "lore" | "character"
    summary: str = ""
    tags: list[str] = []
    target_action: str = "create_location"  # "create_location" | "create_lorebook_entry"
    world_id: str | None = None
    lorebook_id: str | None = None



class StoryActionRequest(BaseModel):
    action: str  # "rewrite" | "expand" | "summarize"
    target_text: str = ""
    directive: str = ""


class ParseStoryRequest(BaseModel):
    story_id: str
    text: str


class StoryBeatRequest(BaseModel):
    content: str
    role: str = "user"



class StoryBeatUpdateRequest(BaseModel):
    content: str | None = None
    role: str | None = None

class SelectAlternateRequest(BaseModel):
    """Which of a beat's takes to show, for the select-alternate route."""
    index: int = 0

class StoryIllustrateRequest(BaseModel):
    image_prompt: str = ""


class StoryBranchRequest(BaseModel):
    from_beat_id: str
    prompt: str = ""


# Distinguishes "no world_id in this PATCH" from "detach from the world".
_WORLD_ID_UNSET = object()

class CreateStoryRequest(BaseModel):
    title: str
    # See `CreateChatRequest.world_id` in chats.py — same column, same reason.
    world_id: str | None = None
    description: str | None = None
    genre: str | None = None
    character_ids: list[str] = []
    lorebook_ids: list[str] = []
    location_ids: list[str] = []
    scenario_id: str | None = None
    llm_model: str | None = None
    memory: str | None = None
    max_agentic_depth: int | None = None
    pov: str | None = None
    word_count_goal: int | None = None


class UpdateStoryRequest(BaseModel):
    title: str | None = None
    world_id: str | None = None
    description: str | None = None
    genre: str | None = None
    character_ids: list[str] | None = None
    lorebook_ids: list[str] | None = None
    location_ids: list[str] | None = None
    scenario_id: str | None = None
    llm_model: str | None = None
    memory: str | None = None
    is_archived: bool | None = None
    max_agentic_depth: int | None = None
    # Declared here as well as in `update_story`'s allow-list. Both are needed:
    # this schema is the only reason `model_dump(exclude_unset=True)` can see
    # the key, and it has no `extra: "forbid"` — so an undeclared field is not
    # rejected, it is silently absent, which is how "Autonomous Illustration ->
    # 0" came back 200 and did nothing.
    max_agentic_images: int | None = None
    # Who the reader character is. On the schema as well as the allow-list,
    # because `model_dump(exclude_unset=True)` can only forward a field the
    # request model declares — and an undeclared one is silently absent rather
    # than rejected, which is how the story's "Autonomous Illustration" slider
    # came to write nothing.
    persona_id: str | None = None
    persona_name: str | None = None
    persona_description: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    pov: str | None = None
    word_count_goal: int | None = None


def ensure_beat_ids(chapter: StoryChapter) -> bool:
    """Assign stable ids to beats that predate branching support.

    Beats are stored as JSON dicts; branching needs a per-beat id to fork
    from. Legacy beats have none, so backfill them lazily (idempotent).

    NOTE: MutableList does NOT track in-place mutation of its dict members,
    so the list must be rebuilt (assignment) for the change to persist.

    Takes no session and commits nothing: it is now called from
    `append_beat`, which the job handler uses with a session it does not own,
    and from routes that save the chapter themselves. The old
    session+commit+refresh version could not be called from a handler holding
    an in-flight transaction.
    """
    if not chapter.beats:
        return False
    rebuilt = []
    changed = False
    for beat in chapter.beats:
        if not isinstance(beat, dict):
            rebuilt.append(beat)
            continue
        if beat.get("id"):
            rebuilt.append(beat)
            continue
        rebuilt.append({**beat, "id": str(uuid4()), "parent_beat_id": None})
        changed = True
    if changed:
        chapter.beats = rebuilt
    return changed


def _ensure_beat_ids(session: Session, chapter: StoryChapter) -> None:
    """The committing variant, for routes that want the backfill persisted at once."""
    if ensure_beat_ids(chapter):
        session.add(chapter)
        session.commit()
        session.refresh(chapter)


def _resolve_story_image_path(value: str | None) -> str | None:
    """Resolve a possibly-relative image path to an existing file on disk.

    Story image references (``chapter.image_paths`` and ``Asset.relative_path``)
    are stored relative to ``OUTPUT_DIR``; opening them directly fails. This
    resolves them against the configured output directory and returns the
    absolute path only when the file actually exists.
    """
    if not value:
        return None
    output_dir = os.path.realpath(app_config.settings.output_dir)
    candidate = os.path.realpath(
        value if os.path.isabs(value) else os.path.join(output_dir, value.lstrip("/\\"))
    )
    try:
        if os.path.commonpath([candidate, output_dir]) != output_dir:
            return None
    except ValueError:
        return None
    return candidate if os.path.exists(candidate) else None


def _collect_story_illustration_assets(session: Session, story_id: str) -> list[str]:
    """Return absolute, on-disk image paths for a story's illustration assets.

    Illustration images generated via the story workspace are indexed in the
    ``assets`` table with ``story_id`` set. We only return paths that exist on
    disk so the comic export never silently falls back to a gray placeholder
    for a missing file.
    """
    rows = session.exec(
        select(Asset)
        .where(
            Asset.story_id == story_id,
            Asset.kind == AssetKind.IMAGE,
            Asset.deleted_at == None,  # noqa: E711
        )
        .order_by(Asset.created_at)
    ).all()
    paths = []
    for asset in rows:
        resolved = _resolve_story_image_path(asset.relative_path)
        if resolved:
            paths.append(resolved)
    return paths


def _chapter_panel_images(ch: StoryChapter, story_asset_paths: list[str], asset_cursor: list[int]) -> list[str]:
    """Resolve real, on-disk image paths for a chapter's comic/webtoon panel.

    Prefers the chapter's own ``image_paths`` (resolved against ``OUTPUT_DIR``).
    When a chapter has none, borrows the next available story illustration asset
    so panels are populated with real art instead of blank gray placeholders.
    Returns a list of absolute image paths (empty when no image is available).
    """
    resolved = [p for p in (_resolve_story_image_path(v) for v in (ch.image_paths or [])) if p]
    if resolved:
        return resolved
    if story_asset_paths:
        img = story_asset_paths[asset_cursor[0] % len(story_asset_paths)]
        asset_cursor[0] += 1
        return [img]
    return []


@router.get("", response_model=list[Story])
def list_stories(
    session: Session = Depends(get_session),
    story_repo: StoryRepository = Depends(get_story_repo),
    # Bound at the declaration, not inside the handler: this route has a bound
    # at `le=10000`, and the list route 15 lines above it documents the rule —
    # "the strict bound is the house style for a reason" — so the gap is a
    # documentation/maintenance divergence, not a missing opinion. A bare
    # `limit: int = 100` accepts `?limit=100000000` and reads the whole story
    # table, which on a long campaign is a second of blocking I/O per request.
    #
    # `list_active` is clamped defensively below too, because it is also reachable
    # from `StoryRepository` directly by other services.
    limit: int = Query(100, ge=1, le=MAX_STORIES_PAGE_SIZE),
    offset: int = Query(0, ge=0),
):
    return story_repo.list_active(limit=limit, offset=offset)

@router.post("", response_model=Story)
def create_story(req: CreateStoryRequest, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo)):
    require_world(session, req.world_id)
    story = Story(
        title=req.title,
        description=req.description,
        genre=req.genre,
        character_ids=req.character_ids,
        lorebook_ids=req.lorebook_ids,
        location_ids=req.location_ids,
        scenario_id=req.scenario_id,
        llm_model=req.llm_model,
        memory=req.memory,
        max_agentic_depth=req.max_agentic_depth,
        pov=req.pov,
        word_count_goal=req.word_count_goal,
    )
    story.created_at = datetime.now(timezone.utc)
    story.updated_at = story.created_at
    link_to_world(session, story, req.world_id)
    session.add(story)
    session.commit()
    session.refresh(story)
    # Create a default placeholder chapter so every story starts with
    # at least one writable chapter.  The frontend auto-selects this.
    default_chapter = StoryChapter(
        story_id=story.id,
        chapter_number=1,
        title="Chapter 1",
        content="",
    )
    session.add(default_chapter)
    session.commit()
    session.refresh(story)
    return story

@router.get("/{story_id}", response_model=Story)
def get_story(story_id: str, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo)):
    story = story_repo.get(story_id)
    if not story:
        raise NotFoundError("Story", story_id)
    return story


@router.get("/{story_id}/export")
def export_story(story_id: str, format: str = "json", session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), published: bool = False):
    """Export a story.

    `published=True` is the unauthenticated path (`/published/{token}/export`).
    It existed as a plain call to this function, so the public export returned
    the owner-shaped payload: internal ids on the story, its characters and its
    locations, every chapter's `beats` (the author's private planning outline),
    and the full lorebook list — all reachable with nothing but a share token.
    The public reader deliberately builds none of that, so "the export is
    narrower than the read" was never true.

    It is now the same projection, via `_published_story_payload`, so the two
    cannot drift: `tests/test_published_story_redaction.py` asserts the rule
    rather than a field list.

    Because `published` is a parameter of a decorated handler, FastAPI exposes it
    as a query parameter on this route (`?published=true`). That is deliberate
    rather than hidden with `include_in_schema=False`: it can only ever *narrow*
    the response, so the worst a caller can do is ask for less, and a parameter
    that is accepted but undocumented is worse than one that is both.
    """
    story = story_repo.get(story_id)
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
    locations = session.exec(
        select(Location).where(Location.id.in_(story.location_ids or []))
    ).all() if story.location_ids else []

    if published:
        # JSON is the default format and the only one whose body is a serialised
        # projection. The others (markdown, epub, pdf, webtoon) render straight
        # from `story`/`chapters` and never emitted `beats`, lorebooks or ids, so
        # they need no gating — but they are reached here too, and a future format
        # branch added below must respect `published`.
        if format == "json":
            return _published_story_payload(story, chapters, characters, locations)

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
                    '''<?xml version="1.0"?>
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
        panel_w, panel_h = _COMIC_PANEL_W, _COMIC_PANEL_H
        margin = _COMIC_MARGIN
        title = story.title or "Untitled Story"

        # Gather real story illustration images (verified on disk) once; chapters
        # without their own images borrow from this pool so panels show art.
        story_asset_paths = _collect_story_illustration_assets(session, story_id)
        asset_cursor = [0]

        for ch in chapters:
            text = ch.content.strip() or ""
            paragraphs = text.split("\n\n") if text else []
            images = _chapter_panel_images(ch, story_asset_paths, asset_cursor)
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
                font = ImageFont.truetype(_COMIC_FONT_PATH, 28)
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
                    except Exception as exc:
                        logger.debug("comic_image_embed_failed", error=str(exc))
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
        webtoon_w = _WEBTOON_W
        margin = _WEBTOON_MARGIN
        title = story.title or "Untitled Story"
        try:
            font = ImageFont.truetype(_COMIC_FONT_PATH, 28)
        except Exception:
            font = ImageFont.load_default()

        story_asset_paths = _collect_story_illustration_assets(session, story_id)
        asset_cursor = [0]

        segments = []
        for ch in chapters:
            text = ch.content.strip() or ""
            paragraphs = text.split("\n\n") if text else []
            images = _chapter_panel_images(ch, story_asset_paths, asset_cursor)
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
        "locations": [
            {
                "id": loc.id,
                "name": loc.name,
                "description": loc.description,
                "atmosphere": loc.atmosphere,
            }
            for loc in locations
        ],
        "chapters": [_serialize_chapter(ch) for ch in chapters],
        "meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "chapter_count": len(chapters),
            "character_count": len(characters),
            "lorebook_count": len(lorebooks),
            "location_count": len(locations),
        },
    }
    return payload


@router.post("/{story_id}/publish", response_model=dict)
def publish_story(story_id: str, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo)):
    """Publish a story and generate a shareable token for public reading."""
    from secrets import token_urlsafe

    story = story_repo.get(story_id)
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
def unpublish_story(story_id: str, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo)):
    """Unpublish a story (revoke its public token)."""
    story = story_repo.get(story_id)
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


def _published_story_payload(
    story: Story,
    chapters: list,
    characters: list,
    locations: list,
) -> dict:
    """The one public projection of a story. Both public routes use it.

    A published token is unauthenticated, so this function is the entire
    redaction boundary: no internal primary keys, no chapter `beats` (the
    author's private planning outline), no lorebooks, and no authoring
    timestamps. The export used to build its own, wider payload — see
    `export_story`'s `published` parameter, which now routes here instead.
    """
    return {
        "story": {
            "id": story.id,
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
        "locations": [
            {"name": l.name, "description": l.description, "atmosphere": l.atmosphere}
            for l in locations
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

    locations = session.exec(
        select(Location).where(Location.id.in_(story.location_ids or []))
    ).all() if story.location_ids else []

    return _published_story_payload(story, chapters, characters, locations)


@router.get("/published/{token}/export")
def export_published_story(token: str, format: str = "json", session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo)):
    """Export a published story by its token (public, read-only).

    Same token, same redaction as `read_published_story` — that is the whole
    point of `published=True` below. It used to return the owner-shaped export
    from an unauthenticated route, which leaked every internal id, each
    chapter's private `beats` outline, and the whole lorebook list.
    """
    story = session.exec(
        select(Story).where(Story.published_token == token, Story.is_published == True)
    ).first()
    if not story:
        raise NotFoundError("PublishedStory", token)

    # `story_repo` is still injected so the two routes resolve dependencies
    # identically; `published=True` makes the export use the public projection.
    return export_story(
        story.id,
        format=format,
        session=session,
        story_repo=story_repo,
        published=True,
    )


@router.put("/{story_id}", response_model=Story)
def update_story(story_id: str, req: UpdateStoryRequest, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo)):
    story = story_repo.get(story_id)
    if not story:
        raise NotFoundError("Story", story_id)
    
    update_data = req.model_dump(exclude_unset=True)
    # `max_agentic_images` belongs here. The chat side has always allowed it, and
    # the story context panel's "Autonomous Illustration" slider is bound to it —
    # without this entry a PUT returns 200 and silently discards the value, so
    # the slider looks inert because it is.
    allowed = {'title', 'description', 'genre', 'character_ids', 'lorebook_ids', 'location_ids', 'llm_model', 'memory', 'scenario_id', 'is_archived', 'max_agentic_depth', 'max_agentic_images', 'max_agentic_narrations', 'persona_id', 'persona_name', 'persona_description', 'temperature', 'top_p', 'max_output_tokens', 'frequency_penalty', 'presence_penalty', 'pov', 'word_count_goal'}
    for key, value in update_data.items():
        if key in allowed:
            setattr(story, key, value)

    # `world_id` is not in `allowed` because it is not a plain setattr: it owns a
    # second column on the World side, and an empty string means detach.
    requested_world_id: str | None | object = _WORLD_ID_UNSET
    if "world_id" in update_data:
        requested_world_id = (update_data.pop("world_id") or "").strip() or None
        require_world(session, requested_world_id)
        link_to_world(session, story, requested_world_id)

    story.updated_at = datetime.now(timezone.utc)
    session.add(story)
    session.commit()
    session.refresh(story)
    return story


class ChapterReorderRequest(BaseModel):
    chapter_ids: list[str]


class ChapterUpdate(BaseModel):
    """A partial chapter update.

    This is deliberately a `BaseModel`, not the `StoryChapter` table model.
    `StoryChapter.model_config` sets `table=True`, and FastAPI skips pydantic
    validation for a SQLModel *table* class, so a PUT body of `{"content":
    "..."}` deserialised into `StoryChapter` left every other field at its
    column default. `beats` in particular defaulted to `[]`, and the guard
    `if chapter_update.beats is not None` then took `[]` as an explicit
    instruction to clear the beat list.

    The story editor autosaves two seconds after every batch of keystrokes, so
    that wiped the beats of any chapter that had them, repeatedly, while the
    user was typing. Nothing errored and nothing was logged.

    Every field is optional and absent means "leave it alone", which is the
    semantics a PATCH/PUT-on-a-partial-resource needs and a table model cannot
    express.

    Every field declared here is applied by `update_chapter`. `title`,
    `chapter_number` and `image_paths` were accepted and dropped: the AI title
    generator fires a real paid LLM job, the editor then PUTs the result, the
    route answered 200, the UI toasted "Title generated!", and the text was
    thrown away. A field in the request model with no assignment is the mirror
    image of the missing-field bug above, and just as silent.
    """

    content: str | None = None
    title: str | None = None
    chapter_number: int | None = None
    beats: list[dict] | None = None
    image_paths: list[str] | None = None


@router.post("/{story_id}/chapters/reorder")
def reorder_chapters(story_id: str, req: ChapterReorderRequest, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo)):
    story = story_repo.get(story_id)
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
def delete_story(story_id: str, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo)):
    story = story_repo.get(story_id)
    if not story:
        raise NotFoundError("Story", story_id)
    
    # Beats, revisions, asset tags and the graph node all go through here, so
    # the chapter cascade stays beside them — `story_beats.chapter_id` and
    # `story_chapter_revisions.story_id` are bare VARCHAR columns with no FK,
    # which is why nothing else would have cleaned them up for us.
    scrub_entity_references(session, "story", story_id)
    chapters = session.exec(select(StoryChapter).where(StoryChapter.story_id == story_id)).all()
    for ch in chapters:
        session.delete(ch)
    session.delete(story)
    session.commit()
    return {"message": "Story deleted"}

@router.get("/{story_id}/chapters", response_model=list[StoryChapter])
def list_chapters(story_id: str, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo)):
    chapters = story_chapter_repo.list_by_story(story_id)
    return chapters

class ChapterCreate(BaseModel):
    """Create body for POST /stories/{id}/chapters.

    `chapter_number` is assigned by the route from the current maximum and
    `story_id` comes from the path, so neither is accepted from the client; the
    route used to take the `StoryChapter` table class and let a caller pin
    either.
    """

    model_config = {"extra": "forbid"}

    title: str | None = None
    content: str
    beats: list[dict[str, Any]] = Field(default_factory=list)
    image_paths: list[str] = Field(default_factory=list)


@router.post("/{story_id}/chapters", response_model=StoryChapter)
def create_chapter(story_id: str, payload: ChapterCreate, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo)):
    story = story_repo.get(story_id)
    if not story:
        raise NotFoundError("Story", story_id)

    chapter = StoryChapter(**payload.model_dump())
    max_chapter = story_chapter_repo.get_max_chapter_number(story_id)
    chapter.chapter_number = max_chapter.chapter_number + 1 if max_chapter else 1
    chapter.story_id = story_id
    chapter.created_at = datetime.now(timezone.utc)
    chapter.updated_at = chapter.created_at
    
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter

@router.get("/{story_id}/chapters/{chapter_id}", response_model=StoryChapter)
def get_chapter(story_id: str, chapter_id: str, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo)):
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)
    _ensure_beat_ids(session, chapter)
    return chapter

@router.put("/{story_id}/chapters/{chapter_id}", response_model=StoryChapter)
def update_chapter(story_id: str, chapter_id: str, chapter_update: ChapterUpdate, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo), story_revision_repo: StoryChapterRevisionRepository = Depends(get_story_revision_repo)):
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)

    if chapter_update.content is not None and chapter_update.content != chapter.content:
        # Through the repository, before the overwrite, so the snapshot records
        # the text the user is replacing. An inline `session.add` here bypassed
        # `MAX_REVISIONS_PER_CHAPTER`, and this is the autosave path: a snapshot
        # is a full copy of the prose and it fires every couple of seconds of
        # typing, so an afternoon of editing accumulated hundreds of full-text
        # snapshots with no cap. Two implementations of "snapshot", only one of
        # which respected the limit.
        story_revision_repo.create_snapshot(chapter, source="manual")
    if chapter_update.content is not None:
        # The prose edit is folded back onto the beats rather than stored beside
        # them. It used to be a plain assignment, and `beats` could arrive in the
        # same request — two uncoordinated writes to the same text, with no rule
        # for which one won. Now the beats are the record and the prose is a
        # render of them, so a manual edit resolves onto a beat by position.
        absorb_prose_edit(chapter, session, chapter_update.content)
    if chapter_update.beats is not None:
        # An explicit beat list from the client wins outright and re-renders the
        # prose, so the two can never disagree after a save.
        write_beats(chapter, session, chapter_update.beats)
    # `title`, `chapter_number` and `image_paths` were declared in the request
    # model and then never assigned: the handler applied only `content` and
    # `beats`, answered 200, and the value was gone. The visible symptom was the
    # AI title generator — a real paid LLM job whose result the editor PUTs, gets
    # a 200 for, and then toasts "Title generated!" about.
    #
    # The model is the contract now: a declared field is applied. `chapter_number`
    # is deliberately not uniqueness-checked here, matching `reorder_chapters`
    # and `create_chapter`; the chapter list orders by it and duplicates are the
    # caller's problem, not something to 400 on mid-autosave.
    if chapter_update.title is not None:
        chapter.title = chapter_update.title
    if chapter_update.chapter_number is not None:
        chapter.chapter_number = chapter_update.chapter_number
    if chapter_update.image_paths is not None:
        chapter.image_paths = chapter_update.image_paths

    chapter.updated_at = datetime.now(timezone.utc)
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter

@router.delete("/{story_id}/chapters/{chapter_id}")
def delete_chapter(story_id: str, chapter_id: str, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo)):
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)
        
    session.exec(
        delete(StoryChapterRevision)
        .where(StoryChapterRevision.chapter_id == chapter_id)
    )
    session.delete(chapter)
    session.commit()
    return {"message": "Chapter deleted"}

@router.post("/{story_id}/chapters/{chapter_id}/continue")
async def continue_story(story_id: str, chapter_id: str, data: StoryContinueRequest, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo)):
    # Appending the user's beat is synchronous session work and the enqueue
    # below is awaited, so the whole prologue runs in a worker thread.
    story, chapter = await asyncio.to_thread(
        _continue_story_prep_sync, session, story_repo, story_chapter_repo, story_id, chapter_id, data.prompt
    )

    job_id = await _enqueue_story_continuation(
        session, story, chapter, directive=data.directive, director_preset=data.director_preset
    )
    return {"job_id": job_id}


def _continue_story_prep_sync(
    session: Session,
    story_repo: StoryRepository,
    story_chapter_repo: StoryChapterRepository,
    story_id: str,
    chapter_id: str,
    prompt: str,
) -> tuple[Story | None, StoryChapter]:
    """Load the chapter (appending the author's beat when given) and its story."""
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)

    story = story_repo.get(story_id)

    if prompt:
        append_beat(chapter, session, role=StoryBeatRole.USER.value, content=prompt)
        session.add(chapter)
        session.commit()
        session.refresh(chapter)
        if story is not None:
            # commit() expired the story's columns; the enqueue helper below
            # reads them from the event loop.
            session.refresh(story)

    return story, chapter


async def _enqueue_story_continuation(
    session: Session,
    story: Story | None,
    chapter: StoryChapter,
    retry_of: str | None = None,
    directive: str | None = None,
    director_preset: str | None = None,
) -> str:
    """Build the story-continue LLM job for a chapter and enqueue it.

    Shared by the continue and retry-last endpoints so both produce an
    identical context assembly (lorebooks, genre, memory, scenario,
    characters, locations) and identical sampler handling — which is why a
    retry's context is the same as a fresh one's: the chapter prose is
    unchanged, only the beat it lands on is not.

    `retry_of` names the beat the result belongs on. Absent, the handler appends
    a new beat; present, it appends an ALTERNATE to that one. The chat equivalent
    is `is_swipe` + `target_message_id` on the job metadata.
    """
    from services.context_builder import build_context

    story_id = chapter.story_id

    # Build story context using the shared context builder so we get
    # semantic lorebook injection, context pruning, and consistent formatting.
    base_prompt = (
        "You are a collaborative AI storyteller. Your task is to continue the story naturally "
        "from the provided text. Maintain the tone and style. Do not include conversational filler "
        "(e.g. 'Sure, here is the continuation:'). Just output the next part of the prose."
    )

    # The premise, the chapter title, and the chapters before this one.
    #
    # All three were absent. `Story.description` is the field the user types at
    # creation and edits in the context panel, and it never reached the model;
    # and there is no `select(StoryChapter).where(story_id == …)` anywhere on
    # this path, so chapter 3 was written from chapter 3's text alone, with
    # chapters 1 and 2 nowhere in the prompt. Earlier chapters are passed as
    # prior assistant turns, which is both the correct role and cheaper than
    # stuffing them into the system prompt.
    story_premise = (story.description or "").strip() if story else ""
    prior_chapters = await asyncio.to_thread(_prior_chapter_messages, session, story_id, chapter.id)

    # The CURRENT chapter goes in as its beats, one turn each, rather than as one
    # `content` blob.
    #
    # This is what beats-as-rows buys. `prune_context` trims from the front of a
    # MESSAGE LIST, so a chapter arriving as a single `{"role": "user",
    # "content": <whole prose>}` message has nothing to trim inside it — a
    # 6,000-word chapter ate the budget regardless of `maxContextTokens`, which
    # is why the plumbing's own comment says `prune_context` "truncated the
    # user's own prose". Sent as turns, the earlier beats are the first to go and
    # the recent ones survive, which is the correct shape.
    #
    # User beats are `user` turns and narrator beats are `assistant` turns, the
    # same split `llm_turn_for` uses, so the model sees the reader's own inputs
    # as its own side of the conversation.
    chapter_turns = [
        {
            "role": "user" if beat.get("role") == StoryBeatRole.USER.value else "assistant",
            "content": beat.get("content") or "",
        }
        for beat in (chapter.beats or [])
        if (beat.get("content") or "").strip()
    ]
    if not chapter_turns:
        # A chapter with content but NO beats — an imported one, a chapter made by
        # `create_chapter` with text and never continued. Its prose is the whole
        # input and there are no rows to say it, so it goes in as the one user turn
        # it always was.
        #
        # Dropping it instead would send a continuation built from the previous
        # chapters alone, which is a silent quality regression on exactly the
        # chapters a user has not asked the AI to write yet.
        chapter_turns = [{"role": "user", "content": chapter.content.strip()}]
    messages = [
        *[{"role": "assistant", "content": text} for text in prior_chapters],
        *[t for t in chapter_turns if t["content"]],
    ]

    DIRECTOR_PRESETS = {
        "conflict": "Introduce an immediate complication, obstacle, or dramatic plot twist that raises the stakes.",
        "atmosphere": "Deepen the sensory atmosphere, physical textures, lighting, weather, and environmental mood.",
        "dialogue": "Focus on an intense, nuanced dialogue exchange with character subtext and emotional undercurrents.",
        "action": "Escalate into visceral, fast-paced kinetic action, physical momentum, and urgent peril.",
        "introspection": "Reveal intimate internal thoughts, private doubts, and emotional revelations from the character's perspective.",
    }

    directive_text = (directive or "").strip()
    if director_preset and director_preset in DIRECTOR_PRESETS:
        preset_text = DIRECTOR_PRESETS[director_preset]
        directive_text = f"{preset_text} {directive_text}".strip()

    if directive_text:
        messages.append({
            "role": "system",
            "content": f"[Director's Guidance]\n{directive_text}\nFollow this guidance strictly while continuing the narrative naturally.",
        })

    if story_premise:
        base_prompt = f"{base_prompt}\n\n[Story premise]\n{story_premise}"

    # Context tokens come from a pure config read, no session needed.
    context_tokens = await asyncio.to_thread(_resolve_context_tokens)

    # One assembly through the unified context builder. `story_context_kwargs`
    # resolves persona (library row fills blanks), world membership
    # (lorebooks, locations, scenario), and the story's own writing preferences
    # from the Story row — no per-field manual resolution needed here.
    system_prompt, context, _sections = await asyncio.to_thread(
        build_context, session, "story", story, messages,
        include_roleplay_default=False,
        max_context_tokens=context_tokens,
        system_prompt_override=base_prompt,
    )

    # Story agentic mode: offer the story-safe toolset so the model can
    # illustrate its own scenes.
    #
    # The gate used to be `max_agentic_depth > 0`, which is the LLM hop cap —
    # the number of times the model may think, not the number of images it may
    # spend. For stories the toolset is `generate_image` ONLY, so "agentic" and
    # "autonomous illustration" are the same feature, and it has to be gated on
    # the image budget rather than on the hop cap. Otherwise the context panel's
    # "Autonomous Illustration → 0 (Off)" slider does nothing: the tools are
    # still attached, the budget is still the default 2, and the model keeps
    # illustrating.
    from services.orchestrator_service import (
        budget_metadata_for,
        get_tool_max,
        story_agentic_tools,
    )

    # The story toolset is `generate_image` only, so "agentic" for a story IS
    # "autonomous illustration", and it has to be gated on the image budget
    # rather than on the depth cap — the LLM hop count. Otherwise the context
    # panel's "Autonomous Illustration -> 0 (Off)" slider does nothing: the tools
    # are still attached and the default budget still applies.
    story_image_budget = (
        get_tool_max("generate_image", story)
        if story is not None
        else 0
    )
    story_tools: list[dict] = []
    story_agentic = story_image_budget > 0 and bool(story and (story.max_agentic_depth or 0) > 0)
    if story_agentic:
        story_tools = story_agentic_tools()

    workflow, metadata = build_llm_workflow(
        messages=context,
        type_="story_continue",
        story_id=story_id,
        chapter_id=chapter.id,
        model=_model_for_kind("story_continue", story.llm_model if story else None, session),
        workspace="story",
        samplers=sampler_overrides(story),
        # Always carried when there is a story, not conditional on the depth cap
        # being set. Each budget has its own unset value, and the orchestrator
        # needs to see the key to know whether it was configured at all — this is
        # what lets a story's own cap survive past the first hop.
        extra_metadata={
            "agentic": story_agentic,
            "max_agentic_depth": story.max_agentic_depth,
            # Which beat this take belongs on. A retry's context is identical to
            # a fresh continuation's, so this is the only thing that distinguishes
            # them, and it is what makes the alternates additive rather than a
            # replacement.
            "retry_of": retry_of,
            **budget_metadata_for(story),
        } if story is not None else None,
    )
    if story_tools:
        workflow["tools"] = story_tools
    job = await submit_llm_job(
        session,
        workflow,
        metadata,
    )

    return job.id


# How much of the preceding chapters to carry. Bounded because the whole thing
# lands in a paid prompt: the builder's own `max_context_tokens` prunes after the
# fact, but a chapter is potentially the user's most expensive input, so the
# window is set here too and the budget argument still governs.
PRIOR_CHAPTER_LIMIT = 4
PRIOR_CHAPTER_CHARS = 4000


def _prior_chapter_messages(
    session: Session, story_id: str, before_chapter_id: str
) -> list[str]:
    """The chapters before `before_chapter_id`, oldest first.

    Ordered by chapter number rather than `created_at` so a branched or
    reordered chapter list still produces a coherent prior context, and bounded
    in both count and length.
    """
    from sqlmodel import select

    prior = session.exec(
        select(StoryChapter)
        .where(StoryChapter.story_id == story_id)
        .order_by(StoryChapter.chapter_number)
        .limit(PRIOR_CHAPTER_LIMIT)
    ).all()
    texts: list[str] = []
    for prior_chapter in prior:
        if prior_chapter.id == before_chapter_id:
            break
        text = (prior_chapter.content or "").strip()
        if text:
            texts.append(text[-PRIOR_CHAPTER_CHARS:])
    return texts


def _world_prompt_parts(session: Session, story) -> dict | None:
    """The owning World's contribution to a story's prompt, read off the loop.

    Its lorebooks and locations come from the members' own `world_id`, not from
    id arrays on the `worlds` row — see `context_builder._world_contribution`.
    """
    from core.entities import World

    world = session.get(World, story.world_id)
    if world is None:
        return None
    from services.world_ownership import members_of, world_scenario

    scenario = world_scenario(session, world.id)
    return {
        "name": world.name,
        "description": world.description,
        "lorebook_ids": [b.id for b in members_of(session, world.id, Lorebook)],
        "location_ids": [l.id for l in members_of(session, world.id, Location)],
        "scenario": (scenario.prompt_template if scenario is not None else None) or None,
    }


def _resolve_context_tokens() -> int:
    """A story continuation's context budget.

    `Story` has no per-story override (unlike `Chat.max_context_tokens`), so
    this is the global `ai.maxContextTokens` — the same value every chat reply
    path resolves. The important part is that it is resolved at all: unpassed,
    `build_chat_context` fell back to `DEFAULT_MAX_TOKENS` (4096) and then
    truncated the user's own prose to make room.
    """
    from config import get_config
    from services.context_builder import DEFAULT_MAX_TOKENS

    configured = (get_config() or {}).get("ai", {}).get("maxContextTokens")
    try:
        return int(configured) if configured else DEFAULT_MAX_TOKENS
    except (TypeError, ValueError):
        return DEFAULT_MAX_TOKENS


def _scenario_prompt_template(session: Session, scenario_id: str) -> str | None:
    """A scenario's prompt template, read off the event loop."""
    scenario = session.get(Scenario, scenario_id)
    if scenario and scenario.prompt_template:
        return scenario.prompt_template
    return None


@router.post("/{story_id}/chapters/{chapter_id}/discover-worldbuilding")
def discover_chapter_worldbuilding(
    story_id: str,
    chapter_id: str,
    session: Session = Depends(get_session),
    story_repo: StoryRepository = Depends(get_story_repo),
    story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo),
):
    """Scan the chapter text and beats for novel worldbuilding entities."""
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter:
        raise NotFoundError("StoryChapter", chapter_id)
    story = story_repo.get(story_id)

    # Gather known names
    existing_names: set[str] = set()
    if story:
        if story.world_id:
            from core.entities import Character, Location, Lorebook
            from services.world_ownership import members_of

            for loc in members_of(session, story.world_id, Location):
                existing_names.add(loc.name)
            for char in members_of(session, story.world_id, Character):
                existing_names.add(char.name)
            for lb in members_of(session, story.world_id, Lorebook):
                for entry in lb.entries:
                    for k in entry.keys:
                        existing_names.add(k)
        for cid in story.character_ids or []:
            from core.entities import Character
            c = session.get(Character, cid)
            if c:
                existing_names.add(c.name)

    # Combine chapter text
    text_parts = [chapter.content or ""]
    for beat in chapter.beats or []:
        if isinstance(beat, dict) and beat.get("content"):
            text_parts.append(beat["content"])
    full_text = "\n\n".join(text_parts)

    from services.world_discovery import extract_world_entities
    discoveries = extract_world_entities(full_text, existing_names=existing_names)
    return {"discoveries": discoveries, "chapter_id": chapter_id, "story_id": story_id}


@router.post("/{story_id}/adopt-worldbuilding")
def adopt_worldbuilding_entity(
    story_id: str,
    data: AdoptWorldbuildingRequest,
    session: Session = Depends(get_session),
    story_repo: StoryRepository = Depends(get_story_repo),
):
    """Adopt an extracted discovery into the World Vault as a Location or LorebookEntry."""
    story = story_repo.get(story_id)
    if not story:
        raise NotFoundError("Story", story_id)

    target_world_id = data.world_id or story.world_id

    from services.embedding_service import EmbeddingService
    emb_svc = EmbeddingService()

    if data.target_action == "create_location":
        from core.entities import Location
        loc = Location(
            name=data.name,
            description=data.summary,
            atmosphere=data.summary if len(data.summary) > 20 else None,
            tags=data.tags or ["discovered", "location"],
            world_id=target_world_id,
        )
        session.add(loc)
        session.commit()
        session.refresh(loc)
        return {"status": "created", "entity_type": "location", "entity_id": loc.id, "name": loc.name}
    else:
        from core.entities import Lorebook, LorebookEntry
        target_lb_id = data.lorebook_id
        if not target_lb_id and target_world_id:
            from services.world_ownership import members_of
            existing_lbs = members_of(session, target_world_id, Lorebook)
            if existing_lbs:
                target_lb_id = existing_lbs[0].id
        if not target_lb_id:
            lb = Lorebook(
                name=f"{story.title or 'Story'} Worldbook",
                description=f"Auto-collected lore for {story.title or 'story'}",
                world_id=target_world_id,
            )
            session.add(lb)
            session.commit()
            session.refresh(lb)
            target_lb_id = lb.id
            if story and not story.lorebook_ids:
                story.lorebook_ids = [lb.id]
                session.add(story)
                session.commit()

        embedding = emb_svc.generate_embedding(f"{data.name}: {data.summary}")
        entry = LorebookEntry(
            lorebook_id=target_lb_id,
            keys=[data.name],
            content=data.summary or f"{data.name} is a known {data.category} in the world.",
            category=data.category,
            tags=data.tags or ["discovered"],
            embedding=embedding,
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return {"status": "created", "entity_type": "lorebook_entry", "entity_id": entry.id, "name": data.name, "lorebook_id": target_lb_id}



_ACTION_PROMPTS = {
    "rewrite": (
        "You are a skilled fiction editor. Rewrite the provided passage according to the "
        "author's directive (if any). Preserve the author's voice, tense, POV, and the "
        "surrounding story's continuity. Match the surrounding prose style. Output ONLY the "
        "rewritten prose — no preamble, no quotes, no commentary."
    ),
    "expand": (
        "You are a skilled fiction writer. Expand the provided passage with richer detail — "
        "sensory description, character interiority, pacing beats — roughly doubling its length. "
        "Respect any author's directive. Preserve the author's voice, tense, POV, and continuity "
        "with the surrounding story. Output ONLY the expanded prose — no preamble, no quotes."
    ),
    "summarize": (
        "You are a concise story analyst. Summarize the provided story text into a tight synopsis "
        "(at most 150 words) capturing key events, characters, and outcome. Output ONLY the "
        "summary prose — no preamble, no bullet points unless asked."
    ),
}


@router.post("/{story_id}/chapters/{chapter_id}/ai-action")
async def story_ai_action(story_id: str, chapter_id: str, data: StoryActionRequest, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo)):
    """Run a targeted AI editing action (rewrite/expand/summarize).

    Unlike continue, the result is NOT persisted into the chapter — it is
    returned to the client via the completed job's output so the author can
    preview and apply/discard it in the editor.
    """
    action = data.action
    if action not in _ACTION_PROMPTS:
        raise ValidationError(f"action must be one of: {', '.join(sorted(_ACTION_PROMPTS))}")
    target_text = data.target_text.strip()
    if not target_text:
        raise ValidationError("target_text is required")

    # Only the context build and the job enqueue below are awaited, so the
    # chapter/story reads move to a worker thread.
    story, chapter = await asyncio.to_thread(
        _story_chapter_pair_sync, story_repo, story_chapter_repo, story_id, chapter_id
    )

    directive = data.directive.strip()
    directive_line = f"\n\nAuthor's directive: {directive}" if directive else ""

    # Give targeted edits a window of surrounding prose for continuity.
    context_tail = ""
    full_text = (chapter.content or "").strip()
    if action in ("rewrite", "expand") and full_text:
        pos = full_text.find(target_text)
        if pos > 0:
            before = full_text[max(0, pos - 1200):pos]
            after = full_text[pos + len(target_text):][:400]
            context_tail = (
                "Surrounding story (for continuity only, do NOT repeat it):\n"
                f"---\n{before}[...]{after}\n---\n\n"
            )

    user_content = (
        f"{context_tail}Passage to {action}:{directive_line}\n\n{target_text}"
        if action != "summarize"
        else f"{directive_line}\n\n{target_text}".strip()
    )

    from config import get_system_prompt_blocks
    blocks = get_system_prompt_blocks() or {}
    action_prompt = blocks.get(f"story_action_{action}") or _ACTION_PROMPTS[action]

    from services.context_builder import build_context
    system_prompt, context, _sections = await asyncio.to_thread(
        build_context, session, "story", story,
        [{"role": "user", "content": user_content}],
        system_prompt_override=action_prompt,
    )

    workflow, metadata = build_llm_workflow(
        messages=context,
        type_="story_action",
        story_id=story_id,
        chapter_id=chapter_id,
        model=_model_for_kind("story_action", story.llm_model if story else None, session),
        workspace="story",
        samplers=sampler_overrides(story),
    )
    job = await submit_llm_job(session, workflow, metadata)
    return {"job_id": job.id}


@router.post("/{story_id}/chapters/{chapter_id}/retry-last")
async def retry_last_continuation(story_id: str, chapter_id: str, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo), story_revision_repo: StoryChapterRevisionRepository = Depends(get_story_revision_repo)):
    """Ask for a second take of the last AI continuation, keeping the first.

    It used to DROP the beat and enqueue, so a continuation you merely wanted
    another opinion on was gone the moment you asked for one — and the only way
    back was a revision snapshot that rewound the whole chapter. The take now
    lands in `alternates` beside it, which is what a chat swipe has always done.

    The snapshot is still taken: it is what rewinds the chapter to before the
    retry, which is a different thing from undoing one take.
    """
    story, chapter, retry_of = await asyncio.to_thread(
        _retry_last_prep_sync,
        session,
        story_repo,
        story_chapter_repo,
        story_revision_repo,
        story_id,
        chapter_id,
    )

    job_id = await _enqueue_story_continuation(
        session, story, chapter, retry_of=retry_of
    )
    return {"job_id": job_id}


def _story_chapter_pair_sync(
    story_repo: StoryRepository,
    story_chapter_repo: StoryChapterRepository,
    story_id: str,
    chapter_id: str,
) -> tuple[Story | None, StoryChapter]:
    """Load a story and one of its chapters, off the event loop."""
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)
    return story_repo.get(story_id), chapter


def _retry_last_prep_sync(
    session: Session,
    story_repo: StoryRepository,
    story_chapter_repo: StoryChapterRepository,
    story_revision_repo: StoryChapterRevisionRepository,
    story_id: str,
    chapter_id: str,
) -> tuple[Story | None, StoryChapter, str]:
    """Load the chapter and hand back the beat a retry should replace.

    Synchronous for the same reason the other preps are: the requeue is awaited,
    so the route stays `async def` and these reads would otherwise run on the
    event loop.
    """
    story, chapter = _story_chapter_pair_sync(
        story_repo, story_chapter_repo, story_id, chapter_id
    )

    _ensure_beat_ids(session, chapter)
    beats = list(chapter.beats or [])
    # The last *prose* beat, not simply the last beat. A narrated chapter ends in
    # a `TTS_BEAT_ROLE` attachment, which is an audio file reference with empty
    # `content` — retrying has to find the narrator turn under it, and dropping
    # that turn has to drop the attachment with it (it describes the audio of the
    # text being removed).
    last_index = next(
        (
            i
            for i in range(len(beats) - 1, -1, -1)
            if isinstance(beats[i], dict) and beats[i].get("role") == StoryBeatRole.NARRATOR.value
        ),
        -1,
    )
    if last_index < 0:
        raise ValidationError("No AI continuation to retry — the latest beat is not an AI-generated one")

    # Snapshot before the requeue, same as before — but the beat is NOT trimmed.
    # Retry used to drop it and re-enqueue, so a continuation you only wanted a
    # second opinion on was destroyed the moment you asked. The take now lands in
    # `alternates` beside it, and the snapshot is what still lets you rewind the
    # whole chapter to before you started retrying.
    story_revision_repo.create_snapshot(chapter, source="pre_retry")

    # The anchor the new take replaces, handed to the handler as `retry_of`.
    retry_of = beats[last_index].get("id")

    chapter.updated_at = datetime.now(timezone.utc)
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    if story is not None:
        # commit() expired the story's columns; the enqueue helper below reads
        # them from the event loop.
        session.refresh(story)
    return story, chapter, retry_of


def _revision_out(revision: StoryChapterRevision) -> dict:
    preview = (revision.content or "").strip()
    if len(preview) > 160:
        preview = preview[:160].rstrip() + "…"
    return {
        "id": revision.id,
        "chapter_id": revision.chapter_id,
        "story_id": revision.story_id,
        "source": revision.source,
        "word_count": revision.word_count,
        "created_at": revision.created_at.isoformat() if revision.created_at else None,
        "preview": preview,
    }


class RevisionCreateRequest(BaseModel):
    source: str | None = None


@router.get("/{story_id}/chapters/{chapter_id}/revisions")
def list_chapter_revisions(story_id: str, chapter_id: str, session: Session = Depends(get_session), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo), story_revision_repo: StoryChapterRevisionRepository = Depends(get_story_revision_repo)):
    """List snapshot history for a chapter (newest first)."""
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)
    return [_revision_out(r) for r in story_revision_repo.list_for_chapter(chapter_id)]


@router.post("/{story_id}/chapters/{chapter_id}/revisions")
def create_chapter_revision(story_id: str, chapter_id: str, data: RevisionCreateRequest | None = None, session: Session = Depends(get_session), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo), story_revision_repo: StoryChapterRevisionRepository = Depends(get_story_revision_repo)):
    """Manually snapshot the chapter's current prose."""
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)
    if data is not None and data.source and data.source != "manual":
        raise ValidationError("Only manual snapshots can be created from the API")
    revision = story_revision_repo.create_snapshot(chapter, source="manual")
    session.add(revision)
    session.commit()
    session.refresh(revision)
    return _revision_out(revision)


@router.post("/{story_id}/chapters/{chapter_id}/revisions/{revision_id}/restore", response_model=StoryChapter)
def restore_chapter_revision(story_id: str, chapter_id: str, revision_id: str, session: Session = Depends(get_session), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo), story_revision_repo: StoryChapterRevisionRepository = Depends(get_story_revision_repo)):
    """Restore a chapter's prose, and its beat list with it, from a snapshot.

    The current chapter is snapshotted first (source 'pre_restore') so the
    restore itself is undoable.

    Used to rewrite `content` and leave `beats` untouched, on the reasoning that
    beats describe turn structure rather than the restored text. That is exactly
    backwards under this module's model — the prose IS the beat list rendered,
    so a restore that changed one and not the other left the chapter in the
    state the beat list exists to prevent, and the next beat edit failed to find
    its text in the chapter. A snapshot now carries both and the restore rewinds
    both, re-rendering the prose from the restored beats.

    A snapshot taken before this column existed has no beats; restoring one
    rewinds the prose and leaves the beats as they were, which is what it did
    before.
    """
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)
    revision = story_revision_repo.get(revision_id, story_id)
    if not revision or revision.chapter_id != chapter_id:
        raise NotFoundError("StoryChapterRevision", revision_id)

    story_revision_repo.create_snapshot(chapter, source="pre_restore")
    chapter.content = revision.content
    if revision.beats:
        write_beats(chapter, session, [dict(b) for b in revision.beats if isinstance(b, dict)])
    chapter.updated_at = datetime.now(timezone.utc)
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter

@router.post("/{story_id}/chapters/{chapter_id}/beats")
def add_beat(story_id: str, chapter_id: str, data: StoryBeatRequest, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo)):
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)
        
    content = data.content
    role = data.role

    if not content.strip():
        raise ValidationError("Beat content cannot be empty")
    if role not in _ALLOWED_BEAT_ROLES:
        raise ValidationError(f"role must be one of {sorted(_ALLOWED_BEAT_ROLES)}")

    append_beat(chapter, session, role=role, content=content)
    chapter.updated_at = datetime.now(timezone.utc)
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter


def _beat_snippet(content: str, role: str) -> str:
    """The exact text a beat contributes to the flat chapter prose."""
    if role == StoryBeatRole.USER.value:
        return f"\n\n> {content}\n\n"
    return f"\n\n{content}\n\n"


def render_beats(beats: list[dict[str, Any]] | None) -> str:
    """The prose the beat list denotes. The one definition of `chapter.content`."""
    return "".join(
        _beat_snippet(
            (b.get("content") if isinstance(b, dict) else "") or "",
            (b.get("role") if isinstance(b, dict) else None) or StoryBeatRole.NARRATOR.value,
        )
        for b in (beats or [])
    )


def beats_are_renderable(beats: list[dict[str, Any]] | None) -> bool:
    """Can `render_beats` reproduce this chapter's prose?

    False when a beat has no `content` key at all — a shape only very old rows
    have, since every writer includes it (TTS beats carry `""` deliberately).
    For those, rendering would drop the beat's text on the floor, so the caller
    must keep the existing prose rather than recompute it. This is the one case
    where the beat list is NOT the record, and it is a migration concern, not a
    design one.
    """
    return all(
        ("content" in b) for b in (beats or []) if isinstance(b, dict)
    ) and all(isinstance(b, dict) for b in (beats or []))


def sync_chapter_prose(chapter: StoryChapter) -> bool:
    """Recompute `chapter.content` from `chapter.beats`.

    The single owner of that field. Every path that mutates the beat list calls
    this; no path concatenates onto the string by hand. It used to be
    `chapter.content += ...` at each of four sites, each with its own separator
    convention, and the three `_replace_beat_text` / `_remove_beat_text`
    splices existed to undo the damage when the two drifted — which they did,
    because the user can edit the prose in the editor and nothing told the beats.

    Returns False when the beats cannot be rendered (see `beats_are_renderable`),
    in which case `content` is left untouched and the caller appends instead.
    """
    beats = chapter.beats or []
    if not beats_are_renderable(beats):
        logger.warning(
            "chapter_beats_not_renderable",
            chapter_id=chapter.id,
            beat_count=len(beats),
        )
        return False
    chapter.content = render_beats(beats)
    return True


def _beat_ranges(
    beats: list[dict[str, Any]],
) -> list[tuple[int, int, int, int]]:
    """Where each beat sits in the rendered prose, as four coordinates.

    `(snippet_start, content_start, content_end, snippet_end)`.

    The content coordinates are the point: a beat's snippet is
    `"\n\n"` + (`"> "` for a user beat) + content + `"\n\n"`, so an offset in
    the prose is NOT an offset in the beat's own text. Splicing with the snippet
    span alone silently includes the separators in the edit, which is what
    produced a beat reading `"The door opswung wids"` out of a one-word
    substitution.
    """
    spans: list[tuple[int, int, int, int]] = []
    pos = 0
    for b in beats:
        role = b.get("role") or StoryBeatRole.NARRATOR.value
        content = b.get("content") or ""
        lead = 2 + (2 if role == StoryBeatRole.USER.value else 0)
        content_start = pos + lead
        content_end = content_start + len(content)
        snippet_end = content_end + 2
        spans.append((pos, content_start, content_end, snippet_end))
        pos = snippet_end
    return spans


def _beat_index_owning(spans: list[tuple[int, int, int, int]], pos: int) -> int:
    """The beat that owns `pos` in the rendered prose.

    A position in a separator between two beats belongs to the PRECEDING beat, so
    typing at the very end of the chapter appends to the last beat rather than
    creating an off-by-one insertion before it.
    """
    for idx, (_snip_start, _content_start, _content_end, snip_end) in enumerate(spans):
        if _snip_start <= pos < snip_end:
            return idx
    return max(0, len(spans) - 1)


# Above this size the differing region is not diffed. `SequenceMatcher` is
# quadratic in the worst case and this runs on every autosave, so a pathological
# edit shape degrades to the coarse rule below rather than blocking the request.
_DIFF_BUDGET = 4000


def _edit_spans(old: str, new: str) -> list[tuple[int, int, int, int]]:
    """Every contiguous region that differs, as a list of (i1, i2, j1, j2).

    Trimmed by the common prefix and suffix first, which is exact for one
    contiguous edit — what a debounced keystroke batch produces — and O(n).

    The trimmed region is then diffed, because a single save is not always a
    single edit: the editor can flush several, and collapsing them into one span
    would splice text into beats the user never touched. Each span is applied on
    its own, so disjoint edits land in disjoint beats.
    """
    limit = min(len(old), len(new))
    prefix = 0
    while prefix < limit and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < limit - prefix
        and old[len(old) - 1 - suffix] == new[len(new) - 1 - suffix]
    ):
        suffix += 1
    i1, i2 = prefix, len(old) - suffix
    j1, j2 = prefix, len(new) - suffix
    if i1 == i2 and j1 == j2:
        return []
    if len(old[i1:i2]) > _DIFF_BUDGET or len(new[j1:j2]) > _DIFF_BUDGET:
        return [(i1, i2, j1, j2)]

    # Offset the opcodes back into the full strings.
    matcher = difflib.SequenceMatcher(None, old[i1:i2], new[j1:j2], autojunk=False)
    return [
        (i1 + a1, i1 + a2, j1 + b1, j1 + b2)
        for tag, a1, a2, b1, b2 in matcher.get_opcodes()
        if tag != "equal"
    ]


def absorb_prose_edit(chapter: StoryChapter, session: Session, new_content: str) -> None:
    """Fold a manual edit of `chapter.content` back onto the beats.

    This is the whole point of making beats authoritative. The editor is one
    flat textarea and the user types in it, so the prose is still where the
    writing happens — what changes is that the edit now has to resolve onto a
    beat instead of leaving the two lists disagreeing.

    Before this, a manual edit and a beat edit were two uncoordinated writes to
    the same text, and the cost landed later and away from the cause: edit a
    paragraph by hand, then try to delete the beat it came from, and
    `_replace_beat_text` returns None and the request 400s with "Beat text no
    longer matches the chapter prose" — with the beats panel's edit and delete
    affordances now permanently unusable for that chapter and no path back.

    The alignment is positional and total: find the region that changed in the
    old prose, splice the new text into the beat that owns the start of it, and
    delete the beats wholly consumed. Text in beats the user did not touch is
    byte-identical afterwards.
    """
    beats = [dict(b) for b in (chapter.beats or []) if isinstance(b, dict)]
    old = render_beats(beats)
    # Read BEFORE the assign below, which is the whole point of the guard: this is
    # the prose the server last wrote, and it is the only baseline an edit can be
    # located against.
    stored = chapter.content or ""
    chapter.content = new_content
    if old == new_content or not beats:
        return
    if not beats_are_renderable(beats):
        # A beat with no `content` key at all: rendering would drop its text, so
        # the prose stays and the beat list stays as it is. This is the one shape
        # where the beats are not the record, and it is a migration concern.
        return
    if stored != old:
        # The chapter was ALREADY inconsistent before this edit arrived — its
        # stored prose was not the render of its own beats. Folding an edit into
        # that would splice text into beats at positions derived from text they
        # never produced, and a short accidental match in `SequenceMatcher` is
        # enough to corrupt a beat. The prose wins, the beats are left as they
        # were, and it is logged: reachable from a restore of a pre-`092`
        # snapshot, which rewinds `content` with no beats to rewind with it.
        logger.warning(
            "chapter_prose_beats_drifted",
            chapter_id=chapter.id,
            rendered_len=len(old),
            stored_len=len(stored),
        )
        return

    spans = _beat_ranges(beats)
    edits = _edit_spans(old, new_content)

    # Pass 0 — a pure insertion sitting exactly on a beat boundary is a NEW beat,
    # not more text in the previous one.
    #
    # Typing at the end of the chapter is the single most common edit, and folding
    # it into the last beat is both wrong as a turn log and unrepresentable: the
    # user's text has the beat separator plus their own blank line where the
    # render only has one separator, so the fold would silently drop a newline.
    # As a new beat it round-trips exactly.
    insertions: list[tuple[int, dict[str, Any]]] = []
    remaining: list[tuple[int, int, int, int]] = []
    for i1, i2, j1, j2 in edits:
        boundary = None
        if i1 == i2:
            boundary = next(
                (idx for idx, span in enumerate(spans) if span[3] == i1 and i1 > 0),
                None,
            )
        if boundary is not None:
            text = new_content[j1:j2]
            # A beat's own separators are part of the render, not of its text.
            if text.startswith("\n\n"):
                text = text[2:]
            if text.endswith("\n\n"):
                text = text[:-2]
            role = StoryBeatRole.NARRATOR.value
            if text.startswith("> "):
                role, text = StoryBeatRole.USER.value, text[2:]
            if text:
                insertions.append(
                    (
                        boundary + 1,
                        {"role": role, "content": text},
                    )
                )
            continue
        remaining.append((i1, i2, j1, j2))

    # Pass 1 — plan every splice against the ORIGINAL text.
    #
    # This has to be a separate pass from applying them, and it is the kind of
    # ordering that is invisible until it breaks: a single keystroke batch can
    # land as several `SequenceMatcher` opcodes inside one beat, and applying
    # each immediately means the next one reads the already-mutated string. The
    # offsets are only valid against the text the spans were computed from, so
    # every offset is derived first and applied after.
    planned: dict[int, list[tuple[int, int, str]]] = {}
    for i1, i2, j1, j2 in remaining:
        first = _beat_index_owning(spans, i1)
        last = _beat_index_owning(spans, max(i1, i2 - 1)) if i2 > i1 else first
        for idx in range(first, last + 1):
            _snip_start, content_start, content_end, _snip_end = spans[idx]
            # Clamped to the beat's own text, so a region that starts inside this
            # beat and ends inside the next one takes only this beat's part.
            # Both ends need clamping on BOTH sides: a pure insertion at the very
            # end of a chapter positions `i1` past the beat's content, and an
            # unclamped `lo` would splice at len(content)+1, duplicating the
            # tail of the text.
            lo = min(max(i1, content_start), content_end) - content_start
            hi = min(max(i2, content_start), content_end) - content_start
            # Only the beat at the START of the region receives the new text; the
            # ones wholly inside it are emptied, and the filter below drops them.
            replacement = new_content[j1:j2] if idx == first else ""
            planned.setdefault(idx, []).append((lo, hi, replacement))

    # Pass 2 — apply, right-to-left within each beat, so an earlier splice never
    # shifts a later one's offsets.
    for idx, ops in planned.items():
        if idx >= len(beats):
            continue
        text = beats[idx].get("content") or ""
        for lo, hi, replacement in sorted(ops, reverse=True):
            text = text[:lo] + replacement + text[hi:]
        beats[idx]["content"] = text

    # A beat whose content went empty still owns its separators, which would
    # render as a stray blank line. Keep it only if it carries state a render
    # cannot reproduce — audio is the case (a TTS beat's content is `""`).
    beats = [
        b for b in beats
        if (b.get("content") or "").strip() or b.get("audio_path")
    ]

    # Apply insertions back-to-front so earlier positions stay valid.
    for at, beat in sorted(insertions, reverse=True):
        beats.insert(min(at, len(beats)), {**beat, "id": str(uuid4()), "parent_beat_id": None})

    rendered = render_beats(beats)

    # Verify before committing. The prose is the user's text and `absorb` has no
    # licence to change it: if the fold does not reproduce exactly what was typed,
    # the beats are left as they were and the prose is kept.
    #
    # This is reachable, and not only from pathological input. Deleting a whole
    # paragraph is the obvious case: the minimal diff between the old and new text
    # matches the deleted paragraph's words inside the replacement, so the edit
    # is expressed as an insertion into the preceding beat and the beat that was
    # deleted survives as a stale duplicate. The beat list cannot represent the
    # edit without knowing which of the two copies the user meant, and guessing
    # would silently change their text.
    # Compared with the trailing separators ignored: a chapter always ends in the
    # last beat's separator, so the render can never reproduce a text that does
    # not, and that single normalisation is the only systematic difference.
    # Everything interior still has to match exactly.
    if rendered.rstrip("\n") != new_content.rstrip("\n"):

        # `beats` is a working copy and is discarded. Assigning it here would
        # store a spliced beat list that does not match the prose — the very
        # state this function exists to prevent.
        logger.warning(
            "chapter_prose_edit_not_foldable",
            chapter_id=chapter.id,
            beat_count=len(beats),
        )
        chapter.content = new_content
        return

    # The canonical render, not the text as typed, so the invariant holds for the
    # next edit: the only difference is the trailing separator a chapter always
    # carries, which is invisible in the editor and normalised on save.
    # Pushed to rows, so `chapter.beats` is a render of the rows rather than a
    # second copy the two can drift between.
    write_beats(chapter, session, beats)


# ── beats as rows ───────────────────────────────────────────────────────────
#
# A beat is a `story_beats` row now. `story_chapters.beats` remains the JSON the
# API and the editor speak, and `_sync_from_rows` is the ONE place both are
# produced from the same source — which is what makes them unable to disagree.
# Every write below goes through the repository and then through this.
#
# The reason for the shape at all: beats were a JSON array on the chapter, and
# keeping that array in step with `chapter.content` (the prose they render to)
# was a set of hand-written splices. See `infrastructure/repositories/story_beat_repo.py`
# for what that cost.

def _row_to_beat_dict(row) -> dict[str, Any]:
    from infrastructure.repositories.story_beat_repo import _row_to_dict

    return _row_to_dict(row)


def _beat_repo(session: Session):
    from infrastructure.repositories.story_beat_repo import StoryBeatRepository

    return StoryBeatRepository(session)


def write_beats(chapter: StoryChapter, session: Session, beats: list[dict]) -> list[dict]:
    """Push a whole beat list to its rows, then re-render the prose.

    The bridge for the paths that work on the JSON list — `absorb_prose_edit`,
    beat edit/delete, reorder, propagate. They are position-aware over a rendered
    string and rewriting them as row operations would be a rewrite of logic that
    is now well tested; pushing the RESULT to rows keeps that logic and makes the
    rows the source of truth afterwards.

    Delete-then-insert, which is safe here because every caller holds a complete
    new list and the insert is within the same transaction.
    """
    repo = _beat_repo(session)
    repo.replace_all(chapter.id, beats)
    return sync_from_rows(chapter, session)


def sync_from_rows(chapter: StoryChapter, session: Session) -> list[dict]:
    """Rebuild `chapter.beats` from its rows, then re-render the prose.

    The single writer of both fields. `chapter.beats` is the JSON the API and
    the editor have always spoken; the rows are the source. Producing both here,
    from one read of the rows, is what makes the two unable to describe
    different text — the failure that produced `absorb_prose_edit`.

    Returns the rebuilt list so a caller can hold the beat it just wrote without
    re-reading it.
    """
    beats = _beat_repo(session).list_by_chapter(chapter.id)
    chapter.beats = beats
    sync_chapter_prose(chapter)
    return beats


def append_beat(
    chapter: StoryChapter,
    session: Session,
    *,
    role: str,
    content: str,
    source_job_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Add a beat to the end of a chapter and re-render the prose.

    The only writer of a beat onto a chapter, used by both the HTTP routes and
    the job handler in `world_integration_service` — so an AI continuation and a
    hand-entered beat are the same operation by construction rather than by two
    implementations that happen to agree today.

    `source_job_id` is stamped on the beat when the beat is the artefact of a
    paid job: it is what makes a redelivered JOB_COMPLETED a no-op and what the
    reconciler searches for, the story counterpart of
    `Message.message_metadata["source_job_id"]`.

    `extra` carries the rest of the beat's metadata — where `orchestrator_depth`
    lands, so an intermediate agentic hop is labelled the same way the chat UI
    labels one instead of being indistinguishable from a real continuation.
    """
    repo = _beat_repo(session)
    existing = repo.list_by_chapter(chapter.id)
    repo.append(
        chapter.id,
        role=role,
        content=content,
        parent_beat_id=(existing[-1].get("id") if existing else None),
        source_job_id=source_job_id,
        extra=extra,
    )
    beats = sync_from_rows(chapter, session)
    return beats[-1] if beats else None


def append_beat_alternate(
    chapter: StoryChapter,
    session: Session,
    *,
    role: str,
    content: str,
    retry_of: str,
    source_job_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Add a second take of an existing beat, keeping the first.

    The story counterpart of a chat swipe. `retry_last_continuation` used to
    TRIM the last narrator beat and re-enqueue, so a continuation you disliked
    was gone the moment you asked for another — there was one revision snapshot
    to rewind to and no way to compare the two side by side. A chat swipe has
    been additive for as long as it existed: `alternates` on one row,
    `active_index` pointing at the one that renders.

    The same three fields on a beat, because that is the model that made
    `absorb_prose_edit` and `sync_chapter_prose` total — one record per beat,
    the prose a render of it. A retry therefore stores the new take beside the
    old rather than in place of it.

    `content` on the beat is the ACTIVE alternate, so `render_beats` needs no
    special case: the beat renders what is selected, and the rejected takes stay
    in `alternates` for the user to come back to.

    Idempotent on the same LIKE search `_beat_already_stamped` uses: the stamp is
    inside the alternate, and the search scans the serialised `beats` column, so
    a redelivery finds its own job id whichever slot it landed in.
    """
    repo = _beat_repo(session)
    row = repo.get(retry_of)
    if row is None or row.chapter_id != chapter.id:
        # The anchor is gone. A fresh beat at the tail is the honest recovery:
        # the user asked for a continuation and the one it would have replaced
        # has been deleted by hand.
        logger.info("story_retry_anchor_missing", retry_of=retry_of)
        return append_beat(
            chapter, session,
            role=role,
            content=content,
            source_job_id=source_job_id,
            extra=extra,
        )

    alternates = list(row.alternates or [])
    if not alternates:
        # The first retry: seed the list with the beat's own take, stamped with
        # the job that produced it if there was one, so the alternates are
        # self-describing from the start rather than growing a stamp later.
        alternates = [{"text": row.content}]
        if row.source_job_id:
            alternates[0][SOURCE_JOB_ID_METADATA_KEY] = row.source_job_id
    entry: dict[str, Any] = {"text": content}
    if source_job_id:
        entry[SOURCE_JOB_ID_METADATA_KEY] = source_job_id
    alternates.append(entry)

    # On the ROW now, not in a spliced list of dicts — the reason the row model
    # exists is that this kind of write had no safe target. A MutableList does
    # not record an in-place edit of a nested dict, which silently persisted the
    # old beats while `content`, a plain column, carried the new prose.
    row.alternates = alternates
    row.active_index = len(alternates) - 1
    # The beat's own content IS the active alternate, so the render is unchanged
    # in shape and the new take is what the user sees.
    row.content = content
    if source_job_id and not row.source_job_id:
        # Only when the beat has none of its own. Overwriting an existing stamp
        # would hide the job the first take came from.
        row.source_job_id = source_job_id
    if extra:
        merged = dict(row.extra or {})
        merged.update(extra)
        row.extra = merged
    session.add(row)

    sync_from_rows(chapter, session)
    return _row_to_beat_dict(row)


def select_beat_alternate(chapter: StoryChapter, session: Session, beat_id: str, index: int) -> bool:
    """Point a beat at a different of its takes and re-render.

    The story counterpart of `POST /chats/{id}/messages/{id}/swipe` with
    `direction`/`index`. Returns False when the beat or the index does not exist,
    so the route can 404 rather than silently doing nothing.
    """
    repo = _beat_repo(session)
    row = repo.get(beat_id)
    if row is None or row.chapter_id != chapter.id:
        return False
    alternates = list(row.alternates or [])
    if not alternates or not 0 <= index < len(alternates):
        return False
    entry = alternates[index]

    row.active_index = index
    row.content = entry.get("text") or ""
    if entry.get(SOURCE_JOB_ID_METADATA_KEY):
        # The beat carries the stamp of whichever take is showing, so the
        # reconciler looks for the job that produced the text on screen.
        row.source_job_id = entry[SOURCE_JOB_ID_METADATA_KEY]
    session.add(row)

    sync_from_rows(chapter, session)
    return True


# The TTS beat role is declared beside its only writer, in
# `world_integration_service.TTS_BEAT_ROLE`, and admitted here rather than reused
# from `StoryBeatRole`: a TTS beat has empty `content` and carries `audio_path`,
# so calling it `narrator` would make "retry the last continuation" try to trim
# an empty string out of the chapter, and `system` means "scene break"
# everywhere else. `StoryBeatRole` is the enum the beat request models are
# validated against and it is not ours to widen, so the extra value is declared
# beside the set that consumes it.
_ALLOWED_BEAT_ROLES = {r.value for r in StoryBeatRole} | {TTS_BEAT_ROLE}


@router.post("/{story_id}/chapters/{chapter_id}/beats/{beat_id}/select-alternate", response_model=StoryChapter)
def select_alternate(story_id: str, chapter_id: str, beat_id: str, data: SelectAlternateRequest, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo)):
    """Point a beat at a different of its takes.

    The story counterpart of `POST /chats/{id}/messages/{id}/swipe`. Retry used
    to be destructive, so there was nothing to switch between; now the takes
    accumulate on the beat and this picks which one renders.
    """
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)

    if not select_beat_alternate(chapter, session, beat_id, data.index):
        raise ValidationError("No alternate at that index")
    chapter.updated_at = datetime.now(timezone.utc)
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter


@router.patch("/{story_id}/chapters/{chapter_id}/beats/{beat_id}", response_model=StoryChapter)
def update_story_beat(story_id: str, chapter_id: str, beat_id: str, data: StoryBeatUpdateRequest, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo), story_revision_repo: StoryChapterRevisionRepository = Depends(get_story_revision_repo)):
    """Edit a single beat's text and/or role, keeping the chapter prose in sync."""
    if data.content is None and data.role is None:
        raise ValidationError("Nothing to update — provide content and/or role")
    if data.role is not None and data.role not in _ALLOWED_BEAT_ROLES:
        raise ValidationError(f"role must be one of {sorted(_ALLOWED_BEAT_ROLES)}")

    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)

    _ensure_beat_ids(session, chapter)
    beats = list(chapter.beats or [])
    index = next((i for i, b in enumerate(beats) if isinstance(b, dict) and b.get("id") == beat_id), None)
    if index is None:
        raise NotFoundError("StoryBeat", beat_id)

    beat = dict(beats[index])
    old_content = beat.get("content") or ""
    old_role = beat.get("role") or StoryBeatRole.NARRATOR.value
    new_content = old_content if data.content is None else data.content.strip()
    new_role = old_role if data.role is None else data.role

    if not new_content:
        raise ValidationError("Beat content cannot be empty")

    beats[index] = {**beat, "content": new_content, "role": new_role}

    # The prose is a render of this list, so it is recomputed rather than
    # spliced. There is no failure mode left here: the old path located the
    # beat's text in the chapter with `rfind` and 400'd when a manual edit had
    # moved it, which left the beats panel's edit and delete affordances
    # permanently unusable for that chapter and offered no way back.
    story_revision_repo.create_snapshot(chapter, source="pre_beat_edit")
    write_beats(chapter, session, beats)

    chapter.updated_at = datetime.now(timezone.utc)
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter


@router.delete("/{story_id}/chapters/{chapter_id}/beats/{beat_id}", response_model=StoryChapter)
def delete_story_beat(story_id: str, chapter_id: str, beat_id: str, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo), story_revision_repo: StoryChapterRevisionRepository = Depends(get_story_revision_repo)):
    """Remove a beat and its contribution to the chapter prose."""
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)

    _ensure_beat_ids(session, chapter)
    beats = list(chapter.beats or [])
    index = next((i for i, b in enumerate(beats) if isinstance(b, dict) and b.get("id") == beat_id), None)
    if index is None:
        raise NotFoundError("StoryBeat", beat_id)

    del beats[index]

    story_revision_repo.create_snapshot(chapter, source="pre_beat_delete")
    write_beats(chapter, session, beats)

    chapter.updated_at = datetime.now(timezone.utc)
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter


@router.post("/{story_id}/chapters/{chapter_id}/branch", response_model=StoryChapter)
def branch_chapter(story_id: str, chapter_id: str, data: StoryBranchRequest, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo)):
    """Fork the story at a specific beat into a new chapter.

    The new chapter keeps the shared history up to (and including) the
    branch point, then continues from there.

    The fork is taken from the chapter's **prose**, truncated at the anchor
    beat, not rebuilt from the beat list. It used to be rebuilt purely from
    `beats[:idx+1]`, so any prose that had no beat behind it was silently
    dropped from the fork: hand-typed editor text never creates a beat, and
    `restore_chapter_revision` rewrites `content` from a snapshot while leaving
    `beats` untouched, so the two diverge after any restore. The user branched,
    were navigated to the new chapter, and found their chapter truncated — while
    the dialog said "The original chapter is untouched", implying a complete
    fork.

    When the anchor beat's text is not present in the prose (the two have
    drifted, or the chapter is empty) there is no safe truncation point, so it
    falls back to the beat-derived text, which is at least internally consistent.
    """
    chapter = story_chapter_repo.get(chapter_id, story_id)
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
        # The id is the *beat's*, not the chapter's. Reporting the chapter id
        # here sent the caller looking up the wrong entity on a bad beat id.
        raise NotFoundError("StoryBeat", data.from_beat_id)

    prefix = [dict(b) for b in beats[: idx + 1]]

    prompt = data.prompt.strip()
    if prompt:
        prefix.append({
            "id": str(uuid4()),
            "parent_beat_id": data.from_beat_id,
            "role": StoryBeatRole.USER.value,
            "content": prompt,
        })

    # The fork keeps the chapter's own prose up to the anchor, so anything the
    # user typed in the editor that never became a beat is not silently dropped.
    # Under the render-as-the-record model this is the same string
    # `render_beats(prefix)` produces, but the anchor beat may have been edited
    # by hand since, so a cut of the real prose is still the safer source and
    # the beat list is the fallback.
    beat_derived = render_beats(prefix).strip()

    new_content = None
    anchor_beat = prefix[idx] if idx < len(prefix) else {}
    anchor_text = (anchor_beat.get("content") or "").strip()
    source_content = chapter.content or ""
    if anchor_text and source_content:
        cut = _beat_snippet(anchor_text, anchor_beat.get("role"))
        position = source_content.find(cut)
        if position != -1:
            new_content = source_content[: position + len(cut)].strip()

    if not new_content:
        new_content = beat_derived

    max_chapter = session.exec(
        select(StoryChapter)
        .where(StoryChapter.story_id == story_id)
        .order_by(StoryChapter.chapter_number.desc())
        .limit(1)
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
    story_repo: StoryRepository = Depends(get_story_repo),
    story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo),
):

    # Both the job submission and the LLM job creation are awaited, so the
    # chapter/story/checkpoint reads run in a worker thread.
    story, chapter, checkpoint = await asyncio.to_thread(
        _illustrate_chapter_prep_sync, session, story_repo, story_chapter_repo, story_id, chapter_id
    )

    if data.image_prompt:
        # Provided prompt: queue image job directly (non-blocking)
        from services.image_submission import submit_image_job

        img_job = await submit_image_job(
            session,
            prompt=data.image_prompt,
            checkpoint=checkpoint,
            workspace="story",
            story_id=story_id,
            chapter_id=chapter_id,
            extra_metadata={"prompt": data.image_prompt},
        )
        return {"job_id": img_job.id, "prompt": data.image_prompt}

    # No provided prompt: fire an LLM job to generate one, store context for
    # chaining into an image job when the LLM completes. Assembling it reads
    # characters and lorebooks, so it too runs in a worker thread.
    system_prompt = await asyncio.to_thread(
        _illustrate_system_prompt_sync, session, story, chapter
    )

    workflow, metadata = build_llm_workflow(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Chapter text:\n{chapter.content[-3000:]}"}
        ],
        type_="story_illustrate_prompt",
        story_id=story_id,
        chapter_id=chapter_id,
        model=_model_for_kind("story_illustrate_prompt", story.llm_model if story else None, session),
        workspace="story",
        samplers=sampler_overrides(story),
        source="story_illustrate_prompt",
        extra_metadata={"scene_checkpoint": checkpoint},
    )
    prompt_job = await submit_llm_job(session, workflow, metadata)

    return {"job_id": prompt_job.id, "status": "queued", "message": "Illustration prompt generation started"}


def _illustrate_chapter_prep_sync(
    session: Session,
    story_repo: StoryRepository,
    story_chapter_repo: StoryChapterRepository,
    story_id: str,
    chapter_id: str,
) -> tuple[Story | None, StoryChapter, str]:
    """Load the chapter, its story and the checkpoint to illustrate with."""
    from services.chat_utils import resolve_scenario_defaults

    story, chapter = _story_chapter_pair_sync(
        story_repo, story_chapter_repo, story_id, chapter_id
    )

    # Resolve checkpoint: story characters > scenario default > fallback to an installed model
    preferred_ckpt = None
    if story and story.character_ids:
        char = session.get(Character, story.character_ids[0])
        if char and char.checkpoint:
            preferred_ckpt = char.checkpoint
    if not preferred_ckpt and story:
        preferred_ckpt, _ = resolve_scenario_defaults(session, story)
    checkpoint = _resolve_default_checkpoint(session, preferred_ckpt)
    return story, chapter, checkpoint


def _illustrate_system_prompt_sync(
    session: Session, story: Story | None, chapter: StoryChapter
) -> str:
    """Assemble the art-director prompt from the story's characters and lore."""
    from config import get_system_prompt_blocks
    blocks = get_system_prompt_blocks() or {}
    system_prompt = blocks.get("story_illustrate") or (
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

    if story and story.lorebook_ids:
        # One path for both RAG states.
        #
        # There used to be an `if rag_enabled()` branch here, and the else arm
        # loaded EVERY entry of EVERY story lorebook with no `LIMIT` and no
        # `ORDER BY`, then concatenated all of them into a paid LLM system
        # prompt. So a SillyTavern import with a few thousand entries produced a
        # multi-megabyte prompt — and the asymmetry was perverse: the setting the
        # UI offers as a memory saver made THIS prompt larger, while the same
        # story's Continue path went through `context_builder`, which bounds lore
        # deliberately.
        #
        # `search_lorebook_entries` already degrades correctly when RAG is off:
        # its docstring is explicit that "turning RAG off removes only the
        # semantic step, not retrieval" and that returning [] would make
        # lorebooks silently inert. So there is nothing to choose between the two
        # arms — the branch was only ever duplicating it badly.
        #
        # With the semantic cutoff now in place (see
        # `rag_pipeline.rag_max_distance`), this also inherits the fix for the
        # inverse problem: when nothing in the lorebook is relevant, fewer than
        # `limit` entries come back rather than an arbitrary top-N.
        lore_lines = []
        try:
            relevant = search_lorebook_entries(
                session,
                story.lorebook_ids,
                query=(chapter.content or "")[-2000:],
                limit=8,
            )
        except Exception as exc:  # pragma: no cover - retrieval edge cases
            logger.warning("illustrate_lorebook_retrieval_failed", error=str(exc))
            relevant = []
        for entry in relevant:
            keys_str = ", ".join(entry.keys) if entry.keys else "General"
            lore_lines.append(f"- [{keys_str}]: {entry.content}")
        if lore_lines:
            system_prompt += "\n\nRelevant World Lore:\n" + "\n".join(lore_lines)
    return system_prompt


@router.get("/{story_id}/images")
def list_story_images(story_id: str, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo)):
    """List all images across the story's chapters (workspace gallery)."""
    story = story_repo.get(story_id)
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
    story_repo: StoryRepository = Depends(get_story_repo),
    story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Trigger TTS narration for an entire story chapter.

    `Idempotency-Key` is opt-in, matching the chat narrate route. A chapter
    narration is the longest TTS job there is, so a double click on this one is
    the most expensive retry in the app.
    """
    from infrastructure.request_dedup import deduplicated, make_key

    if idempotency_key and idempotency_key.strip():
        dedup_key = make_key(
            "narrate_chapter", story_id, chapter_id, idempotency_key.strip()
        )
        return await deduplicated(
            dedup_key,
            lambda: _narrate_chapter(
                session, story_repo, story_chapter_repo, story_id, chapter_id
            ),
        )

    return await _narrate_chapter(
        session, story_repo, story_chapter_repo, story_id, chapter_id
    )


async def _narrate_chapter(
    session: Session,
    story_repo: StoryRepository,
    story_chapter_repo: StoryChapterRepository,
    story_id: str,
    chapter_id: str,
):
    from services.tts_workflow_builder import build_voice_speak_workflow

    # Story, chapter and voice resolution are synchronous session work; the job
    # creation below is awaited, so it moves to a worker thread — along with the
    # capability guard, which is a session query and must fail before a graph is
    # built.
    text, voice_profile, voice_model_id, language, filename_prefix = await asyncio.to_thread(
        _narrate_chapter_prep_sync,
        session,
        story_repo,
        story_chapter_repo,
        story_id,
        chapter_id,
    )

    # `build_tts_workflow` emitted `XTTS_v2` + `SaveAudio` node types that exist
    # in no provider image, and the job went out as `task_type="image"`, so it
    # was routed to a worker that could not build its graph. The dedicated TTS
    # worker is a separate provider capability; the metadata keys are unchanged
    # so `_handle_story_tts` still selects on `source == "story_tts"`.
    workflow, metadata = build_voice_speak_workflow(
        text,
        voice_profile=voice_profile,
        language=language,
        filename_prefix=filename_prefix,
        extra_metadata={
            "story_id": story_id,
            "chapter_id": chapter_id,
            "voice_model_id": voice_model_id,
            "source": "story_tts",
        },
    )

    job = await submit_tts_job(
        session,
        workflow,
        metadata,
    )

    return {"job_id": job.id, "chapter_id": chapter_id, "story_id": story_id}


def _narrate_chapter_prep_sync(
    session: Session,
    story_repo: StoryRepository,
    story_chapter_repo: StoryChapterRepository,
    story_id: str,
    chapter_id: str,
) -> tuple[str, str | None, str | None, str | None, str]:
    """Load the chapter text and resolve the voice to narrate it with."""
    from services.chat_utils import resolve_scenario_defaults, resolve_voice_for_character
    from services.tts_workflow_builder import _require_tts_capable

    # The same guard `voices.py` calls, first, before it reads anything or builds
    # a graph. It runs here rather than in the route body because this function
    # is already the route's off-loop prologue, and the guard is a session query.
    # Fail now with a 400 naming the missing capability, instead of accepting a
    # job that dies inside a container naming a node that is not installed.
    _require_tts_capable(session)

    story = story_repo.get(story_id)
    if not story:
        raise NotFoundError("Story", story_id)
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)

    text = chapter.content.strip()
    if not text:
        raise ComfyError("Chapter has no content to narrate")

    # Resolve voice model from story or first character, falling back to scenario default
    voice_profile = voice_model_id = language = None
    if story.character_ids:
        char = session.get(Character, story.character_ids[0])
        voice_profile, voice_model_id, language = resolve_voice_for_character(session, char)
    if not voice_profile:
        _, scenario_voice = resolve_scenario_defaults(session, story)
        if scenario_voice:
            voice_profile = scenario_voice
    return (
        text,
        voice_profile,
        voice_model_id,
        language,
        f"story_tts/{story_id}/{chapter_id}",
    )


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
    from config import get_system_prompt_blocks
    blocks = get_system_prompt_blocks() or {}
    default_parse_prompt = """You are an AI worldbuilder. Parse the provided story text and extract the following:
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
    system_prompt = blocks.get("story_parse") or default_parse_prompt
    workflow, metadata = build_chat_llm_workflow(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": req.text[:10000]}  # limit text length
        ],
        chat_id=None,
        character_id=None,
        model=_model_for_kind("story_parse", None, session),
        type_="story_parse"
    )
    metadata["story_id"] = req.story_id
    metadata["workspace"] = "story"
    job = await submit_llm_job(session, workflow, metadata)
    await asyncio.to_thread(session.commit)
    return {"job_id": job.id}


class StartChatFromStoryRequest(BaseModel):
    chapter_id: str | None = None


@router.post("/{story_id}/start-chat")
def start_chat_from_story(
    story_id: str,
    req: StartChatFromStoryRequest | None = None,
    session: Session = Depends(get_session),
    story_repo: StoryRepository = Depends(get_story_repo),
    chat_repo: ChatRepository = Depends(get_chat_repo),
):
    """Seed and launch a live Roleplay Chat directly from a Story scene."""
    story = story_repo.get(story_id)
    if not story:
        raise NotFoundError("Story", story_id)

    # Resolve primary and additional characters
    char_ids = story.character_ids or []
    primary_char_id = char_ids[0] if char_ids else None
    additional_char_ids = char_ids[1:] if len(char_ids) > 1 else []

    # Resolve active chapter
    chapter = None
    target_chapter_id = req.chapter_id if req else None
    if target_chapter_id:
        chapter = session.exec(
            select(StoryChapter).where(StoryChapter.id == target_chapter_id, StoryChapter.story_id == story_id)
        ).first()
    if not chapter:
        chapter = session.exec(
            select(StoryChapter).where(StoryChapter.story_id == story_id).order_by(StoryChapter.chapter_number).limit(1)
        ).first()

    chat_name = f"{story.title} — {chapter.title or f'Chapter {chapter.chapter_number}' if chapter else 'Scene'}"
    chat = Chat(
        name=chat_name,
        character_id=primary_char_id,
        additional_character_ids=additional_char_ids,
        world_id=story.world_id,
        active_lorebook_ids=list(story.lorebook_ids or []),
        location_id=story.location_ids[0] if story.location_ids else None,
        scenario_id=story.scenario_id,
        persona_id=story.persona_id,
        persona_name=story.persona_name,
        persona_description=story.persona_description,
        llm_model=story.llm_model,
    )
    chat.created_at = datetime.now(timezone.utc)
    chat.updated_at = chat.created_at
    link_to_world(session, chat, story.world_id)
    session.add(chat)
    session.commit()
    session.refresh(chat)

    # If chapter content exists, add an introductory system scene beat to seed roleplay
    if chapter and chapter.content and chapter.content.strip():
        excerpt = chapter.content.strip()
        if len(excerpt) > 1200:
            excerpt = "..." + excerpt[-1200:]

        seed_msg = Message(
            chat_id=chat.id,
            role=MessageRole.SYSTEM,
            content=f"[Scene Setting from Story: {story.title} — {chapter.title or f'Chapter {chapter.chapter_number}'}]\n\n{excerpt}",
            message_metadata={
                "source": "story_seed",
                "story_id": story.id,
                "chapter_id": chapter.id,
            },
        )
        session.add(seed_msg)
        session.commit()

    return {
        "chat_id": chat.id,
        "name": chat.name,
    }

