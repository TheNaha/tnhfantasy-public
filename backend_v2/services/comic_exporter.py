"""
Comic / webtoon exporter for the Story Sandbox.

Given a story chapter, splits its prose into panels, generates a consistent
image per panel (same seed + visual_tags per character across panels), and
assembles a CBZ archive plus a self-contained HTML reader.

Triggered manually from the story chapter view. The route runs the pipeline
synchronously within a background task and returns a job id immediately; a
WebSocket event announces completion with the download URL.

Output layout (under OUTPUT_DIR):
    data/output/{user_id}/comics/{story_id}/chapter_{chapter_number}/
        pages/
            page_0001.png
            page_0002.png
            ...
        comic.yaml          (manifest)
        reader.html         (self-contained web reader)
        story.cbz           (CBZ archive: pages + manifest)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from typing import Any

from config import env_positive_int
from core.entities import JobStatus, StoryChapter
from core.scene_graph import (
    SceneCompositionSpec,
    SceneGraphSpec,
    SceneSamplerSpec,
    apply_scene_spec_limits,
    validate_scene_spec,
)
from infrastructure.image_processor import get_output_path
from infrastructure.logging import get_logger
from services.asset_reconciler import reconcile_asset
from services.image_submission import submit_image_job
from services.job_queue import queue_manager
from services.job_service import JobService

logger = get_logger("comic_exporter")

# Workspace used for comic output, so the asset index and gallery can scope to it.
COMICS_WORKSPACE = "comics"

# Default panels per page: one panel per page (simple, readable).
DEFAULT_PANELS_PER_PAGE = 1

# Comic page dimensions: portrait, SDXL-friendly.
COMIC_WIDTH = 832
COMIC_HEIGHT = 1216

# How long to wait for a single panel image job before giving up.
PANEL_JOB_TIMEOUT_SECONDS = 300

# Max concurrent panel image jobs. A single-user setup keeps this low to
# avoid overloading one provider; override with COMIC_EXPORT_MAX_CONCURRENCY.
COMIC_EXPORT_MAX_CONCURRENCY = env_positive_int(
    os.environ.get("COMIC_EXPORT_MAX_CONCURRENCY"), 3
)


def _char_seed(character_name: str) -> int:
    """Deterministic seed for a character, so the same character keeps the
    same seed across every panel of a comic."""
    return int(hashlib.sha256(f"comic-char:{character_name}".encode()).hexdigest()[:8], 16) % (
        2**31
    )


def _characters_in_text(content: str, characters_by_id: dict[str, Any]) -> list[str]:
    """Return the character ids whose names appear in the given text."""
    found: list[str] = []
    for cid, char in characters_by_id.items():
        name = getattr(char, "name", None) or ""
        if name and name in content:
            found.append(cid)
    return found


def _has_dialogue(content: str) -> bool:
    """Heuristic: does this paragraph contain spoken dialogue?"""
    return '"' in content or "“" in content or "”" in content


def split_chapter_into_panels(
    chapter: StoryChapter, characters_by_id: dict[str, Any]
) -> list[dict[str, Any]]:
    """Split a chapter's prose into panels.

    Uses beats when available (each beat = one panel), otherwise splits
    content by paragraphs. Dialogue-heavy content gets dialogue panels;
    narration gets caption panels.

    Returns a list of dicts with: index, content, characters, panel_type,
    scene_description.
    """
    panels: list[dict[str, Any]] = []

    beats = chapter.beats or []
    if beats:
        for i, beat in enumerate(beats):
            content = (beat.get("content") or "").strip()
            if not content:
                continue
            role = beat.get("role", "narrator")
            panel_type = "narration" if role == "narrator" else "dialogue"
            char_ids = _characters_in_text(content, characters_by_id)
            panels.append(
                {
                    "index": i,
                    "content": content,
                    "characters": char_ids,
                    "panel_type": panel_type,
                    "scene_description": content[:200],
                }
            )
    else:
        paragraphs = [p.strip() for p in (chapter.content or "").split("\n\n") if p.strip()]
        for i, para in enumerate(paragraphs):
            char_ids = _characters_in_text(para, characters_by_id)
            panels.append(
                {
                    "index": i,
                    "content": para,
                    "characters": char_ids,
                    "panel_type": "dialogue" if _has_dialogue(para) else "narration",
                    "scene_description": para[:200],
                }
            )

    return panels


def _panel_prompt(panel: dict[str, Any], characters_by_id: dict[str, Any]) -> str:
    """Build a Danbooru-style image prompt for one panel.

    Includes character visual_tags for consistency, plus the panel's own
    scene description. Dialogue panels add framing that leaves room for
    speech bubbles; narration panels get wide establishing shots.
    """
    parts: list[str] = []

    scene = panel.get("scene_description", "")
    if scene:
        parts.append(scene)

    for cid in panel.get("characters", []):
        char = characters_by_id.get(cid)
        if char and getattr(char, "visual_tags", None):
            parts.append(f"({char.visual_tags})")
        if char:
            parts.append(f"1boy/1girl, {char.name}")

    if panel["panel_type"] == "dialogue":
        parts.append(
            "medium shot, character centered, empty space for speech bubble, "
            "dialogue panel, comic panel, manga style"
        )
    elif panel["panel_type"] == "narration":
        parts.append(
            "wide shot, establishing shot, atmospheric, caption panel, "
            "comic panel, manga style"
        )
    else:
        parts.append("comic panel, manga style, line art, cel shaded")

    parts.append("clean background, line art, cel shaded")

    return ", ".join(parts)


def _panel_spec(
    panel: dict[str, Any],
    characters_by_id: dict[str, Any],
    checkpoint: str,
    panel_index: int,
) -> SceneGraphSpec:
    """Build a SceneGraphSpec for one panel.

    Character consistency: each character present in the panel contributes
    their deterministic seed. The first character's seed is used for the
    panel, so the same character always renders with the same seed.
    """
    characters = panel.get("characters", [])
    seed = 0
    if characters:
        first_char = characters_by_id.get(characters[0])
        if first_char:
            seed = _char_seed(getattr(first_char, "name", "")) + panel_index

    return SceneGraphSpec(
        prompt=_panel_prompt(panel, characters_by_id),
        negative_prompt="text, watermark, signature, logo, title, letters, UI, interface",
        composition=SceneCompositionSpec(
            width=COMIC_WIDTH,
            height=COMIC_HEIGHT,
            batch_size=1,
        ),
        sampler=SceneSamplerSpec(
            name="euler",
            scheduler="normal",
            steps=20,
            cfg=7.0,
            denoise=1.0,
            seed=seed,
        ),
    )


async def _wait_for_image_job(
    job_service: JobService,
    job_id: str,
    timeout_seconds: int = PANEL_JOB_TIMEOUT_SECONDS,
) -> list[dict[str, Any]] | None:
    """Poll a single image job until it reaches a terminal state.

    Returns the job's outputs (list of image dicts) on success, None on
    failure or timeout.
    """
    deadline = datetime.now(timezone.utc).timestamp() + timeout_seconds
    while True:
        job = await job_service.get_job(job_id)
        if not job:
            logger.warning("comic_panel_job_missing", job_id=job_id)
            return None
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            if job.status == JobStatus.COMPLETED:
                return job.outputs or []
            logger.warning(
                "comic_panel_job_failed",
                job_id=job_id,
                status=job.status.value,
                error=job.error,
            )
            return None
        if datetime.now(timezone.utc).timestamp() > deadline:
            logger.warning("comic_panel_job_timeout", job_id=job_id)
            return None
        await asyncio.sleep(2.0)


async def _generate_panel_images(
    session,
    job_service: JobService,
    panels: list[dict[str, Any]],
    characters_by_id: dict[str, Any],
    checkpoint: str,
    story_id: str | None,
    chapter_id: str | None,
    user_id: str,
) -> list[dict[str, Any]]:
    """Generate one image per panel, waiting for each to complete.

    Returns a list of panels with `image_path` populated for successful ones.
    Failed panels keep `image_path = None` and are logged — the export
    proceeds with placeholder pages for failed panels.

    All panel image jobs are submitted upfront, then awaited concurrently
    behind a concurrency semaphore so wall-clock time is not additive per
    panel.
    """
    # Step 1: Submit every panel image job upfront. Each is a fast DB row
    # + enqueue; the actual generation happens on the provider.
    panel_jobs: list[tuple[dict[str, Any], str]] = []  # (panel, job_id)
    for panel in panels:
        spec = _panel_spec(
            panel,
            characters_by_id,
            checkpoint,
            panel_index=panel["index"],
        )
        # Pre-flight check: validate the spec against scene-graph limits.
        # Issues are logged but the spec is clamped and proceeds — a panel
        # that asked for 200 steps gets 60 steps, not a failed job.
        issues = validate_scene_spec(spec)
        if issues:
            logger.warning(
                "comic_panel_spec_issues",
                panel_index=panel["index"],
                issues=[{"field": i.field, "problem": i.problem, "resolution": i.resolution} for i in issues],
            )
        spec = apply_scene_spec_limits(spec)

        # Character consistency seed, stamped on metadata for the gallery.
        char_seed = 0
        if panel.get("characters"):
            first_char = characters_by_id.get(panel["characters"][0])
            if first_char:
                char_seed = _char_seed(getattr(first_char, "name", ""))

        job = await submit_image_job(
            session,
            prompt=spec.prompt,
            negative_prompt=spec.negative_prompt,
            checkpoint=checkpoint,
            workspace=COMICS_WORKSPACE,
            story_id=story_id,
            chapter_id=chapter_id,
            source="comic_panel",
            task_type="image",
            extra_metadata={
                "comic_panel_index": panel["index"],
                "comic_panel_type": panel["panel_type"],
                "comic_characters": panel.get("characters", []),
                "comic_seed": char_seed,
                "comic_story_id": story_id,
                "comic_chapter_id": chapter_id,
                "scene_graph": True,
                "panel_prompt": spec.prompt,
                "panel_width": spec.composition.width,
                "panel_height": spec.composition.height,
                "panel_steps": spec.sampler.steps,
                "panel_seed": spec.sampler.seed,
            },
            spec=spec,
        )
        await queue_manager.enqueue(job.id, task_type="image")
        panel_jobs.append((panel, job.id))

    # Step 2: Wait for all panel jobs concurrently behind a semaphore so a
    # slow panel does not block the rest. Failed panels keep image_path=None
    # and the page assembler substitutes a placeholder.
    semaphore = asyncio.Semaphore(COMIC_EXPORT_MAX_CONCURRENCY)

    async def _wait_one(panel: dict[str, Any], job_id: str) -> None:
        async with semaphore:
            outputs = await _wait_for_image_job(job_service, job_id)
            if outputs:
                panel["image_path"] = outputs[0].get("filename") or outputs[0].get("data")
                panel["image_outputs"] = outputs
                logger.info(
                    "comic_panel_image_ready",
                    panel_index=panel["index"],
                    job_id=job_id,
                    image_path=panel["image_path"],
                )
            else:
                logger.warning(
                    "comic_panel_image_failed",
                    panel_index=panel["index"],
                    job_id=job_id,
                )

    await asyncio.gather(*[_wait_one(panel, job_id) for panel, job_id in panel_jobs])

    return panels


def _assemble_pages(
    panels: list[dict[str, Any]],
    output_dir: str,
    chapter: StoryChapter,
) -> list[str]:
    """Lay panels out into pages (one panel per page) and return page image paths.

    Each panel image becomes one page. A future pass can group multiple panels
    per page with gutters and reading order.
    """
    page_paths: list[str] = []
    for i, panel in enumerate(panels):
        img_path = panel.get("image_path")
        if not img_path:
            img_path = _make_placeholder_panel(i, output_dir, chapter)
        page_paths.append(img_path)
    return page_paths


def _make_placeholder_panel(index: int, output_dir: str, chapter: StoryChapter) -> str:
    """Create a placeholder PNG for a panel whose image generation failed."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (COMIC_WIDTH, COMIC_HEIGHT), color=(40, 40, 50))
    draw = ImageDraw.Draw(img)
    text = f"Panel {index + 1}\n(image unavailable)"
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    draw.text((40, 40), text, fill=(200, 200, 200), font=font)

    page_dir = os.path.join(output_dir, "pages")
    os.makedirs(page_dir, exist_ok=True)
    path = os.path.join(page_dir, f"page_{index + 1:04d}.png")
    img.save(path)
    return path


