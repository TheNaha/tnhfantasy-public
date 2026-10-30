# Proposal

## Why

The Story Sandbox is an AI Dungeon–style interactive document editor with chapters, branches, illustrations, and comic/webtoon export. Its contract — chapter branching, illustration triggers, comic export job events, and sandbox state — has no single behavior contract. Drift between the sandbox editor, comic exporter job events, and the frontend export UI causes broken exports or missing illustrations. A capability-owned spec is needed so story-sandbox drift is caught before it reaches users.

## What Changes

- Create capability spec `specs/story-sandbox/spec.md` documenting the story sandbox contract: chapters, branches, illustration triggers, comic/webtoon export job events, and sandbox state.
- No implementation changes; this spec pins existing behavior.

## Capabilities

### New Capabilities

- `story-sandbox`: The story sandbox contract — AI Dungeon–style chapter editor, branches, illustration triggers, comic/webtoon export job events, and sandbox state.

### Modified Capabilities

- None.

## Impact

- `backend_v2/services/comic_exporter.py` — story chapter → panels → web-comic/PDF export.
- `backend_v2/services/image_submission.py` — illustration job submission from sandbox.
- `frontend_v2/` — story sandbox editor and export UI.
- `backend_v2/core/entities.py` — Story, Chapter, Branch entity definitions.
