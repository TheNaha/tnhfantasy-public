"""`update_config`'s blank-means-unset path.

`Settings.jsx` offers "(unset — backend falls back to its compiled-in default)"
for `generator.default_checkpoint` and sends `""` for it. `_check_str` rejects a
blank string, so the only way to express "unset" was a 400 — the option could
not be selected at all. Blank now deletes the key, which is what the label
claims: `resolve_default_checkpoint()` sees a genuinely absent key rather than
an empty string that happens to be treated as absent.
"""
import copy

import pytest

import config as cfg
from config import DEFAULT_CHECKPOINT, resolve_default_checkpoint, update_config


@pytest.fixture(autouse=True)
def isolated_config():
    """Own `_config`, restored afterwards — these tests mutate global state."""
    original = cfg._config
    original_path = cfg._config_path
    cfg._config = copy.deepcopy(cfg.DEFAULT_CONFIG)
    yield
    cfg._config = original
    cfg._config_path = original_path


class TestBlankMeansUnset:
    def test_a_blank_checkpoint_is_accepted_and_removes_the_key(self):
        update_config({"generator": {"default_checkpoint": "mine.safetensors"}}, persist=False)
        assert cfg.get_config()["generator"]["default_checkpoint"] == "mine.safetensors"

        update_config({"generator": {"default_checkpoint": ""}}, persist=False)

        assert "default_checkpoint" not in cfg.get_config()["generator"]
        assert resolve_default_checkpoint() == DEFAULT_CHECKPOINT

    def test_whitespace_counts_as_blank(self):
        update_config({"generator": {"default_checkpoint": "mine.safetensors"}}, persist=False)
        update_config({"generator": {"default_checkpoint": "   "}}, persist=False)

        assert "default_checkpoint" not in cfg.get_config()["generator"]

    def test_unsetting_one_leaf_does_not_disturb_its_siblings(self):
        update_config(
            {"generator": {"default_checkpoint": "mine.safetensors"}, "ai": {"temperature": 1.25}},
            persist=False,
        )
        update_config({"generator": {"default_checkpoint": ""}}, persist=False)

        assert cfg.get_config()["ai"]["temperature"] == 1.25

    def test_a_blank_value_elsewhere_is_still_rejected(self):
        """The unset rule is per-leaf, not a blanket loosening of the validator."""
        with pytest.raises(ValueError, match="must be a number"):
            update_config({"ai": {"temperature": ""}}, persist=False)

    def test_a_misspelled_key_is_still_rejected(self):
        with pytest.raises(ValueError, match="unknown generator setting"):
            update_config({"generator": {"default_chekpoint": ""}}, persist=False)

    def test_the_section_survives_being_emptied(self):
        """`_split_unset` drops an emptied section from the *update*; the merge
        must not leave the section missing."""
        update_config({"generator": {"default_checkpoint": ""}}, persist=False)

        assert isinstance(cfg.get_config().get("generator"), dict)

    def test_set_then_unset_round_trips(self):
        update_config({"generator": {"default_checkpoint": "mine.safetensors"}}, persist=False)
        update_config({"generator": {"default_checkpoint": ""}}, persist=False)
        update_config({"generator": {"default_checkpoint": "other.safetensors"}}, persist=False)

        assert cfg.get_config()["generator"]["default_checkpoint"] == "other.safetensors"