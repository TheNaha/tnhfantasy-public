# Proposal

## Why

Image generation runs ComfyUI workflows against Modal, Beam, direct_url, and remote_agent workers through `services/image_submission.py`, `services/comic_exporter.py`, and the gallery/asset reconciler. The job submission contract — checkpoint resolution, workflow envelopes, SaveAudio vs image outputs, job events, and gallery metadata — has no single behavior contract. Drift between the backend submission path and provider workflow envelopes causes jobs to fail or produce empty outputs. A capability-owned spec is needed so image-generation drift is caught before it reaches users.

## What Changes

- Create capability spec `specs/image-generation/spec.md` documenting the image generation contract: job submission, workflow envelopes, checkpoint/Lora resolution, gallery metadata, asset reconciler, and comic export job events.
- No implementation changes; this spec pins existing behavior.

## Capabilities

### New Capabilities

- `image-generation`: The image generation contract — ComfyUI job submission, workflow envelopes, checkpoint/Lora resolution, gallery metadata, asset reconciler, and comic export job events.

### Modified Capabilities

- None.

## Impact

- `backend_v2/services/image_submission.py` — build, validate, create, enqueue image jobs.
- `backend_v2/services/workflow_builder.py` — ComfyUI workflow construction.
- `backend_v2/services/comic_exporter.py` — story chapter → panels → web-comic/PDF export.
- `backend_v2/services/asset_reconciler.py` — image finalization to /api/files.
- `backend_v2/services/engines/` — Modal/Beam engine clients.
- `deployables/` — ComfyUI and TTS worker workflow envelopes.