def _build_manifest(
    story_id: str | None,
    chapter: StoryChapter,
    panels: list[dict[str, Any]],
    page_paths: list[str],
    user_id: str,
) -> dict[str, Any]:
    """Build the comic.yaml manifest."""
    return {
        "version": "1.0",
        "story_id": story_id,
        "chapter_id": chapter.id,
        "chapter_number": chapter.chapter_number,
        "title": chapter.title,
        "user_id": user_id,
        "workspace": COMICS_WORKSPACE,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "page_count": len(page_paths),
        "panels_per_page": DEFAULT_PANELS_PER_PAGE,
        "reading_order": "left-to-right",
        "pages": [
            {
                "page": i + 1,
                "image": os.path.basename(p),
                "panel_index": panels[i].get("index") if i < len(panels) else None,
                "panel_content": panels[i].get("content", "") if i < len(panels) else "",
                "panel_type": panels[i].get("panel_type") if i < len(panels) else None,
            }
            for i, p in enumerate(page_paths)
        ],
    }


def _write_cbz(
    output_dir: str,
    page_paths: list[str],
    manifest: dict[str, Any],
) -> str:
    """Write a CBZ archive (ZIP of pages + comic.yaml manifest)."""
    cbz_path = os.path.join(output_dir, "story.cbz")
    with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in page_paths:
            if os.path.exists(p):
                zf.write(p, arcname=os.path.join("pages", os.path.basename(p)))
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        zf.writestr("comic.yaml", manifest_bytes)
    return cbz_path


