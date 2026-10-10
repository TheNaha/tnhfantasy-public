import asyncio
import os
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from PIL import Image, ImageDraw, ImageFont
from sqlmodel import Session, delete, select

import config as app_config
from api.deps import get_job_service, get_session, get_queue_manager, get_story_repo, get_story_chapter_repo, get_story_revision_repo
from infrastructure.logging import get_logger
from infrastructure.repositories.story_repo import StoryRepository
from infrastructure.repositories.story_chapter_repo import StoryChapterRepository
from infrastructure.repositories.story_revision_repo import StoryChapterRevisionRepository
from services.reference_cleanup import scrub_entity_references
from core.entities import Story, StoryBeatRole, StoryChapter, StoryChapterRevision, Lorebook, Character, Location, Scenario, Asset, AssetKind
from core.exceptions import ComfyError, NotFoundError, ValidationError
from services.llm_config import get_default_llm_model as _get_default_llm_model
from services.llm_workflow import build_llm_workflow, build_chat_llm_workflow, sampler_overrides
from services.rag_pipeline import search_lorebook_entries
from services.job_service import JobService
from services.job_queue import QueueManager, queue_manager
from services.world_ownership import link_story_to_world, require_world
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


class StoryContinueRequest(BaseModel):
    prompt: str = ""


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
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    pov: str | None = None
    word_count_goal: int | None = None


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
    link_story_to_world(session, story, req.world_id)
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
    allowed = {'title', 'description', 'genre', 'character_ids', 'lorebook_ids', 'location_ids', 'llm_model', 'memory', 'scenario_id', 'is_archived', 'max_agentic_depth', 'temperature', 'top_p', 'max_output_tokens', 'frequency_penalty', 'presence_penalty', 'pov', 'word_count_goal'}
    for key, value in update_data.items():
        if key in allowed:
            setattr(story, key, value)

    # `world_id` is not in `allowed` because it is not a plain setattr: it owns a
    # second column on the World side, and an empty string means detach.
    requested_world_id: str | None | object = _WORLD_ID_UNSET
    if "world_id" in update_data:
        requested_world_id = (update_data.pop("world_id") or "").strip() or None
        require_world(session, requested_world_id)
        link_story_to_world(session, story, requested_world_id)

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
    
    scrub_entity_references(session, "story", story_id)
    chapters = session.exec(select(StoryChapter).where(StoryChapter.story_id == story_id)).all()
    for ch in chapters:
        session.exec(
            delete(StoryChapterRevision)
            .where(StoryChapterRevision.chapter_id == ch.id)
        )
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
        chapter.content = chapter_update.content
    if chapter_update.beats is not None:
        chapter.beats = chapter_update.beats
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

    job_id = await _enqueue_story_continuation(session, story, chapter)
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
        if story is not None:
            # commit() expired the story's columns; the enqueue helper below
            # reads them from the event loop.
            session.refresh(story)

    return story, chapter


