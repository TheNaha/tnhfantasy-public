"""The user's own system-prompt blocks.

`system_prompts` in the config is a fixed set of keys the code looks up by
name, so it could not grow: adding a prompt meant editing the config
schema, the validation allow-list and the frontend's copy of the defaults,
and there was no way to remove one at all.

`system_prompt_library` is a list, so it can. These tests pin that a prompt
can be added, used, edited and removed, and that the built-in blocks are
untouched by any of it.
"""

from __future__ import annotations


import pytest

import config as app_config


class TestSystemPromptLibrary:
    def test_it_starts_empty(self, client):
        resp = client.get("/api/settings/system-prompts/library")
        assert resp.status_code == 200
        assert resp.json()["entries"] == []

    def test_a_prompt_can_be_added_and_is_usable(self, client):
        resp = client.post(
            "/api/settings/system-prompts/library",
            json={
                "key": "my_ritual",
                "label": "The Ritual",
                "category": "Roleplay",
                "prompt": "You always speak in the old dialect.",
            },
        )
        assert resp.status_code == 200, resp.text

        entries = client.get("/api/settings/system-prompts/library").json()["entries"]
        assert len(entries) == 1
        assert entries[0]["key"] == "my_ritual"
        assert entries[0]["label"] == "The Ritual"

        # And it is usable by key, like a built-in one.
        blocks = client.get("/api/settings/system-prompts").json()["blocks"]
        assert blocks["my_ritual"] == "You always speak in the old dialect."
        # The built-ins are untouched.
        assert "roleplay_default" in blocks

    def test_a_prompt_can_be_edited(self, client):
        client.post(
            "/api/settings/system-prompts/library",
            json={"key": "my_ritual", "label": "The Ritual", "prompt": "first"},
        )
        resp = client.put(
            "/api/settings/system-prompts/library/my_ritual",
            json={"key": "my_ritual", "label": "The Rite", "prompt": "second"},
        )
        assert resp.status_code == 200, resp.text

        blocks = client.get("/api/settings/system-prompts").json()["blocks"]
        assert blocks["my_ritual"] == "second"

    def test_a_prompt_can_be_removed(self, client):
        client.post(
            "/api/settings/system-prompts/library",
            json={"key": "my_ritual", "label": "The Ritual", "prompt": "first"},
        )
        resp = client.delete("/api/settings/system-prompts/library/my_ritual")
        assert resp.status_code == 200, resp.text

        entries = client.get("/api/settings/system-prompts/library").json()["entries"]
        assert entries == []
        blocks = client.get("/api/settings/system-prompts").json()["blocks"]
        assert "my_ritual" not in blocks

    def test_a_builtin_cannot_be_shadowed_or_removed(self, client):
        resp = client.post(
            "/api/settings/system-prompts/library",
            json={"key": "narrator", "label": "Hijack", "prompt": "mine"},
        )
        assert resp.status_code == 400, resp.text

        resp = client.delete("/api/settings/system-prompts/library/narrator")
        assert resp.status_code == 400, resp.text

    def test_a_duplicate_key_is_refused(self, client):
        client.post(
            "/api/settings/system-prompts/library",
            json={"key": "my_ritual", "label": "One", "prompt": "first"},
        )
        resp = client.post(
            "/api/settings/system-prompts/library",
            json={"key": "my_ritual", "label": "Two", "prompt": "second"},
        )
        assert resp.status_code == 400, resp.text

    def test_editing_a_missing_one_is_a_404(self, client):
        resp = client.put(
            "/api/settings/system-prompts/library/nope",
            json={"key": "nope", "label": "Nope", "prompt": "x"},
        )
        assert resp.status_code == 404, resp.text


class TestConfigValidation:
    def test_the_section_must_be_a_list(self):
        with pytest.raises(ValueError):
            app_config._validate_config({"system_prompt_library": {"a": "b"}})

    def test_an_entry_must_have_a_key(self):
        with pytest.raises(ValueError):
            app_config._validate_config({"system_prompt_library": [{"label": "x", "prompt": "p"}]})

    def test_a_key_may_not_collide_with_a_builtin(self):
        with pytest.raises(ValueError):
            app_config._validate_config(
                {"system_prompt_library": [{"key": "narrator", "label": "n", "prompt": "p"}]}
            )

    def test_duplicate_keys_are_refused(self):
        with pytest.raises(ValueError):
            app_config._validate_config(
                {
                    "system_prompt_library": [
                        {"key": "a", "label": "a", "prompt": "p"},
                        {"key": "a", "label": "b", "prompt": "q"},
                    ]
                }
            )

    def test_a_list_valued_section_reaches_the_merge(self):
        """`update_config` used to drop every section that was not a dict.

        `_split_unset` filtered the updates with `if isinstance(body, dict)`,
        so a list-valued section never reached the validator or the merge —
        and `update_config` returned success having written nothing. Every
        add, edit and remove of a prompt-library entry was a silent no-op
        that reported 200.
        """
        remaining, unset = app_config._split_unset(
            {"system_prompt_library": [{"key": "a", "label": "A", "prompt": "p"}]}
        )
        assert "system_prompt_library" in remaining
        assert remaining["system_prompt_library"] == [
            {"key": "a", "label": "A", "prompt": "p"}
        ]
        assert unset == set()
