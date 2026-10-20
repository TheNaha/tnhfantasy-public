"""Resolution of AgentProfile rows and their AgentPromptVariant overrides.

A variant is a named alternate prompt for an agent. Resolution order is:

* an explicit ``variant:<slug>`` reference selects that variant directly
  (used by the simulator and any API that previews a variant);
* a variant whose scope matches the current context — the model that will
  answer, the Statekeeper gate that fired — is preferred;
* an agent slug selects the agent's active variant, falling back to the
  profile's own ``system_prompt_template`` when no variant is active.

Sampling overrides follow the same specificity: a variant value wins, then the
profile value, and ``None`` means "inherit the chat/story or global default".

Scoping
-------

A variant may carry two scopes:

``model_scope``
    The model (or model role) the variant is FOR. ``None`` means "any model".
    This is what makes "many different variations of system prompts for
    various LLMs" expressible: before it, the only axis was the scene, so one
    prompt served every model that answered.

``gate_scope``
    The Statekeeper gate the variant is FOR. ``None`` means "any gate". The
    Updater's *schema* was already gate-specific — an unfired gate's field was
    absent from the JSON the model was shown — so this is the prompt half:
    the extractor is told in words what shifted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from sqlmodel import Session, select

from core.entities import AgentProfile, AgentPromptVariant
from infrastructure.logging import get_logger

logger = get_logger("agent_variants")

VARIANT_PREFIX = "variant:"


def clean_agent_slug(raw: str) -> str:
    """Lowercase and collapse anything that is not [a-z0-9_] into underscores."""
    return re.sub(r"[^a-z0-9_]+", "_", (raw or "").lower().strip()).strip("_")


def _scope_set(values: Optional[Iterable[str]]) -> set[str]:
    return {(v or "").strip().lower() for v in (values or []) if (v or "").strip()}


def variant_applies(
    variant: AgentPromptVariant,
    *,
    model_scopes: Optional[Iterable[str]] = None,
    gate_scopes: Optional[Iterable[str]] = None,
) -> bool:
    """Does this variant apply in this context?

    A scoped variant applies only when its scope is in the applicable set. An
    unscoped variant applies everywhere. The applicable model set is the model
    that will answer TOGETHER WITH its role, so a variant scoped to `"rp"`
    matches whichever prose model is bound to the rp role, and a variant
    scoped to a specific model id matches only that one.
    """
    variant_model = (getattr(variant, "model_scope", None) or "").strip().lower()
    if variant_model:
        if variant_model not in _scope_set(model_scopes):
            return False

    variant_gate = (getattr(variant, "gate_scope", None) or "").strip().lower()
    if variant_gate:
        if variant_gate not in _scope_set(gate_scopes):
            return False

    return True


def scoped_variants(
    session: Optional[Session],
    agent_slug: str,
    *,
    model_scopes: Optional[Iterable[str]] = None,
    gate_scopes: Optional[Iterable[str]] = None,
) -> list[AgentPromptVariant]:
    """The variants of an agent that apply in this context.

    Ordered so the most specific wins: a variant scoped to both the model and
    the gate, then one scoped to either, then an unscoped one. Within a
    tier, the active variant first, then slug.
    """
    if not session or not agent_slug:
        return []
    try:
        profile = session.exec(
            select(AgentProfile).where(AgentProfile.slug == agent_slug)
        ).first()
        if not profile:
            return []

        variants = session.exec(
            select(AgentPromptVariant).where(AgentPromptVariant.agent_id == profile.id)
        ).all()
    except Exception as exc:
        logger.debug("scoped_variants_failed", agent=agent_slug, error=str(exc))
        return []

    def _specificity(v: AgentPromptVariant) -> int:
        score = 1
        if (getattr(v, "model_scope", None) or "").strip():
            score += 1
        if (getattr(v, "gate_scope", None) or "").strip():
            score += 1
        return score

    applicable = [
        v for v in variants if variant_applies(v, model_scopes=model_scopes, gate_scopes=gate_scopes)
    ]
    applicable.sort(
        key=lambda v: (
            -_specificity(v),
            0 if v.is_active else 1,
            v.slug,
        )
    )
    return applicable


@dataclass(frozen=True)
class ResolvedAgent:
    """An agent profile plus the variant (if any) that overrides it."""

    profile: AgentProfile
    variant: AgentPromptVariant | None = None

    @property
    def slug(self) -> str:
        return self.profile.slug

    @property
    def name(self) -> str:
        return self.profile.name

    @property
    def variant_slug(self) -> str | None:
        return self.variant.slug if self.variant else None

    @property
    def prompt_template(self) -> str:
        if self.variant is not None:
            return self.variant.system_prompt_template
        return self.profile.system_prompt_template

    def _pick(self, attribute: str) -> Any:
        if self.variant is not None:
            value = getattr(self.variant, attribute, None)
            if value is not None:
                return value
        return getattr(self.profile, attribute, None)

    def sampler_overrides(self) -> dict[str, Any]:
        """Return workflow sampler keys mapped from the agent's field names."""
        samplers: dict[str, Any] = {}
        temperature = self._pick("temperature")
        if temperature is not None:
            samplers["temperature"] = temperature
        top_p = self._pick("top_p")
        if top_p is not None:
            samplers["top_p"] = top_p
        # AgentProfile/AgentPromptVariant spell it `max_tokens`; workflows
        # speak `max_output_tokens`.
        max_tokens = self._pick("max_tokens")
        if max_tokens is not None:
            samplers["max_output_tokens"] = max_tokens
        return samplers


