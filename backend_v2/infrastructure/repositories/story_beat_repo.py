"""The single owner of story beats as rows.

Beats were a JSON array of dicts on `story_chapters.beats`, and keeping them in
step with `story_chapters.content` — the prose they render to — was a
hand-written set of splices. That is the two-representations problem: two fields
describing one text, which is the shape this codebase's worst bug class comes
from, and it cost `sync_chapter_prose`, `absorb_prose_edit`, `_beat_snippet` and
two deleted `_replace_beat_text` / `_remove_beat_text` helpers.

A beat is a row now. `story_chapters.beats` still exists and still carries the
same `[...]` shape the API and the editor speak — it is maintained from these
rows by `sync_chapter_prose`, and one writer producing both is what makes them
unable to disagree. What the rows buy is that a beat is independently
addressable, which is what lets a chapter be pruned by beat window instead of
selected whole (see `build_chat_context_async`: a chapter arrives as ONE user
message, so `prune_context` has nothing to trim inside it).

Every read and write of a beat goes through here.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlmodel import Session, select

from core.entities import StoryBeat

# The JSON keys that have a column of their own. Everything else a beat carried
# lives in `extra`, so the move to rows loses nothing.
_COLUMN_KEYS = {
    "id",
    "parent_beat_id",
    "role",
    "content",
    "audio_path",
    "source_job_id",
    "tts_source_job_id",
    "alternates",
    "active_index",
}


def _row_to_dict(beat: StoryBeat) -> dict:
    """The JSON shape a beat has always had, from its row.

    The reader's contract. The API, the editor and the beats panel all speak
    this, which is why `story_chapters.beats` is still populated rather than
    dropped — the rows are the source, and this is the shape they serialise to.
    """
    out: dict = {
        "id": beat.id,
        "parent_beat_id": beat.parent_beat_id,
        "role": beat.role,
        "content": beat.content,
    }
    if beat.audio_path:
        out["audio_path"] = beat.audio_path
    if beat.source_job_id:
        out["source_job_id"] = beat.source_job_id
    if beat.tts_source_job_id:
        out["tts_source_job_id"] = beat.tts_source_job_id
    if beat.alternates:
        out["alternates"] = beat.alternates
        # Always with the alternates, including 0. `0` is a real selection — the
        # FIRST take — and dropping it as falsy made "the first take is showing"
        # indistinguishable from "no selection has been made". A reader that
        # defaults a missing key to 0 gets the right answer by luck, and one that
        # checks for the key's presence gets the wrong one.
        out["active_index"] = beat.active_index
    out.update(beat.extra or {})
    return out


class StoryBeatRepository:
    def __init__(self, session: Session):
        self.session = session

    # ── reads ────────────────────────────────────────────────────────────────

    def list_by_chapter(self, chapter_id: str) -> list[dict]:
        """The chapter's beats as the JSON shape, in position order."""
        rows = self.session.exec(
            select(StoryBeat)
            .where(StoryBeat.chapter_id == chapter_id)
            .order_by(StoryBeat.position)
        ).all()
        return [_row_to_dict(row) for row in rows]

    def rows_by_chapter(self, chapter_id: str) -> list[StoryBeat]:
        """The rows, for callers that need addresses rather than serialisation."""
        return list(
            self.session.exec(
                select(StoryBeat)
                .where(StoryBeat.chapter_id == chapter_id)
                .order_by(StoryBeat.position)
            ).all()
        )

    def get(self, beat_id: str) -> StoryBeat | None:
        return self.session.get(StoryBeat, beat_id)

    def count_by_chapter(self, chapter_id: str) -> int:
        return self.session.exec(
            select(func.count(StoryBeat.id)).where(StoryBeat.chapter_id == chapter_id)
        ).one()

    # ── writes ───────────────────────────────────────────────────────────────

    def append(
        self,
        chapter_id: str,
        *,
        role: str,
        content: str,
        parent_beat_id: str | None = None,
        source_job_id: str | None = None,
        tts_source_job_id: str | None = None,
        audio_path: str | None = None,
        extra: dict | None = None,
        alternates: list[dict] | None = None,
        active_index: int = 0,
    ) -> StoryBeat:
        """Add a beat at the end of the chapter and return its row.

        Position is `max(position) + 1` rather than `count(*)` — the two differ
        after a delete, and reusing an existing position would collide with the
        index the ordering relies on.
        """
        last = self.session.exec(
            select(StoryBeat.position)
            .where(StoryBeat.chapter_id == chapter_id)
            .order_by(StoryBeat.position.desc())
            .limit(1)
        ).first()
        beat = StoryBeat(
            id=str(uuid.uuid4()),
            chapter_id=chapter_id,
            position=(last + 1) if last is not None else 0,
            parent_beat_id=parent_beat_id,
            role=role,
            content=content,
            audio_path=audio_path,
            source_job_id=source_job_id,
            tts_source_job_id=tts_source_job_id,
            alternates=alternates or [],
            active_index=active_index,
            extra=extra or {},
        )
        self.session.add(beat)
        return beat

    def replace_all(self, chapter_id: str, beats: list[dict]) -> list[StoryBeat]:
        """Rewrite a chapter's whole beat list from the JSON shape.

        The bulk path — used by reorder, by propagate, and by the migration's
        own repair. Delete-then-insert is deliberate rather than an upsert:
        reorder moves every row's position, and an upsert loop that stops halfway
        leaves a half-renumbered chapter.
        """
        for row in self.session.exec(
            select(StoryBeat).where(StoryBeat.chapter_id == chapter_id)
        ).all():
            self.session.delete(row)

        created: list[StoryBeat] = []
        for position, beat in enumerate(beats):
            extra = {k: v for k, v in beat.items() if k not in _COLUMN_KEYS}
            row = StoryBeat(
                id=beat.get("id") or str(uuid.uuid4()),
                chapter_id=chapter_id,
                position=position,
                parent_beat_id=beat.get("parent_beat_id"),
                role=beat.get("role") or "narrator",
                content=beat.get("content") or "",
                audio_path=beat.get("audio_path"),
                source_job_id=beat.get("source_job_id"),
                tts_source_job_id=beat.get("tts_source_job_id"),
                alternates=list(beat.get("alternates") or []),
                active_index=beat.get("active_index") or 0,
                extra=extra,
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(row)
            created.append(row)
        return created

    def set_audio(
        self,
        beat_id: str,
        *,
        audio_path: str,
        tts_source_job_id: str | None = None,
    ) -> StoryBeat | None:
        """Point an existing beat at a rendered audio file.

        The chapter-narration update path. A TTS job that lands on a chapter
        whose last beat is already a `tts` beat replaces that beat's audio
        rather than stacking a second one — which is what the handler's old
        dict-merge did, and it only worked because the JSON array and the rows
        happened to agree. `audio_path` is required rather than optional because
        clearing it would mean "the file is gone", which is `delete`'s job to
        decide, not a side effect of a finished job.
        """
        row = self.get(beat_id)
        if row is None:
            return None
        row.audio_path = audio_path
        if tts_source_job_id:
            row.tts_source_job_id = tts_source_job_id
        self.session.add(row)
        return row

    def delete(self, beat_id: str) -> None:
        row = self.session.get(StoryBeat, beat_id)
        if row is not None:
            self.session.delete(row)
