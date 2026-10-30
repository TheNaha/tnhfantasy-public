# Tasks

## 1. Machine-checkable limit consistency test

- [x] 1.1 Create `backend_v2/tests/test_chat_pipeline_limit_drift.py` that imports `core.pipeline_limits` and `core.entities`, AST-parses `services/chat_pipeline.py` for quoted limit values, and scans `pipeline_runner.py` and `pipeline_stages.py` for hardcoded literals matching `MAX_AUTONOMOUS_TURNS`, `IMAGE_TRIGGER_THRESHOLD`, `UPDATER_GATE_THRESHOLD`, and total-attempts-per-turn; assert all four sources agree. Verify `docker exec tnhcomfy-backend python -m pytest test_chat_pipeline_limit_drift.py -q` passes.

## Workflow follow-up

- After the change is reviewed and approved, run `/opsx-apply` to implement the test.
- Archive the change once the test is merged and CI green.
