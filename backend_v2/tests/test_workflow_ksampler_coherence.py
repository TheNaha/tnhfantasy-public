"""The KSampler family must be one list across every tree that reads it.

`core/workflow_parser.KSAMPLER_NODE_CLASSES` is the backend's single source:
`workflow_metadata` derives gallery metadata from it, `provider_capabilities`
hard-blocks graphs on it, and the frontend's `reuseParameters.js` mirrors it
to restore generator state from a graph. Each used to keep its own copy and
they drifted — reuseParameters knew only plain `KSampler`,
workflow_metadata missed `KSampler (Efficient)`/`(Custom)`, and
provider_capabilities missed two spellings it was supposed to block on.

This test reads the frontend file as text (the two trees are never imported
together) and pins the lists to each other. `require_repo_root` skips the
module when there is no checkout to read.
"""
from __future__ import annotations

import re
from pathlib import Path

from repo_paths import require_repo_root

FRONTEND_REL = Path("frontend_v2/src/utils/reuseParameters.js")

_FRONTEND_CONST_RE = re.compile(
    r"const\s+K_SAMPLER_NODE_CLASSES\s*=\s*\[(?P<body>.*?)\]", re.DOTALL
)


def _backend_classes() -> tuple[str, ...]:
    from core.workflow_parser import KSAMPLER_NODE_CLASSES

    return KSAMPLER_NODE_CLASSES


def _frontend_classes() -> list[str]:
    root = require_repo_root("frontend reuseParameters.js")
    source = (root / FRONTEND_REL).read_text(encoding="utf-8")
    match = _FRONTEND_CONST_RE.search(source)
    assert match, (
        f"K_SAMPLER_NODE_CLASSES not found in {FRONTEND_REL} — the frontend "
        "mirror of the KSampler family is missing"
    )
    return re.findall(r"""['"]([^'"]+)['"]""", match.group("body"))


class TestKSamplerFamilyIsOneList:
    def test_frontend_mirror_equals_backend_source(self):
        assert _frontend_classes() == list(_backend_classes()), (
            "frontend K_SAMPLER_NODE_CLASSES drifted from "
            "core.workflow_parser.KSAMPLER_NODE_CLASSES"
        )

    def test_backend_callers_import_instead_of_redefining(self):
        """workflow_metadata and provider_capabilities must not keep copies."""
        root = require_repo_root("backend_v2 core modules")
        stale_re = re.compile(
            r"""\[\s*['"]KSampler['"]\s*,\s*['"]KSamplerAdvanced['"]\s*\]"""
            r"""|\(\s*['"]KSampler['"]\s*,\s*['"]KSampler \(Efficient\)['"]"""
        )
        for rel in (
            "backend_v2/core/workflow_metadata.py",
            "backend_v2/core/provider_capabilities.py",
        ):
            source = (root / rel).read_text(encoding="utf-8")
            assert not stale_re.search(source), (
                f"{rel} redefines the KSampler family instead of importing "
                "KSAMPLER_NODE_CLASSES from core.workflow_parser"
            )

    def test_every_known_spelling_is_present(self):
        classes = _backend_classes()
        for spelling in (
            "KSampler",
            "KSampler (Efficient)",
            "KSamplerAdvanced",
            "KSampler (Custom)",
            "KSampler (Advanced)",
        ):
            assert spelling in classes, f"missing KSampler spelling: {spelling}"