def _write_html_reader(
    output_dir: str,
    page_paths: list[str],
    manifest: dict[str, Any],
) -> str:
    """Write a self-contained HTML comic reader."""
    pages_json = json.dumps(
        [
            {
                "image": os.path.basename(p),
                "panel_index": manifest["pages"][i].get("panel_index"),
                "panel_content": manifest["pages"][i].get("panel_content", ""),
                "panel_type": manifest["pages"][i].get("panel_type"),
            }
            for i, p in enumerate(page_paths)
        ],
        indent=2,
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{manifest.get('title', 'Comic Chapter')} — Comic Reader</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: #1a1a1a;
    color: #eee;
    font-family: system-ui, -apple-system, sans-serif;
    overflow: hidden;
  }}
  #reader {{
    width: 100vw;
    height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 1rem;
  }}
  #page-container {{
    max-width: 100%;
    max-height: 85vh;
    border: 2px solid #333;
    box-shadow: 0 0 30px rgba(0,0,0,0.8);
    background: #fff;
  }}
  #page-img {{
    display: block;
    max-width: 100%;
    max-height: 85vh;
    cursor: pointer;
  }}
  #caption {{
    margin-top: 0.75rem;
    font-size: 0.95rem;
    line-height: 1.4;
    max-width: 60ch;
    text-align: center;
  }}
  #controls {{
    position: absolute;
    bottom: 1rem;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    gap: 0.5rem;
  }}
  button {{
    background: #444;
    color: #fff;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: 0.5rem;
    cursor: pointer;
  }}
  button:hover {{ background: #666; }}
  button:disabled {{ opacity: 0.4; cursor: not-allowed; }}
  #progress {{
    position: absolute;
    top: 0.5rem;
    right: 0.5rem;
    background: rgba(0,0,0,0.6);
    padding: 0.25rem 0.75rem;
    border-radius: 1rem;
    font-size: 0.8rem;
  }}
