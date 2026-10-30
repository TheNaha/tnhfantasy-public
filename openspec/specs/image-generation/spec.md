# image-generation Specification

## Purpose

Defines the image generation contract so ComfyUI job submission, workflow envelopes, checkpoint/Lora resolution, gallery metadata, asset reconciliation, and comic export events stay aligned between the backend and provider workers.

## Requirements

### Requirement: Job submission contract

The system SHALL build, validate, create, and enqueue an image job through a single submission path that resolves checkpoint, applies Lora, validates the workflow, creates the job, and enqueues it.

#### Scenario: Image job submission completes all stages

- **WHEN** `submit_image_job` is called with prompt, checkpoint, and optional lora
- **THEN** it resolves checkpoint, builds the workflow, validates it, creates the job, and enqueues it

### Requirement: Workflow envelope alignment

The ComfyUI workflow envelope SHALL end with `execution_success` (not `executing{null}`), and SaveAudio SHALL output an audio reference rather than images.

#### Scenario: Workflow ends with execution_success

- **WHEN** a ComfyUI prompt completes
- **THEN** the final execution status is `execution_success`

#### Scenario: SaveAudio produces audio reference

- **WHEN** a TTS workflow runs SaveAudio
- **THEN** the output is an audio reference, not an image reference

### Requirement: Gallery metadata reflects the scene spec

When a `SceneGraphSpec` is present, the workflow SHALL be rendered from it and gallery metadata SHALL reflect it; otherwise the stock prompt-and-parameters path SHALL be used unchanged.

#### Scenario: Scene graph spec drives workflow and metadata

- **WHEN** an image job carries a `SceneGraphSpec`
- **THEN** the workflow is rendered from the spec and gallery metadata reflects it

#### Scenario: Stock path when no scene graph spec

- **WHEN** an image job has no `SceneGraphSpec`
- **THEN** the stock prompt-and-parameters path is used unchanged

### Requirement: Comic export job events

Story chapter-to-panel comic export SHALL emit job events as chapters are converted to panels, speech bubbles, and formatted web-comic or PDF output.

#### Scenario: Comic export emits job events

- **WHEN** a story chapter is exported to comic/webtoon format
- **THEN** job events are emitted as panels and speech bubbles are generated
