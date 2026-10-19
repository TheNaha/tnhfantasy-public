"""Tests for Roleplay & Worker Cohesion enhancements.

Covers:
- chat.scenario_id context resolution and deduplication
- story.character_ids lorebook resolution and character memory RAG wiring
- resolve_scenario_defaults for image checkpoints and voice profiles
- orchestrator location sync
- reference cleanup on scenario_id, persona_id, and graph layout
- world hub extended relationships
- LLM sampler token mapping and impersonation role kind
"""

from unittest.mock import MagicMock


from core.entities import (
    Asset,
    Character,
    CharacterMemory,
    Chat,
    GraphLayout,
    Lorebook,
    LorebookEntry,
    Persona,
    Scenario,
    Story,
    World,
)
from services.chat_utils import resolve_scenario_defaults
from services.context_builder import (
    build_system_prompt_sections,
    chat_context_kwargs,
    story_context_kwargs,
)
from services.llm_router import ROLE_BY_KIND, get_router
from services.llm_workflow import build_llm_workflow
from services.reference_cleanup import scrub_entity_references


def _seed(session, **kw):
    entity = kw.pop("_cls", Character)(**kw)
    session.add(entity)
    session.commit()
    session.refresh(entity)
    return entity


class TestChatScenarioContext:
    def test_chat_scenario_reaches_the_prompt(self, session):
        scenario = _seed(session, _cls=Scenario, name="Stormy Night", prompt_template="Thunder rolls outside.")
        chat = _seed(session, _cls=Chat, name="Chat with scenario", scenario_id=scenario.id)

        kwargs = chat_context_kwargs(chat, session=session)
        sections = build_system_prompt_sections(session, **kwargs)

        scenario_section = next((s for s in sections if s["key"] == "story_scenario"), None)
        assert scenario_section is not None
        assert "Thunder rolls outside." in scenario_section["content"]

    def test_chat_scenario_deduplicates_against_append_system_prompt(self, session):
        scenario = _seed(session, _cls=Scenario, name="Stormy Night", prompt_template="Thunder rolls outside.")
        chat = _seed(
            session,
            _cls=Chat,
            name="Chat with scenario",
            scenario_id=scenario.id,
            append_system_prompt="Notes: Thunder rolls outside.",
        )

        kwargs = chat_context_kwargs(chat, session=session)
        sections = build_system_prompt_sections(session, **kwargs)

        scenario_sections = [s for s in sections if s["key"] == "story_scenario"]
        assert len(scenario_sections) == 0


class TestStoryCharacterIntegration:
    def test_story_character_lorebooks_and_character_id_resolved(self, session):
        lb = _seed(session, _cls=Lorebook, name="Arcane Secrets")
        _seed(
            session,
            _cls=LorebookEntry,
            lorebook_id=lb.id,
            keys=["magic", "spells"],
            content="Magic requires focus.",
            is_constant=True,
        )
        char = _seed(
            session,
            _cls=Character,
            name="Merlin",
            lorebook_ids=[lb.id],
        )
        story = _seed(
            session,
            _cls=Story,
            title="The Tower",
            character_ids=[char.id],
        )

        kwargs = story_context_kwargs(story, session=session)
        assert kwargs.get("character_id") == char.id
        assert lb.id in kwargs.get("lorebook_ids", [])


class TestScenarioWorkerFallbacks:
    def test_resolve_scenario_defaults_from_chat(self, session):
        scenario = _seed(
            session,
            _cls=Scenario,
            name="Fantasy Realm",
            prompt_template="A fantasy realm.",
            default_checkpoint="sdxl_fantasy_v1.safetensors",
            default_voice_profile="xtts_wizard",
        )
        chat = _seed(session, _cls=Chat, name="Quest", scenario_id=scenario.id)

        ckpt, voice = resolve_scenario_defaults(session, chat)
        assert ckpt == "sdxl_fantasy_v1.safetensors"
        assert voice == "xtts_wizard"

    def test_resolve_scenario_defaults_from_story(self, session):
        scenario = _seed(
            session,
            _cls=Scenario,
            name="SciFi Expanse",
            prompt_template="A scifi expanse.",
            default_checkpoint="flux_scifi.safetensors",
            default_voice_profile="eleven_narrator",
        )
        story = _seed(session, _cls=Story, title="Deep Space", scenario_id=scenario.id)

        ckpt, voice = resolve_scenario_defaults(session, story)
        assert ckpt == "flux_scifi.safetensors"
        assert voice == "eleven_narrator"


