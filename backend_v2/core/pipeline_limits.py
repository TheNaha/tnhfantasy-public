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
# `Chat.max_autonomous_turns` — the only entity that has one. `Story` has no
# such column: a story continues inside its own chapters and has no Director
# turn budget of its own.
MAX_AUTONOMOUS_TURNS = 4

# How many generation ATTEMPTS one turn may make when the reply keeps
# coming back truncated.
#
# A truncated reply is continued, and a continuation is NOT a turn — it
# finishes a turn that was cut off, it does not start a new one. The budget
# counts attempts: the original plus its continuations.
#
# The constant used to be `MAX_CONTINUATIONS = 4` and the check was
# `continuation_count < 4`, which is 1 original + 4 continuations = 5
# attempts. The number 4 was read as "four continuations" by the code and as
# "four attempts" by everyone reading the manifest, and the manifest said
# "max_continuations: 4" — so the UI said "4 repeats" and the code did 4
# repeats on top of a first attempt. The name now says what it counts.
MAX_CONTINUATION_ATTEMPTS = 4

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

# How much scene authoring one chat may spend, in the cost units of
# `core.scene_graph.scene_spec_cost` — one unit is a 1024x1024 image at 20
# steps. A chat's own `scene_graph_budget` overrides this.
#
# It is not a price; it is a ceiling on how much a single scene may ask of
# the GPU, so one chat cannot author an unbounded number of large,
# many-step images.
DEFAULT_SCENE_GRAPH_BUDGET = 4.0