async def _enqueue_story_continuation(session: Session, story: Story | None, chapter: StoryChapter) -> str:
    """Build the story-continue LLM job for a chapter and enqueue it.

    Shared by the continue and retry-last endpoints so both produce an
    identical context assembly (lorebooks, genre, memory, scenario,
    characters, locations) and identical sampler handling.
    """
    from services.context_builder import build_chat_context_async

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

    messages = [
        *[{"role": "assistant", "content": text} for text in prior_chapters],
        {"role": "user", "content": chapter.content.strip()},
    ]

    story_scenario_template = None
    if story and story.scenario_id:
        # The scenario lookup is synchronous session work in an async helper.
        story_scenario_template = await asyncio.to_thread(
            _scenario_prompt_template, session, story.scenario_id
        )

    world_name = world_description = None
    world_lorebook_ids: list[str] = []
    world_location_ids: list[str] = []
    world_scenario: str | None = None
    if story is not None and story.world_id:
        world = await asyncio.to_thread(_world_prompt_parts, session, story)
        if world is not None:
            world_name, world_description = world["name"], world["description"]
            world_lorebook_ids = world["lorebook_ids"]
            world_location_ids = world["location_ids"]
            world_scenario = world["scenario"]

    if story_premise:
        base_prompt = f"{base_prompt}\n\n[Story premise]\n{story_premise}"

    system_prompt, context = await build_chat_context_async(
        messages,
        # The chat-formatting block (put dialogue in quotes, actions in
        # asterisks) was injected into prose continuations, where it
        # contradicts the instruction above to "just output the next part of the
        # prose". `build_chat_context_with_sections` had no
        # `include_roleplay_default` parameter, so no caller could turn it off.
        include_roleplay_default=False,
        # Same bound every chat reply path uses. Unpassed, this fell through to
        # `DEFAULT_MAX_TOKENS` (4096) regardless of `ai.maxContextTokens`, and
        # `prune_context` then truncated the user's own prose — not the chat
        # formatting block that had eaten the budget.
        max_context_tokens=await asyncio.to_thread(_resolve_context_tokens),
        lorebook_ids=list(dict.fromkeys(
            [*(story.lorebook_ids if story else [] or []), *world_lorebook_ids]
        )) or None,
        system_prompt_override=base_prompt,
        story_genre=story.genre if story else None,
        story_memory=story.memory if story else None,
        story_pov=story.pov if story else None,
        story_scenario=story_scenario_template or world_scenario,
        story_character_ids=(story.character_ids if story else None) or None,
        location_ids=list(dict.fromkeys(
            [*(story.location_ids if story else [] or []), *world_location_ids]
        )) or None,
        world_name=world_name,
        world_description=world_description,
    )

    job_service = JobService(session)

    # Story agentic mode: when the story opts in (max_agentic_depth > 0),
    # offer the story-safe toolset so the model can illustrate its own scenes.
    story_tools: list[dict] = []
    story_agentic = bool(story and (story.max_agentic_depth or 0) > 0)
    if story_agentic:
        from services.orchestrator_service import story_agentic_tools

        story_tools = story_agentic_tools()

    workflow, metadata = build_llm_workflow(
        messages=context,
        type_="story_continue",
        story_id=story_id,
        chapter_id=chapter.id,
        model=((story.llm_model if story else None) or _get_default_llm_model()),
        workspace="story",
        samplers=sampler_overrides(story),
        extra_metadata={
            "agentic": story_agentic,
            "max_agentic_depth": story.max_agentic_depth,
        } if story and story.max_agentic_depth is not None else None,
    )
    if story_tools:
        workflow["tools"] = story_tools
    job = await job_service.create_job(
        task_type="llm",
        workflow=workflow,
        metadata=metadata,
    )

    await queue_manager.enqueue(job.id, task_type="llm")
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
    """The owning World's contribution to a story's prompt, read off the loop."""
    from core.entities import World

    world = session.get(World, story.world_id)
    if world is None:
        return None
    scenario = None
    for scenario_id in world.scenario_ids or []:
        scenario = session.get(Scenario, scenario_id)
        if scenario is not None:
            break
    return {
        "name": world.name,
        "description": world.description,
        "lorebook_ids": list(world.lorebook_ids or []),
        "location_ids": list(world.location_ids or []),
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

    from services.context_builder import build_chat_context_async
    system_prompt, context = await build_chat_context_async(
        [{"role": "user", "content": user_content}],
        lorebook_ids=(story.lorebook_ids if story else None) or None,
        system_prompt_override=_ACTION_PROMPTS[action],
        story_genre=story.genre if story else None,
        story_memory=story.memory if story else None,
        story_pov=story.pov if story else None,
        story_character_ids=(story.character_ids if story else None) or None,
        location_ids=(story.location_ids if story else None) or None,
    )

    job_service = JobService(session)
    workflow, metadata = build_llm_workflow(
        messages=context,
        type_="story_action",
        story_id=story_id,
        chapter_id=chapter_id,
        model=(story.llm_model if story else None) or _get_default_llm_model(),
        workspace="story",
        samplers=sampler_overrides(story),
    )
    job = await job_service.create_job(task_type="llm", workflow=workflow, metadata=metadata)
    await queue_manager.enqueue(job.id, task_type="llm")
    return {"job_id": job.id}


@router.post("/{story_id}/chapters/{chapter_id}/retry-last")
async def retry_last_continuation(story_id: str, chapter_id: str, session: Session = Depends(get_session), story_repo: StoryRepository = Depends(get_story_repo), story_chapter_repo: StoryChapterRepository = Depends(get_story_chapter_repo), story_revision_repo: StoryChapterRevisionRepository = Depends(get_story_revision_repo)):
    """Drop the most recent AI continuation (last narrator beat + its prose)
    and immediately enqueue a fresh continuation in its place."""
    # Trimming the last continuation is synchronous session work and the enqueue
    # below is awaited, so the whole prologue runs in a worker thread.
    story, chapter = await asyncio.to_thread(
        _retry_last_prep_sync,
        session,
        story_repo,
        story_chapter_repo,
        story_revision_repo,
        story_id,
        chapter_id,
    )

    job_id = await _enqueue_story_continuation(session, story, chapter)
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
) -> tuple[Story | None, StoryChapter]:
    """Trim the chapter's last AI continuation, off the event loop."""
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

    last = beats[last_index]
    removed_text = (last.get("content") or "").strip()
    content = chapter.content or ""
    marker = f"\n\n{removed_text}\n\n"
    idx = content.rfind(marker)
    if idx >= 0:
        new_content = (content[:idx] + "\n\n" + content[idx + len(marker):]).strip()
    elif content.endswith(f"\n\n{removed_text}"):
        new_content = content[: -len(removed_text)].rstrip()
    else:
        raise ComfyError("Could not locate the last AI continuation inside the chapter text; edit it manually")

    # Safety net: snapshot the prose before it is trimmed.
    story_revision_repo.create_snapshot(chapter, source="pre_retry")

    chapter.beats = beats[:last_index]
    chapter.content = new_content

    chapter.updated_at = datetime.now(timezone.utc)
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    if story is not None:
        # commit() expired the story's columns; the enqueue helper below reads
        # them from the event loop.
        session.refresh(story)
    return story, chapter


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
    """Restore a chapter's prose from a snapshot.

    The current prose is snapshotted first (source 'pre_restore') so the
    restore itself is undoable. Beats are left untouched — they describe
    turn structure, not the restored text.
    """
    chapter = story_chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise NotFoundError("StoryChapter", chapter_id)
    revision = story_revision_repo.get(revision_id, story_id)
    if not revision or revision.chapter_id != chapter_id:
        raise NotFoundError("StoryChapterRevision", revision_id)

    story_revision_repo.create_snapshot(chapter, source="pre_restore")
    chapter.content = revision.content
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