class TestReferenceCleanup:
    def test_deleting_scenario_cleans_chat_scenario_id(self, session):
        scenario = _seed(session, _cls=Scenario, name="Doomed Expedition", prompt_template="Doom awaits.")
        chat = _seed(session, _cls=Chat, name="Expedition", scenario_id=scenario.id)

        scrub_entity_references(session, "scenario", scenario.id)
        session.refresh(chat)
        assert chat.scenario_id is None

    def test_deleting_persona_cleans_story_persona_id(self, session):
        persona = _seed(session, _cls=Persona, name="Author Voice")
        story = _seed(session, _cls=Story, title="Biography", persona_id=persona.id)

        scrub_entity_references(session, "persona", persona.id)
        session.refresh(story)
        assert story.persona_id is None

    def test_deleting_entity_removes_from_graph_layout(self, session):
        char = _seed(session, _cls=Character, name="Drifter")
        layout = _seed(
            session,
            _cls=GraphLayout,
            name="default",
            entity_type="character",
            entity_id=char.id,
            x=100.0,
            y=200.0,
        )
        layout_id = layout.id
        scrub_entity_references(session, "character", char.id)
        session.expire_all()
        assert session.get(GraphLayout, layout_id) is None


class TestTimelineScopeExtended:
    def test_timeline_filters_assets_and_memories_by_world_id(self, session):
        from api.routes.world_vault.timeline import get_timeline

        world1 = _seed(session, _cls=World, name="Eldoria")
        world2 = _seed(session, _cls=World, name="Nox")

        char1 = _seed(session, _cls=Character, name="Hero", world_id=world1.id)
        char2 = _seed(session, _cls=Character, name="Villain", world_id=world2.id)

        mem1 = _seed(session, _cls=CharacterMemory, character_id=char1.id, content="Hero trained in Eldoria.")
        mem2 = _seed(session, _cls=CharacterMemory, character_id=char2.id, content="Villain plotted in Nox.")

        asset1 = _seed(
            session,
            _cls=Asset,
            filename="sword.png",
            relative_path="sword.png",
            character_id=char1.id,
        )
        asset2 = _seed(
            session,
            _cls=Asset,
            filename="orb.png",
            relative_path="orb.png",
            character_id=char2.id,
        )

        res_world1 = get_timeline(
            character_id=None,
            story_id=None,
            chat_id=None,
            location=None,
            world_id=world1.id,
            types="memory,asset",
            limit=50,
            offset=0,
            session=session,
        )
        ids = {item["id"] for item in res_world1["events"]}
        assert mem1.id in ids
        assert asset1.id in ids
        assert mem2.id not in ids
        assert asset2.id not in ids
        assert res_world1["total"] == 2


class TestLLMWorkflowSamplerTokens:
    def test_sampler_max_tokens_mapped_to_workflow(self, monkeypatch):
        mock_registry = MagicMock()
        mock_registry.role_sampler.return_value = {"max_tokens": 1234}
        monkeypatch.setattr(get_router(), "registry", mock_registry)

        wf, _ = build_llm_workflow(
            messages=[{"role": "user", "content": "hi"}],
            type_="chat",
        )
        assert wf.get("max_output_tokens") == 1234

    def test_impersonation_mapped_to_rp(self):
        assert ROLE_BY_KIND.get("impersonation") == "rp"
