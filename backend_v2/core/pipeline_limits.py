"""Single source of truth for the roleplay chat pipeline's numbers.

Every limit the 6-stage pipeline enforces lived in more than one place: the
manifest served to the LLM Studio UI (`services/chat_pipeline.py`), the entity
column defaults (`core/entities.py`), the decision schema's thresholds
(`services/decision_schema.py`), and hardcoded literals in the executor
(`services/job_processing.py`). Nothing tied them together, so the UI could
quote a number the code did not use — and the "4 turns" in the manifest, the
"4" in the `Chat.max_autonomous_turns` default, and the hardcoded
`continuation_count < 4` were three copies of one fact that had to be changed
together by hand.

This module is deliberately a leaf: it imports nothing, so `core/entities.py`
can import it without creating a cycle, and so anything can import it.

The manifest imports from here, and so does the code. `GET /llm/pipeline`
therefore cannot report a limit the pipeline does not enforce.
"""

from __future__ import annotations

# The autonomous multi-turn budget: how many turns one interaction may chain
# before control returns to the user. Also the default for
# `Chat.max_autonomous_turns` / `Story.max_autonomous_turns`.
MAX_AUTONOMOUS_TURNS = 4

# How many times a single truncated generation may be continued. Continuations
# are deliberately NOT counted as turns — they finish one turn that was cut
# off, they do not start a new one.
MAX_CONTINUATIONS = 4

# How many images one exchange may spend when the chat/story sets no limit.
MAX_AGENTIC_IMAGES = 2

# Probability above which a Statekeeper gate is considered to have fired, and
# therefore which fields the Updater is allowed to write.
UPDATER_GATE_THRESHOLD = 0.55

# Probability above which the Auditor asks for a scene illustration.
IMAGE_TRIGGER_THRESHOLD = 0.65

# Minimum `continue_chain_probability` for an autonomous turn to happen, per
# `Chat.director_autonomy_level`. "strict" disables chaining outright.
AUTONOMY_CHAIN_THRESHOLDS: dict[str, float] = {
    "strict": 1.0,
    "balanced": 0.65,
    "cinematic": 0.50,
}

# Wall-clock budget for one Director decision (triage, audit, or chaining).
DIRECTOR_TIMEOUT_SECONDS = 15.0

# Wall-clock budget for the stage-local LLM calls the Director makes.
STAGE_TIMEOUT_SECONDS = 15.0
