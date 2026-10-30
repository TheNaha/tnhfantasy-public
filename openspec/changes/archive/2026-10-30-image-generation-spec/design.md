# Design

## Context

Image generation already exists across `services/image_submission.py` (job submission), `services/workflow_builder.py` (ComfyUI workflow construction), `services/comic_exporter.py` (chapter→comic export), `services/asset_reconciler.py` (image finalization), `services/engines/` (Modal/Beam clients), and `deployables/` (worker workflow envelopes). There is no single spec stating the submission contract or gallery metadata behavior. See `proposal.md` - Why for motivation.

## Goals / Non-Goals

**Goals:**

- A capability spec for `image-generation` centralizing the image generation contract so drift between submission, workflow envelopes, and provider output is detectable.
- Requirements precise enough to anchor future machine-checkable tests (workflow envelope, SaveAudio output, gallery metadata source).

**Non-Goals:**

- Changing job submission code, workflow builder, or comic exporter behavior.
- Adding new providers or deployables.
- Changing ComfyUI worker deployment.

## Decisions

### Decision: Single submission path via image_submission

**Approach:** Spec that all image jobs go through `submit_image_job`, which resolves checkpoint, builds workflow, validates, creates job, and enqueues.

**Rationale:** This is already the documented helper; making it explicit prevents duplicate submission paths that drift from each other.

**Alternatives considered:**
- Allowing each caller to build its own workflow: rejected, because it would recreate the drift the spec is meant to prevent.

### Decision: Gallery metadata source is the SceneGraphSpec when present

**Approach:** When a SceneGraphSpec is present, gallery metadata reflects it; otherwise the stock prompt-and-parameters path is used unchanged.

**Rationale:** This is existing behavior in `image_submission.py`; spec clarifies which source wins.

**Alternatives considered:**
- Always using the stock path: rejected, because SceneGraphSpec-driven illustration (from the Illustrator agent) depends on it.

## Risks / Trade-offs

- [Risk] Workflow envelope contract (`execution_success` vs `executing{null}`) is provider-dependent; a provider that emits the wrong status breaks job completion detection. [Mitigation] Spec states the contract; provider conformance can be tested later.
- [Risk] SaveAudio producing audio (not images) differs from the image path; callers must not assume image output. [Mitigation] Spec states the distinction explicitly.

## Migration Plan

None — additive spec only, no data migration, no behavior change, no rollback needed.

## Open Questions

None.