def _beat_snippet(content: str, role: str) -> str:
    """The exact text a beat contributes to the flat chapter prose."""
    if role == StoryBeatRole.USER.value:
        return f"\n\n> {content}\n\n"
    return f"\n\n{content}\n\n"


def _replace_beat_text(content: str, old_snippet: str, new_snippet: str) -> str | None:
    """Surgically swap one beat's prose inside the chapter text.

    Returns None when the snippet cannot be located (content was edited
    independently of the beats list) so callers can fail before mutating.
    """
    idx = content.rfind(old_snippet)
    if idx >= 0:
        return content[:idx] + new_snippet + content[idx + len(old_snippet):]
    # Tolerate a missing trailing blank line (end-of-chapter beats).
    stripped_old = old_snippet.rstrip("\n")
    if content.endswith(stripped_old):
        return content[: -len(stripped_old)].rstrip("\n") + new_snippet
    return None


def _remove_beat_text(content: str, snippet: str) -> str | None:
    stripped = snippet.rstrip("\n")
    idx = content.rfind(snippet)
    if idx >= 0:
        return (content[:idx] + "\n\n" + content[idx + len(snippet):]).strip()
    if content.endswith(stripped):
        return content[: -len(stripped)].rstrip()
    return None


# The TTS beat role is declared beside its only writer, in
# `world_integration_service.TTS_BEAT_ROLE`, and admitted here rather than reused
# from `StoryBeatRole`: a TTS beat has empty `content` and carries `audio_path`,
# so calling it `narrator` would make "retry the last continuation" try to trim
# an empty string out of the chapter, and `system` means "scene break"
# everywhere else. `StoryBeatRole` is the enum the beat request models are
# validated against and it is not ours to widen, so the extra value is declared
# beside the set that consumes it.
_ALLOWED_BEAT_ROLES = {r.value for r in StoryBeatRole} | {TTS_BEAT_ROLE}


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

    content = chapter.content or ""
    if new_content != old_content or new_role != old_role:
        updated = _replace_beat_text(
            content,
            _beat_snippet(old_content, old_role),
            _beat_snippet(new_content, new_role),
        )
        if updated is None:
            raise ValidationError(
                "Beat text no longer matches the chapter prose — edit the chapter text directly"
            )
        story_revision_repo.create_snapshot(chapter, source="pre_beat_edit")
        chapter.content = updated

    beat["content"] = new_content
    beat["role"] = new_role
    beats[index] = beat
    chapter.beats = beats

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

    removed = beats[index]
    removed_text = (removed.get("content") or "").strip()
    removed_role = removed.get("role") or StoryBeatRole.NARRATOR.value
    if removed_text:
        content = chapter.content or ""
        updated = _remove_beat_text(content, _beat_snippet(removed_text, removed_role))
        if updated is None:
            raise ValidationError(
                "Beat text no longer matches the chapter prose — edit the chapter text directly"
            )
        story_revision_repo.create_snapshot(chapter, source="pre_beat_delete")
        chapter.content = updated

    del beats[index]
    chapter.beats = beats

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

    content_parts = []
    for beat in prefix:
        text = (beat.get("content") or "").strip()
        if not text:
            continue
        if beat.get("role") == StoryBeatRole.USER.value:
            content_parts.append(f"\n\n> {text}\n\n")
        else:
            content_parts.append(f"\n\n{text}\n\n")
    beat_derived = "".join(content_parts).strip()

    # Prefer the real prose, cut at the anchor beat. `_replace_beat_text` /
    # `_remove_beat_text` already own the convention of locating a beat by its
    # snippet (`_beat_snippet`), so the same search is used here.
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
        samplers=sampler_overrides(story),
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


