# Design

## Context

The Story Sandbox already exists as chapters, branches, illustrations, and comic/webtoon export via `services/comic_exporter.py`, `services/image_submission.py` (illustration job submission), and frontend editor/export UI. Entity definitions live in `core/entities.py`. There is no single spec stating branch structure, illustration triggers, or export job events. See `proposal.md` - Why for motivation.

## Goals / Non-Goals

**Goals:**

- A capability spec for `story-sandbox` centralizing the sandbox contract so drift between editor, illustration triggers, and export is detectable.
- Requirements precise enough to anchor future machine-checkable tests (chapter branching, export job events).

**Non-Goals:**

- Changing comic exporter, image submission, or sandbox editor code.
- Adding new export formats beyond comic/webtoon/PDF.
- Changing story entity schema.

## Decisions

### Decision: Chapter branching is branch-scoped, not a flat list

**Approach:** Spec that chapters belong to branches with position within the branch, rather than being a flat ordered list.

**Rationale:** Branching is a core sandbox feature; spec makes the structure explicit so future changes don't flatten it.

**Alternatives considered:**
- Flat chapter list with a branch tag: rejected, because branching semantics (position within branch) matter for export ordering.

### Decision: Sandbox state persists via mutation, not transient UI state

**Approach:** Spec that chapters, branches, and illustrations persist through `updateStory.mutate`-style mutations, not transient UI state.

**Rationale:** Frontend convention states World Vault relationships persist through mutations, not transient UI state; spec applies it to the sandbox.

**Alternatives considered:**
- Storing sandbox drafts in Zustand: rejected, because frontend conventions forbid storing server data in Zustand.

## Risks / Trade-offs

- [Risk] Comic export job events could be missed if the exporter doesn't emit them per panel. [Mitigation] Spec requires job events; exporter conformance can be tested later.
- [Risk] Illustration triggers depend on the visual threshold from the Director pipeline. [Mitigation] Spec references the threshold contract; a future change can pin the exact value.

## Migration Plan

None — additive spec only, no data migration, no behavior change, no rollback needed.

## Open Questions

None.
