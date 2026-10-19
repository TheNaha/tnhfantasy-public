"""Resolution of AgentProfile rows and their AgentPromptVariant overrides.

A variant is a named alternate prompt for an agent. Resolution order is:

* an explicit ``variant:<slug>`` reference selects that variant directly
  (used by the simulator and any API that previews a variant);
* an agent slug selects the agent's active variant, falling back to the
  profile's own ``system_prompt_template`` when no variant is active.

Sampling overrides follow the same specificity: a variant value wins, then the
profile value, and ``None`` means "inherit the chat/story or global default".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from core.entities import AgentProfile, AgentPromptVariant

VARIANT_PREFIX = "variant:"


def clean_agent_slug(raw: str) -> str:
    """Lowercase and collapse anything that is not [a-z0-9_] into underscores."""
    return re.sub(r"[^a-z0-9_]+", "_", (raw or "").lower().strip()).strip("_")


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
) -> ResolvedAgent | None:
    """Resolve an agent slug or ``variant:<slug>`` reference with optional variant_slug override.

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