def resolve_agent(
    session: Session,
    reference: str | None,
    *,
    variant_slug: str | None = None,
    require_enabled: bool = True,
    model_scopes: Optional[Iterable[str]] = None,
    gate_scopes: Optional[Iterable[str]] = None,
) -> ResolvedAgent | None:
    """Resolve an agent slug or ``variant:<slug>`` reference with optional variant_slug override.

    ``model_scopes`` and ``gate_scopes`` narrow which variants are eligible.
    A variant scoped to a model that will not answer, or to a gate that did
    not fire, is not a candidate: it is a prompt written for a different
    situation. The most specific eligible variant wins — one scoped to both
    the model and the gate, then one scoped to either, then an unscoped one.

    Returns ``None`` when the reference matches nothing, so callers keep their
    existing "unknown speaker" fallbacks instead of raising mid-generation.
    """
    ref = (reference or "").strip()
    if not ref:
        return None

    explicit_variant_slug = None
    if ref.lower().startswith(VARIANT_PREFIX):
        explicit_variant_slug = ref[len(VARIANT_PREFIX):].strip()
        if not explicit_variant_slug:
            return None

    target_variant = explicit_variant_slug or variant_slug

    if explicit_variant_slug:
        variant = session.exec(
            select(AgentPromptVariant).where(AgentPromptVariant.slug == explicit_variant_slug)
        ).first()
        if variant is None:
            return None
        profile = session.get(AgentProfile, variant.agent_id)
        if profile is None:
            return None
        if require_enabled and not profile.enabled:
            return None
        return ResolvedAgent(profile=profile, variant=variant)

    stmt = select(AgentProfile).where(AgentProfile.slug == ref)
    if require_enabled:
        stmt = stmt.where(AgentProfile.enabled == True)  # noqa: E712
    profile = session.exec(stmt).first()
    if profile is None:
        return None

    variant = None
    if target_variant and target_variant.lower() != "default":
        variant = session.exec(
            select(AgentPromptVariant).where(
                AgentPromptVariant.agent_id == profile.id,
                AgentPromptVariant.slug == target_variant,
            )
        ).first()

    if variant is None:
        # No explicit choice. A variant SCOPED to the model that will answer,
        # or to a gate that fired, is a better fit than the agent's generic
        # active variant — it was written for exactly this situation, and the
        # scope IS its activation.
        #
        # An unscoped INACTIVE variant is never auto-applied. The built-in
        # sub-variants are seeded that way on purpose: they are examples of
        # what a variant looks like, and Laya picks them by name. Auto-
        # applying the first one alphabetically would silently replace the
        # agent's default persona with an example.
        scoped = [
            v
            for v in scoped_variants(
                session,
                ref,
                model_scopes=model_scopes,
                gate_scopes=gate_scopes,
            )
            if (getattr(v, "model_scope", None) or "").strip()
            or (getattr(v, "gate_scope", None) or "").strip()
        ]
        if scoped:
            variant = scoped[0]
        else:
            variant = session.exec(
                select(AgentPromptVariant)
                .where(
                    AgentPromptVariant.agent_id == profile.id,
                    AgentPromptVariant.is_active == True,  # noqa: E712
                )
                .order_by(AgentPromptVariant.updated_at.desc())
                .limit(1)
            ).first()

    return ResolvedAgent(profile=profile, variant=variant)


def activate_variant(session: Session, variant: AgentPromptVariant) -> None:
    """Make ``variant`` the only active variant for its agent."""
    siblings = session.exec(
        select(AgentPromptVariant).where(
            AgentPromptVariant.agent_id == variant.agent_id,
            AgentPromptVariant.id != variant.id,
            AgentPromptVariant.is_active == True,  # noqa: E712
        )
    ).all()
    for sibling in siblings:
        sibling.is_active = False
        session.add(sibling)
    variant.is_active = True
    session.add(variant)
