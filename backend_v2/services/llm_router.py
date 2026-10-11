"""The rp/util router: which model serves which request.

The two-model split comes from the models themselves. An rp model is chosen for
in-character prose; the same finetunes get *worse* at structured output, tool
calls and vision instruction-following. A `util` model is the opposite. Sending
everything to the rp model is why the roleplay quality and the agentic quality
could not both be good, and it is the reason the registry has two roles.

This module owns exactly one decision — ``job kind -> role`` — and everything
else (which model is the role's primary, its sampler, its URL) comes from
`modal_llm/registry.py`, so changing a model never means touching this file.

Adding a new job kind means adding it to `ROLE_BY_KIND` below; the default keeps
it working (see `role_for_kind`), so a forgotten kind is a routing choice rather
than a crash.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

# `registry.py` lives in `backend_v2/modal_llm/`, which is INSIDE the deployable
# unit on purpose. It used to sit at the repo root, and the backend resolved it
# with `parents[2]` — the repo root in development, `/` inside the container,
# where the Docker build context is `backend_v2/` and there is no repo root
# above it. That produced `/modal_llm/models.json`, a path present in no
# deployment, and `GET /llm/routing` 500ed while every test passed.
_REGISTRY_DIR = Path(__file__).resolve().parents[1] / "modal_llm"
if str(_REGISTRY_DIR) not in sys.path:
    sys.path.insert(0, str(_REGISTRY_DIR))

from registry import Registry, load  # noqa: E402

# --------------------------------------------------------------------------
# Job kind -> role.
#
# The keys are the `type` strings `build_llm_workflow` already carries on every
# LLM job, so this table needs no new plumbing: the workflow already knows what
# it is.
#
# `rp`     — prose, in-character, long-form. Quality and willingness dominate.
# `util`   — structured: tool calls, extraction, summaries, image prompts,
#            captions. Instruction-following dominates, and vision is only
#            available here.
# --------------------------------------------------------------------------
ROLE_BY_KIND: Dict[str, str] = {
    # --- rp: the things a reader evaluates as prose -----------------------
    "chat_reply": "rp",
    "narrator": "rp",
    "story_continue": "rp",
    "story_action": "rp",
    # Suggesting a reply has to sound like the *character* would write it, so it
    # is prose even though it is short.
    "suggest_reply": "rp",

    # --- util: the things a program evaluates as structured output ---------
    # Writing chapters back into the DB is parsing, not prose.
    "story_parse": "util",
    # Generating an image prompt is descriptive and structured.
    "story_illustrate_prompt": "util",
    # Memory extraction runs after every turn and produces records; a finetune's
    # prose bias makes it drop fields.
    "memory_extraction": "util",
    # Anything the agentic tool loop drives, since rp finetunes handle tool
    # calling badly.
    "tool_call": "util",
    "agentic": "util",
    # Captioning / image reading. Only the `util` role ships a vision projector.
    "vision": "util",
    "caption": "util",
    "summarize": "util",
    "summary": "util",
}

#: What a kind that is not in the table above routes to.
DEFAULT_ROLE = "rp"


class LLMRouter:
    """Resolves a request to a model, given a registry and an optional override."""

    def __init__(self, registry: Registry):
        self.registry = registry

    # ------------------------------------------------------------------
    # The decision itself.
    # ------------------------------------------------------------------
    def role_for_kind(self, kind: Optional[str]) -> str:
        """The role a job kind belongs to.

        An unknown kind routes to `DEFAULT_ROLE` rather than raising: a new
        workflow kind that forgets this table still produces a reply, just from
        the prose model, which is a visible quality difference an operator can
        diagnose — not a crash, which would take the feature down entirely.
        """
        if not kind:
            return DEFAULT_ROLE
        return ROLE_BY_KIND.get(kind, DEFAULT_ROLE)

    def models_for_kind(
        self, kind: Optional[str], *, override: Optional[str] = None
    ) -> list:
        """The models that can serve this job kind, best first.

        `override` is a per-chat or per-story pin: when the user has explicitly
        chosen a model, it is honoured and the fallback chain stops there. An
        unknown override raises, because silently falling back to the registry
        would make the user's choice appear to be ignored.
        """
        if override:
            model = self.registry.get(override)
            return [model]
        return self.registry.enabled_for(self.role_for_kind(kind))

    def primary_for_kind(
        self, kind: Optional[str], *, override: Optional[str] = None
    ):
        """The one model to dispatch to."""
        ordered = self.models_for_kind(kind, override=override)
        if not ordered:
            raise LookupError(
                f"no enabled model for kind {kind!r} "
                f"(role {self.role_for_kind(kind)!r})"
            )
        return ordered[0]

    def fallback_chain(
        self, kind: Optional[str], *, override: Optional[str] = None
    ) -> list[str]:
        """Model ids in the order the caller should try them.

        Only the first entry is used today — the engines have no cross-model
        retry. The chain is exposed because the natural next step is a retry on
        the next model when the primary is unreachable, and building it now
        costs nothing.
        """
        return [m.id for m in self.models_for_kind(kind, override=override)]

    # ------------------------------------------------------------------
    # What the job needs from the model beyond its id.
    # ------------------------------------------------------------------
    def sampler_for(self, model_id: str) -> Dict[str, Any]:
        """The model's suggested sampler.

        Empty when the registry declares none, in which case the caller sends no
        sampler keys and the provider's defaults apply. A model-card sampler is
        a *suggestion* — per-chat overrides still win, which is why they are
        applied after this.
        """
        try:
            return dict(self.registry.get(model_id).sampler or {})
        except KeyError:
            return {}

    def describe(self) -> Dict[str, Any]:
        """For the settings UI: what each role currently resolves to."""
        return {
            "roles": {
                role: {
                    "primary": self.registry.primary(role).id,
                    "chain": [m.id for m in self.registry.enabled_for(role)],
                }
                for role in sorted(self.registry.fallback)
            },
            "kinds": dict(sorted(ROLE_BY_KIND.items())),
            "default_role": DEFAULT_ROLE,
        }


_ROUTER: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    """The process-wide router, built once.

    Cached because `load()` parses JSON on every call and this is reached on
    every chat message. The registry only changes on deploy, so a module-level
    cache cannot go stale in a way that matters.
    """
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = LLMRouter(load())
    return _ROUTER


def refresh_router() -> LLMRouter:
    """Rebuild the router from disk. For tests, and for a future 'reload
    registry' endpoint without a restart."""
    global _ROUTER
    _ROUTER = LLMRouter(load())
    return _ROUTER


def unresolved_kinds(kinds: Iterable[str]) -> list[str]:
    """Kind strings that would fall through to the default role.

    A guard for tests and for a startup check: every kind the codebase emits
    should be routed deliberately, because a mistake here is invisible — the
    reply still arrives, just from the wrong model.
    """
    return [k for k in kinds if k and k not in ROLE_BY_KIND]
