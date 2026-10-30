"""`provider_worker_core` and `provider_core` are forks, and must agree.

`deployables/provider_worker_core/__init__.py` documents why the fork exists:
the cloud deployables and `remote_agent` are separate containers with separate
dependency sets, deployed from separate sources, and neither will import the
other at runtime. So the copy is deliberate and should not be "unified" into one
package — but a deliberate fork still has to stay in step on the semantics BOTH
sides share, and nothing was checking.

It did not, and the drift was already there: `get_file_size_cap()` returned the
raw `int(raw)` in the deployables copy while `services/engines/base.py`'s clamps
with `cap if cap > 0 else 0`. Both docstrings promise "zero disables the cap",
and the Beam guard reads it the other way (`if max_bytes >= 0 and size >
max_bytes`), so setting the documented disable value made every `/get-file`
return 413 — the storage app unreadable rather than unlimited.

This module pins the shared semantics a divergence would silently break. It
deliberately does NOT compare the files byte-for-byte: the two copies have
different purposes — the deployable copy is the pre-slimming superset (13
functions in `responses.py`), the live one was cut down to what `remote_agent`
imports (4) — so a diff would be a false alarm. What must match is meaning.
"""

import ast
import importlib.util
import sys

import pytest

from services.engines.base import get_file_size_cap as backend_cap
from services.engines.base import get_upload_size_cap as backend_upload_cap

from tests.repo_paths import require_repo_root

ROOT = require_repo_root("deployables/provider_worker_core/")

DEPLOYABLE_CORE = ROOT / "deployables/provider_worker_core"


