## 2026-06-19T12:23:57Z
Your role is Worker M2 for the ComfyUI Wrapper Audit, Consolidation, and Repair project.
Your working directory is /home/thenaha/containers/stacks/comfyui/.agents/worker_m2.
Your task is to implement the Backend Foundation & DI Stabilization (Milestone 2) as outlined.
Specifically:
1. In /home/thenaha/containers/stacks/comfyui/backend_v2/config.py:
   - Add output_dir and input_dir fields to the Settings class. Use Pydantic's validation or model_validator to load from COMFY_OUTPUT_DIR / COMFY_INPUT_DIR (with COMFY_ prefix) and fallback to OUTPUT_DIR / INPUT_DIR if the COMFY_ prefixed variables are not set.
2. In the backend codebase, replace direct os.environ.get("OUTPUT_DIR") and os.environ.get("INPUT_DIR") accesses with calls to settings.output_dir and settings.input_dir. The relevant files are:
   - /home/thenaha/containers/stacks/comfyui/backend_v2/api/job_processing.py
   - /home/thenaha/containers/stacks/comfyui/backend_v2/api/routes/files.py
   - /home/thenaha/containers/stacks/comfyui/backend_v2/api/routes/statistics.py
   - /home/thenaha/containers/stacks/comfyui/backend_v2/infrastructure/image_processor.py
3. In /home/thenaha/containers/stacks/comfyui/backend_v2/core/events.py:
   - Add sequence_number: Optional[int] = None field to the Event class.
   - Include sequence_number in Event's to_dict() method.
   - In EventBus class: initialize an atomic sequence counter (self._sequence_counter = 0) and assign sequential numbers to each published event during publish().
4. In /home/thenaha/containers/stacks/comfyui/backend_v2/api/routes/websocket.py:
   - Implement a Socket.IO event handler @sio.event async def request_replay(sid, data) that allows clients to request events from the replay buffer having a sequence number greater than a client-provided last_sequence_number.
5. In /home/thenaha/containers/stacks/comfyui/backend_v2/api/error_handlers.py:
   - Unify all unhandled backend exceptions by adding StarletteHTTPException and raw Exception handlers to register_exception_handlers, translating them into standard JSON responses with {"error": ..., "code": ...}.
6. In /home/thenaha/containers/stacks/comfyui/backend_v2/services/job_submission_service.py:
   - Remove the unused HTTPException import.
7. Run the backend test suite via pytest to verify all tests continue to pass.
8. Document all changes and test results in /home/thenaha/containers/stacks/comfyui/.agents/worker_m2/handoff.md.
