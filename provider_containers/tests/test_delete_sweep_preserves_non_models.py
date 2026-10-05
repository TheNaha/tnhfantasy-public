"""The delete sweeps must not delete files that were never models.

`models/embeddings`, `models/wildcards` and `models/poses` are in
`MODEL_DIRECTORIES`, so the reconciliation validator walks them — and
reconciliation runs it with `delete_invalid=True` every couple of hours,
unattended, against the operator's real volume.

Those directories are *supposed* to hold non-model files: a `.txt` embedding or
wildcard list, a `.yaml` pose config. `validate_downloaded_file` skips its header
check for those extensions but still applies `MIN_MODEL_SIZE` (10 KiB), so an
ordinary 200-byte wildcard list came back `valid: False, indeterminate: False` —
a definite verdict, the only kind the delete branch acts on — and was
`os.remove`d.

Measured on the remote agent before this guard, one `models/wildcards` sweep:

    files before: big_prompt.yaml easynegative.txt large_wildcards.txt
                  my_wildcards.txt style.yaml
    total_invalid: 4
    files after:  large_wildcards.txt

Only the one file over 10 KiB survived. There is no undo and no notification;
the operator finds out when a prompt stops applying.

The guard is `is_model_candidate`, which is narrower than the `is_model_file`
all three sweeps previously used: `is_model_file` only excludes pipeline-owned
(`.lock`, `.downloading`) and sidecar (`.json`, `.preview.png`, `.sha256`) names,
so it was never going to stop a `.txt`.

These tests assert the RULE on the real sweep implementations, so a fourth copy
or a re-widened predicate fails here.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from provider_core.utils import NON_MODEL_SUFFIXES, is_model_candidate

# What a ComfyUI install legitimately keeps in these directories.
NON_MODEL_ASSETS = (
    "wildcards/easynegative.txt",
    "wildcards/style.yaml",
    "wildcards/portrait.yml",
    "embeddings/sd-negative-embed.txt",
    "poses/openpose.yaml",
    "notes.md",
    "reference.png",
    "meta.json",
)

MODELS = (
    "checkpoints/sd_xl_base.safetensors",
    "loras/detail.safetensors",
    "vae/vae-ft-mse.pt",
    "unet/diffusion_pytorch_model.onnx",
    "clip/text_encoder.safetensors",
)


class TestThePredicate(unittest.TestCase):
    def test_non_model_assets_are_not_validation_candidates(self):
        for name in NON_MODEL_ASSETS:
            self.assertFalse(
                is_model_candidate(name),
                f"{name} lives in a model directory by design and must never be "
                "validated on a delete path",
            )

    def test_models_are_still_candidates(self):
        for name in MODELS:
            self.assertTrue(is_model_candidate(name), name)

    def test_pipeline_artifacts_are_not_candidates(self):
        for name in ("x.safetensors.lock", "x.safetensors.downloading", "x.json", "x.preview.png", "x.sha256"):
            self.assertFalse(is_model_candidate(name), name)

    def test_the_header_skip_list_is_derived_from_the_same_tuple(self):
        # If these two can disagree, a suffix added to one and not the other is
        # exactly the drift that deleted files.
        from provider_core.validation import _SKIP_HEADER_EXTENSIONS

        self.assertTrue(set(_SKIP_HEADER_EXTENSIONS) <= set(NON_MODEL_SUFFIXES))


class TestTheRemoteAgentSweep(unittest.TestCase):
    """The real implementation, on a real directory, with deletes enabled."""

    def _sweep(self, filenames, directory="wildcards"):
        import remote_agent.server as agent

        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, directory)
            os.makedirs(target)
            for relative in filenames:
                path = os.path.join(target, os.path.basename(relative))
                with open(path, "wb") as handle:
                    handle.write(b"not a model, just text\n")
            result = agent._validate_dir(target, delete_invalid=True)
            return result, sorted(os.listdir(target))

    def test_it_deletes_nothing_that_is_not_a_model(self):
        result, remaining = self._sweep(NON_MODEL_ASSETS)
        self.assertEqual(result["total_invalid"], 0, result)
        self.assertEqual(
            remaining,
            sorted(os.path.basename(n) for n in NON_MODEL_ASSETS),
            "a non-model asset was deleted by the validation sweep",
        )

    def test_a_too_small_file_that_looks_like_a_model_is_still_reported(self):
        # The guard must not become a way to stop noticing bad downloads.
        result, remaining = self._sweep(["checkpoints/broken.safetensors"])
        self.assertEqual(result["total_invalid"], 1, result)
        self.assertEqual(remaining, [])

    def test_a_large_non_model_asset_is_also_left_alone(self):
        # Over MIN_MODEL_SIZE it used to pass validation and be counted `valid`,
        # which is how this stayed invisible: only the small ones vanished, so
        # the sweep still reported a plausible `total_valid`.
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "wildcards")
            os.makedirs(target)
            for name, size in (("huge.txt", 40000), ("small.txt", 23)):
                with open(os.path.join(target, name), "wb") as handle:
                    handle.write(b"x" * size)
            result = agent_validate(root, target)
            self.assertEqual(result["total_invalid"], 0, result)
            self.assertEqual(result["total_valid"], 0, result)
            self.assertEqual(sorted(os.listdir(target)), ["huge.txt", "small.txt"])


def agent_validate(root, target):
    import remote_agent.server as agent

    return agent._validate_dir(target, delete_invalid=True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()