</style>
</head>
<body>
<div id="progress"><span id="pageNum">1</span> / <span id="pageTotal">{len(page_paths)}</span></div>
<div id="reader">
  <div id="page-container">
    <img id="page-img" src="pages/{os.path.basename(page_paths[0])}" alt="Page 1">
  </div>
  <div id="caption"></div>
  <div id="controls">
    <button id="prevBtn" disabled>‹ Prev</button>
    <button id="nextBtn">Next ›</button>
  </div>
</div>
<script>
const pages = {pages_json};
let current = 0;
const img = document.getElementById('page-img');
const caption = document.getElementById('caption');
const pageNum = document.getElementById('pageNum');
const prevBtn = document.getElementById('prevBtn');
const nextBtn = document.getElementById('nextBtn');

function render() {{
  const p = pages[current];
  img.src = 'pages/' + p.image;
  img.alt = 'Page ' + (current + 1);
  pageNum.textContent = current + 1;
  caption.textContent = p.panel_content || '';
  prevBtn.disabled = current === 0;
  nextBtn.disabled = current === pages.length - 1;
}}

prevBtn.onclick = () => {{ if (current > 0) {{ current--; render(); }} }};
nextBtn.onclick = () => {{ if (current < pages.length - 1) {{ current++; render(); }} }};
document.addEventListener('keydown', (e) => {{
  if (e.key === 'ArrowRight') nextBtn.click();
  if (e.key === 'ArrowLeft') prevBtn.click();
}});
render();
</script>
</body>
</html>"""

    html_path = os.path.join(output_dir, "reader.html")
    with open(html_path, "w") as f:
        f.write(html)
    return html_path


async def _register_comic_assets(
    session,
    output_dir: str,
    page_paths: list[str],
    user_id: str,
    story_id: str | None,
    chapter: StoryChapter,
) -> None:
    """Register every comic page image in the assets index."""
    for i, p in enumerate(page_paths):
        if not os.path.exists(p):
            continue
        await reconcile_asset(
            session,
            p,
            user_id=user_id,
            workspace=COMICS_WORKSPACE,
            story_id=story_id,
            chapter_id=chapter.id,
            job_id=None,
            output_dir=output_dir,
        )


async def export_comic_chapter(
    session,
    *,
    story_id: str,
    chapter_id: str,
    user_id: str = "default_user",
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Export a story chapter as a comic (CBZ + HTML reader).

    Runs the full pipeline: split into panels, generate images, assemble
    pages, write CBZ + HTML, register assets.

    Returns a dict with `cbz_path`, `html_path`, `output_dir`, `page_count`.
    """
    from infrastructure.repositories.story_chapter_repo import StoryChapterRepository
    from infrastructure.repositories.story_repo import StoryRepository

    story_repo = StoryRepository(session)
    chapter_repo = StoryChapterRepository(session)

    story = story_repo.get(story_id)
    chapter = chapter_repo.get(chapter_id, story_id)
    if not chapter or chapter.story_id != story_id:
        raise ValueError(f"Chapter {chapter_id} not found in story {story_id}")

    # Load characters for visual tag consistency.
    char_ids = list(story.character_ids or []) or []
    characters_by_id: dict[str, Any] = {}
    if char_ids:
        from sqlmodel import select
        from core.entities import Character

        rows = session.exec(
            select(Character).where(Character.id.in_(char_ids))
        ).all()
        characters_by_id = {r.id: r for r in rows}

    # Resolve checkpoint: story characters > scenario default > fallback.
    checkpoint = None
    if story and story.character_ids:
        char = session.get(
            __import__("core.entities", fromlist=["Character"]).Character,
            story.character_ids[0],
        )
        if char and getattr(char, "checkpoint", None):
            checkpoint = char.checkpoint
    if not checkpoint and story:
        from services.chat_utils import resolve_scenario_defaults

        try:
            scenario_checkpoint, _ = resolve_scenario_defaults(session, story)
            checkpoint = scenario_checkpoint
        except Exception:
            pass
    if not checkpoint:
        from config import resolve_default_checkpoint

        checkpoint = resolve_default_checkpoint()

    # Resolve output directory.
    out = output_dir or get_output_path(
        subdir=os.path.join(COMICS_WORKSPACE, str(story_id), f"chapter_{chapter.chapter_number}"),
        user_id=user_id,
        workspace=COMICS_WORKSPACE,
    )
    os.makedirs(out, exist_ok=True)

    # Step 1: Split chapter into panels.
    panels = split_chapter_into_panels(chapter, characters_by_id)
    if not panels:
        raise ValueError(f"Chapter {chapter_id} has no content to export")

    logger.info(
        "comic_export_started",
        story_id=story_id,
        chapter_id=chapter_id,
        panel_count=len(panels),
    )

    # Step 2: Generate an image per panel.
    job_service = JobService(session)
    panels = await _generate_panel_images(
        session,
        job_service,
        panels,
        characters_by_id,
        checkpoint=checkpoint,
        story_id=story_id,
        chapter_id=chapter_id,
        user_id=user_id,
    )

    # Step 3: Assemble pages (1 panel per page).
    page_paths = _assemble_pages(panels, out, chapter)

    # Step 4: Build manifest.
    manifest = _build_manifest(story_id, chapter, panels, page_paths, user_id)
    manifest_path = os.path.join(out, "comic.yaml")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # Step 5: Write CBZ + HTML reader.
    cbz_path = _write_cbz(out, page_paths, manifest)
    html_path = _write_html_reader(out, page_paths, manifest)

    # Step 6: Register page images as assets.
    await _register_comic_assets(
        session,
        out,
        page_paths,
        user_id=user_id,
        story_id=story_id,
        chapter=chapter,
    )

    session.commit()

    logger.info(
        "comic_export_complete",
        story_id=story_id,
        chapter_id=chapter_id,
        cbz_path=cbz_path,
        html_path=html_path,
        page_count=len(page_paths),
    )

    return {
        "cbz_path": cbz_path,
        "html_path": html_path,
        "output_dir": out,
        "page_count": len(page_paths),
        "manifest": manifest,
    }
