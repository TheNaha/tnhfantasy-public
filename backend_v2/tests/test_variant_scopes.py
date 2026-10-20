"""Scoped variants — a prompt for a model, and a prompt for a gate.

The variant axis used to be one-dimensional: per agent, chosen by scene
content. "Many different variations of system prompts for various LLMs" needs
a second axis, because the router picks the model before the prompt is built
and a prompt that suits a large instruct model does not necessarily suit a
small finetune.

`model_scope` — the model (or model role) a variant is FOR. A variant with
no scope applies everywhere. A scoped one is only offered to Laya when the
agent it belongs to will actually answer with that model, and is applied
automatically when it matches.

`gate_scope` — the Statekeeper gate a variant is FOR. The Updater's schema
was already gate-specific (an unfired gate's field is absent from the JSON
the model is shown, and anything smuggled in is dropped on the way back);
this is the prompt half, so the extractor is told in words what shifted.
"""

from __future__ import annotations

import uuid


from sqlmodel import Session

from core.entities import AgentProfile, AgentPromptVariant


def _agent(session: Session, slug: str, name: str, template: str) -> AgentProfile:
    profile = AgentProfile(
        id=str(uuid.uuid4()),
        slug=slug,
        name=name,
        agent_type="generation",
        description=name,
        system_prompt_template=template,
        model_target="rp",
        is_builtin=False,
        enabled=True,
    )
    session.add(profile)
    session.commit()
    return profile


def _variant(
    session: Session,
    agent_id: str,
    slug: str,
    template: str,
    *,
    model_scope: str | None = None,
    gate_scope: str | None = None,
    is_active: bool = False,
    hint: str = "Use when the scene calls for it.",
) -> AgentPromptVariant:
    variant = AgentPromptVariant(
        id=str(uuid.uuid4()),
        agent_id=agent_id,
        slug=slug,
        name=slug,
        system_prompt_template=template,
        description="",
        selection_hint=hint,
        tags=[],
        is_active=is_active,
        is_builtin=False,
        model_scope=model_scope,
        gate_scope=gate_scope,
    )
    session.add(variant)
    session.commit()
    return variant


class TestModelScope:
    def test_a_scoped_variant_is_not_offered_for_another_model(self, session):
        from services.laya_questions import get_agent_variant_options

        profile = _agent(session, "character", "Character", "You are the character.")
        _variant(
            session,
            profile.id,
            "character-bigmodel",
            "You are the character, for a large model.",
            model_scope="artemis_31b",
        )
        _variant(
            session,
            profile.id,
            "character-smallmodel",
            "You are the character, for a small model.",
            model_scope="gemma3_12b",
        )

        options = get_agent_variant_options(
            session, "character", model_scopes={"artemis_31b", "rp"}
        )
        assert "character-bigmodel" in options
        assert "character-smallmodel" not in options, (
            "a variant written for a different model was offered to Laya"
        )

    def test_an_unscoped_variant_applies_to_every_model(self, session):
        from services.laya_questions import get_agent_variant_options

        profile = _agent(session, "character", "Character", "You are the character.")
        _variant(session, profile.id, "character-tense", "The moment is tense.")

        for scopes in ({"artemis_31b", "rp"}, {"gemma3_12b", "util"}, None):
            options = get_agent_variant_options(
                session, "character", model_scopes=scopes
            )
            assert "character-tense" in options, (
                f"an unscoped variant stopped applying for scopes {scopes}"
            )

    def test_a_role_scope_matches_whichever_model_holds_the_role(self, session):
        from services.laya_questions import get_agent_variant_options

        profile = _agent(session, "character", "Character", "You are the character.")
        _variant(
            session,
            profile.id,
            "character-prose",
            "You are the character, prose-tuned.",
            model_scope="rp",
        )

        # A different model, but still the one bound to the rp role.
        options = get_agent_variant_options(
            session, "character", model_scopes={"some_other_model", "rp"}
        )
        assert "character-prose" in options

        # The util role is a different role.
        options = get_agent_variant_options(
            session, "character", model_scopes={"some_other_model", "util"}
        )
        assert "character-prose" not in options

    def test_a_scoped_variant_is_applied_automatically(self, session):
        """The scope IS the activation.

        A scoped variant is a deliberate statement that this prompt is for
        this situation, so it applies without Laya having to choose it.
        """
        from services.agent_variants import resolve_agent

        profile = _agent(session, "character", "Character", "You are the character.")
        _variant(
            session,
            profile.id,
            "character-prose",
            "You are the character, prose-tuned.",
            model_scope="rp",
        )

        resolved = resolve_agent(
            session, "character", model_scopes={"artemis_31b", "rp"}
        )
        assert resolved is not None
        assert resolved.variant_slug == "character-prose"

    def test_an_unscoped_inactive_variant_is_not_auto_applied(self, session):
        """The built-in sub-variants are examples, not defaults.

        They are seeded with `is_active=False` so they do not replace the
        agent's own persona. Auto-applying the first one alphabetically would
        have done exactly that.
        """
        from services.agent_variants import resolve_agent

        profile = _agent(session, "character", "Character", "You are the character.")
        _variant(session, profile.id, "character-playful", "Keep it playful.")
        _variant(session, profile.id, "character-tense", "The moment is tense.")

        resolved = resolve_agent(session, "character")
        assert resolved is not None
        assert resolved.variant is None, (
            "an inactive example variant replaced the agent's default persona"
        )

    def test_an_active_unscoped_variant_is_the_default(self, session):
        from services.agent_variants import resolve_agent

        profile = _agent(session, "character", "Character", "You are the character.")
        _variant(
            session, profile.id, "character-default", "The default persona.",
            is_active=True,
        )

        resolved = resolve_agent(session, "character")
        assert resolved is not None
        assert resolved.variant_slug == "character-default"


