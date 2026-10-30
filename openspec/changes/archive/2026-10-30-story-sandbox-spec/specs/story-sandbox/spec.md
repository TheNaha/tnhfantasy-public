# Spec Delta

## Purpose

Defines the Story Sandbox contract so chapter branching, illustration triggers, comic/webtoon export job events, and sandbox state stay aligned between the editor and export paths.

## ADDED Requirements

### Requirement: Chapter branching

A Story SHALL contain chapters that can branch, with each chapter tracking its parent branch and position in the branch sequence.

#### Scenario: Chapter belongs to a branch

- **WHEN** a chapter is created in a story
- **THEN** it has a branch identifier and position within that branch

### Requirement: Illustration triggers

Illustration SHALL fire when a scene's visual threshold is crossed, formulating a ComfyUI visual prompt for the scene.

#### Scenario: Illustration fires at visual threshold

- **WHEN** a story scene's visual threshold is crossed
- **THEN** an illustration job is submitted with a ComfyUI visual prompt

### Requirement: Comic/webtoon export job events

Exporting a story chapter to comic/webtoon format SHALL emit job events as panels, speech bubbles, and formatted web-comic or PDF output are generated.

#### Scenario: Comic export emits job events

- **WHEN** a story chapter is exported to comic/webtoon format
- **THEN** job events are emitted for panels, speech bubbles, and final output

### Requirement: Sandbox state

Story sandbox state SHALL persist chapters, branches, and illustrations through mutations, not transient UI state.

#### Scenario: Sandbox state persists through mutations

- **WHEN** a story is edited through the sandbox
- **THEN** chapters, branches, and illustrations are persisted via mutation, not held only in UI state