def _illustrate_chapter_prep_sync(
    session: Session,
    story_repo: StoryRepository,
    story_chapter_repo: StoryChapterRepository,
    story_id: str,
    chapter_id: str,
) -> tuple[Story | None, StoryChapter, str]:
    """Load the chapter, its story and the checkpoint to illustrate with."""
    story, chapter = _story_chapter_pair_sync(
        story_repo, story_chapter_repo, story_id, chapter_id
    )

    # Resolve checkpoint: story characters > fallback to an installed model
    checkpoint = _resolve_default_checkpoint(session)
    if story and story.character_ids:
        char = session.get(Character, story.character_ids[0])
        if char and char.checkpoint:
            checkpoint = _resolve_default_checkpoint(session, char.checkpoint)
    return story, chapter, checkpoint


def _illustrate_system_prompt_sync(
    session: Session, story: Story | None, chapter: StoryChapter
) -> str:
    """Assemble the art-director prompt from the story's characters and lore."""
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
    job_service: JobService = Depends(get_job_service),
    queue_manager: QueueManager = Depends(get_queue_manager),
):
    """Trigger TTS narration for an entire story chapter."""
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

    job = await job_service.create_job(
        task_type="tts",
        workflow=workflow,
        metadata=metadata,
    )
    await queue_manager.enqueue(job.id, task_type="tts")

    return {"job_id": job.id, "chapter_id": chapter_id, "story_id": story_id}


def _narrate_chapter_prep_sync(
    session: Session,
    story_repo: StoryRepository,
    story_chapter_repo: StoryChapterRepository,
    story_id: str,
    chapter_id: str,
) -> tuple[str, str | None, str | None, str | None, str]:
    """Load the chapter text and resolve the voice to narrate it with."""
    from services.chat_utils import resolve_voice_for_character
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

    # Resolve voice model from story or first character
    voice_profile = voice_model_id = language = None
    if story.character_ids:
        char = session.get(Character, story.character_ids[0])
        voice_profile, voice_model_id, language = resolve_voice_for_character(session, char)
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
    await asyncio.to_thread(session.commit)
    await queue_manager.enqueue(job.id, task_type="llm")
    return {"job_id": job.id}