class TestGateScope:
    def test_a_gate_scoped_variant_is_used_when_that_gate_fires(self, session):
        from services.agent_variants import resolve_agent

        profile = _agent(session, "updater", "Statekeeper", "You are the Statekeeper.")
        _variant(
            session,
            profile.id,
            "updater-mood",
            "The character's mood shifted. Update only the mood.",
            gate_scope="gate_character_mood",
        )

        resolved = resolve_agent(
            session,
            "updater",
            require_enabled=False,
            gate_scopes={"gate_character_mood"},
        )
        assert resolved is not None
        assert resolved.variant_slug == "updater-mood"

    def test_a_gate_scoped_variant_is_not_used_for_another_gate(self, session):
        from services.agent_variants import resolve_agent

        profile = _agent(session, "updater", "Statekeeper", "You are the Statekeeper.")
        _variant(
            session,
            profile.id,
            "updater-mood",
            "The character's mood shifted.",
            gate_scope="gate_character_mood",
        )

        resolved = resolve_agent(
            session,
            "updater",
            require_enabled=False,
            gate_scopes={"gate_world_state"},
        )
        assert resolved is not None
        assert resolved.variant_slug != "updater-mood"


class TestWithVariantsResponse:
    def test_it_carries_the_scopes_and_the_agent_id(self, session, client):
        """The cross-agent prompt library reads the scopes off this response.

        It also needs the variant's `agent_id` to save an edit, and the
        response did not carry it — so every save from the library would have
        posted to `PUT /agents/undefined/variants/<id>`.
        """
        profile = _agent(session, "character", "Character", "You are the character.")
        _variant(
            session,
            profile.id,
            "character-prose",
            "You are the character, prose-tuned.",
            model_scope="rp",
            gate_scope="gate_character_mood",
        )

        resp = client.get("/api/v2/llm/agents/with-variants")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        agent = next(a for a in body if a["slug"] == "character")
        entry = next(v for v in agent["variants"] if v["slug"] == "character-prose")

        assert entry["agent_id"] == profile.id
        assert entry["model_scope"] == "rp"
        assert entry["gate_scope"] == "gate_character_mood"


class TestUpdaterPromptNamesTheGate:
    def test_the_prompt_says_what_changed(self, session):
        from services.updater_service import build_state_updater_prompt

        prompt = build_state_updater_prompt(
            character_name="Aria",
            user_name="Player",
            current_location="The Bridge",
            current_time="Dusk",
            state_snapshot={},
            recent_lines=["Aria: We have to go."],
            triggered_gates=["gate_character_mood"],
            available_expressions=None,
        )
        assert "mood" in prompt.lower(), (
            "the Updater was not told which gate fired"
        )
        # And the schema is still restricted to that gate's fields.
        assert "character_mood" in prompt
        assert "inventory" not in prompt.lower().split("current state:")[0], (
            "a field from an unfired gate reached the schema"
        )

    def test_no_gates_means_no_claim(self, session):
        from services.updater_service import build_state_updater_prompt

        prompt = build_state_updater_prompt(
            character_name="Aria",
            user_name="Player",
            current_location=None,
            current_time=None,
            state_snapshot={},
            recent_lines=[],
            triggered_gates=[],
            available_expressions=None,
        )
        assert "the director detected" not in prompt.lower()
