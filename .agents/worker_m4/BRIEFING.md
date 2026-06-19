# BRIEFING — 2026-06-19T12:50:17Z

## Mission
Refactor backend_v2 database migrations and model service into modular components (database migrations, model downloader, model reconciliation, model civitai sync) and ensure backend compatibility and all tests passing.

## 🔒 My Identity
- Archetype: Worker M4
- Roles: implementer, qa, specialist
- Working directory: /home/thenaha/containers/stacks/comfyui/.agents/worker_m4
- Original parent: d4553e37-d267-4d5b-ba70-743258ac2a78
- Milestone: Milestone 4 (Backend Refactoring & Decoupling)

## 🔒 Key Constraints
- CODE_ONLY network mode: No external network access.
- Minimal change principle: Make the smallest edit that achieves the goal, keeping comments/docstrings intact where possible.
- DO NOT CHEAT: No hardcoding test results/dummy implementations.
- Write only to .agents/worker_m4 folder (metadata).

## Current Parent
- Conversation ID: d4553e37-d267-4d5b-ba70-743258ac2a78
- Updated: 2026-06-19T12:50:17Z

## Task Summary
- **What to build**: Refactor database.py to move migrations to new module `backend_v2/infrastructure/migrations/` and run migrations wrapped in SQL transactions. Refactor model_service.py to extract downloader, reconciliation, and CivitAI sync logic into separate files, with `ModelServiceV2` as a backward-compatible Facade. Adjust tests in test_model_service.py and verify via pytest.
- **Success criteria**: All tests pass, backend code compiles/runs, no regression, clean transaction-based migrations, correct sub-services and delegation.
- **Interface contracts**: /home/thenaha/containers/stacks/comfyui/backend_v2/infrastructure/database.py, /home/thenaha/containers/stacks/comfyui/backend_v2/services/model_service.py
- **Code layout**: /home/thenaha/containers/stacks/comfyui/backend_v2

## Change Tracker
- **Files modified**: None
- **Build status**: TBD
- **Pending issues**: None

## Quality Status
- **Build/test result**: TBD
- **Lint status**: TBD
- **Tests added/modified**: None

## Loaded Skills
- **Source**: none

## Key Decisions Made
- None yet

## Artifact Index
- /home/thenaha/containers/stacks/comfyui/.agents/worker_m4/ORIGINAL_REQUEST.md — Original request content