def _load_deployable_module(name: str):
    """Import a `provider_worker_core` module by path.

    These modules are not importable by name from here — they are a deploy-time
    package under a path only the deployable's own bootstrap knows — so they are
    loaded directly. `provider_core` (the live copy) IS on the path once the
    deployables' own bootstrap has run, and `provider_worker_core.responses`
    imports from it, so it is made importable first.
    """
    remote_agent = str(ROOT / "remote_agent")
    if remote_agent not in sys.path:
        sys.path.insert(0, remote_agent)
    spec = importlib.util.spec_from_file_location(name, DEPLOYABLE_CORE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGetFileSizeCapAgrees:
    """The one function both copies share, and the one that had drifted."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, 512 * 1024 * 1024),     # unset -> the default ceiling
            ("", 512 * 1024 * 1024),        # blank -> the default ceiling
            ("garbage", 512 * 1024 * 1024),  # unparseable -> the default, not a crash
            ("1024", 1024),
            ("0", 0),   # documented as "disable the cap"
            ("-1", 0),  # likewise, for the negative spelling
        ],
    )
    def test_same_answer_for_the_same_env(self, monkeypatch, raw, expected):
        if raw is None:
            monkeypatch.delenv("PROVIDER_GET_FILE_MAX_BYTES", raising=False)
        else:
            monkeypatch.setenv("PROVIDER_GET_FILE_MAX_BYTES", raw)

        deployable_copy = _load_deployable_module("http_client").get_file_size_cap
        from_deployable = deployable_copy()
        from_backend = backend_cap()

        assert from_deployable == expected
        assert from_backend == expected, (
            "the two get_file_size_cap copies disagree; one of them will make the "
            "documented 0-means-unlimited setting do something else"
        )

    @pytest.mark.parametrize(
        "rel",
        [
            "deployables/beam/beam_app.py",
            "remote_agent/server.py",
            "deployables/provider_worker_core/http_client.py",
        ],
    )
    def test_no_deployable_rejects_on_the_documented_disable_value(self, rel):
        """`0` means "no cap", so no guard may be written `cap >= 0 and size > cap`.

        With that shape, an operator who sets
        `PROVIDER_GET_FILE_MAX_BYTES=0` to disable the cap gets a 413 for every
        non-empty file — the setting that is supposed to open the storage app up
        is the one that makes it unreadable. `remote_agent/server.py` had this
        right; `beam_app.py` had it wrong, which is what a fork with no parity
        check looks like in practice.
        """
        source = (ROOT / rel).read_text()
        offending = [
            stripped
            for stripped in (line.strip() for line in source.splitlines())
            if stripped.startswith(("if ", "elif ")) and "max_bytes >= 0" in stripped
        ]
        assert not offending, (
            f"{rel} guards the cap with `>= 0`, which turns the documented "
            f"0-means-unlimited value into reject-everything: {offending}"
        )


class TestGetUploadSizeCapAgrees:
    """The upload cap is one knob across backend, containers and the agent.

    Added with FP-5 (audit-2026-10-30c): `get_upload_size_cap()`'s docstring
    promised the containers enforced `PROVIDER_UPLOAD_MAX_BYTES` and cited a
    deleted `router.py`; no deployable enforced any cap. Both fork copies now
    carry the helper, each enforcement site calls it, and the two copies must
    agree the same way `get_file_size_cap` does.
    """

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, 512 * 1024 * 1024),     # unset -> the default ceiling
            ("", 512 * 1024 * 1024),        # blank -> the default ceiling
            ("garbage", 512 * 1024 * 1024),  # unparseable -> the default, not a crash
            ("1024", 1024),
            ("0", 0),   # documented as "disable the cap"
            ("-1", 0),  # likewise, for the negative spelling
        ],
    )
    def test_same_answer_for_the_same_env(self, monkeypatch, raw, expected):
        if raw is None:
            monkeypatch.delenv("PROVIDER_UPLOAD_MAX_BYTES", raising=False)
        else:
            monkeypatch.setenv("PROVIDER_UPLOAD_MAX_BYTES", raw)

        deployable_copy = _load_deployable_module("http_client").get_upload_size_cap
        live_spec = importlib.util.spec_from_file_location(
            "live_http_client", ROOT / "remote_agent/provider_core/http_client.py"
        )
        live_module = importlib.util.module_from_spec(live_spec)
        live_spec.loader.exec_module(live_module)

        from_backend = backend_upload_cap()
        assert deployable_copy() == expected
        assert live_module.get_upload_size_cap() == expected
        assert from_backend == expected, (
            "the upload cap copies disagree; PROVIDER_UPLOAD_MAX_BYTES would "
            "mean different things on each side of the same contract"
        )

    @pytest.mark.parametrize(
        ("rel", "needle"),
        [
            ("deployables/beam/beam_app.py", "get_upload_size_cap()"),
            ("deployables/modal/image/modal_app.py", "get_upload_size_cap()"),
            ("remote_agent/server.py", "PROVIDER_UPLOAD_MAX_BYTES"),
            ("remote_agent/provider_core/http_client.py", "get_upload_size_cap"),
            ("deployables/provider_worker_core/http_client.py", "get_upload_size_cap"),
        ],
    )
    def test_every_enforcement_site_reads_the_shared_knob(self, rel, needle):
        source = (ROOT / rel).read_text()
        assert needle in source, (
            f"{rel} no longer reads {needle}; its upload path is outside the "
            "PROVIDER_UPLOAD_MAX_BYTES contract again"
        )


class TestForkShape:
    """The fork is deliberate; these keep it honest without forbidding it."""

    @pytest.mark.parametrize(
        "rel",
        [
            "deployables/provider_worker_core/__init__.py",
            "deployables/provider_worker_core/http_client.py",
            "deployables/provider_worker_core/responses.py",
            "remote_agent/provider_core/__init__.py",
            "remote_agent/provider_core/http_client.py",
            "remote_agent/provider_core/responses.py",
        ],
    )
    def test_both_copies_exist(self, rel):
        assert (ROOT / rel).exists(), f"{rel} is missing"

    def test_the_deployable_copy_still_exports_what_the_deployables_import(self):
        """`modal_app.py` and `beam_app.py` import these by name at deploy time."""
        responses = _load_deployable_module("responses")
        for name in ("ok", "failed", "from_upstream"):
            assert hasattr(responses, name), (
                f"provider_worker_core.responses no longer exports {name}; the Modal "
                f"and Beam apps import it at deploy time and only fail once deployed"
            )

    def test_the_shared_modules_declare_their_purpose(self):
        """The `__init__` explaining the fork is the thing keeping it justified."""
        text = (DEPLOYABLE_CORE / "__init__.py").read_text()
        assert "fork" in text.lower(), (
            "provider_worker_core/__init__.py no longer explains why the copy "
            "exists; without that, the next reader 'helpfully' unifies it and "
            "breaks deployment"
        )
        assert (ROOT / "remote_agent/provider_core/__init__.py").exists()

    def test_the_fork_is_not_silently_identical(self):
        """A byte-identical fork is a fork nobody is maintaining.

        If this ever starts failing because the files were genuinely unified,
        delete the copy rather than keeping a second path to one implementation.
        """
        deployable = (DEPLOYABLE_CORE / "responses.py").read_text()
        live = (ROOT / "remote_agent/provider_core/responses.py").read_text()

        def _functions(source: str) -> set:
            tree = ast.parse(source)
            return {
                node.name
                for node in tree.body
                if isinstance(node, ast.FunctionDef)
            }

        assert _functions(deployable) != _functions(live), (
            "the two responses.py copies now expose the same functions; either "
            "unify them or drop the fork — do not leave two identical paths"
        )