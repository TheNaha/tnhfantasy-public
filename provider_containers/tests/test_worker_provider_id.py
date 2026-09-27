"""`os.getenv(name, default)` applies the default only when the variable is ABSENT.

Both workers read `ENGINE` through `(os.getenv("ENGINE") or "").strip().lower() or
"<default>"` — with a four-line comment on the trap — and read `PROVIDER_ID` two
lines above it through `os.getenv("PROVIDER_ID", f"{ENGINE}-worker")`, which is
*not* the same expression. A bare `PROVIDER_ID=` in an env file (an
`env_file:` line with the value forgotten, which is what a templated compose file
produces) yields `""`, not the default.

An empty provider_id is not cosmetic: reconciliation and auto-discovery register
discovered models under it, so they land on a provider row the backend does not
have, and `provider_container_name(provider.id)` — the name the backend looks for
(`infrastructure/providers/runtime.py`) — comes out as `tnhcomfy-`, which matches
no container.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROVIDER_ROOT = Path(__file__).resolve().parents[1]

# (module, how the engine-derived default is spelled)
WORKERS = [
    ("image_worker.worker", "{engine}-worker"),
    ("llm_worker.worker", "local-dev"),
]

# Values that must all collapse to the default: absent is handled separately,
# since `monkeypatch.delenv` is the honest way to express it.
BLANK_VALUES = ["", " ", "\t", "\n", "   \t\n  "]


def _provider_id_under(module: str, provider_id: str | None, engine: str = "modal") -> str:
    """Import `module` in a fresh interpreter and read its PROVIDER_ID.

    A subprocess, not `importlib.reload`: both worker modules construct a client
    and (after item 21) build a lifespan closure at import time, and reloading
    them inside the test process would leave a half-initialised module in
    `sys.modules` for every later test in the run.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROVIDER_ROOT)
    env["ENGINE"] = engine
    # A modal/app-name-free environment: the image worker raises at import for an
    # unknown ENGINE, and the LLM worker's default engine has no side effects.
    if provider_id is None:
        env.pop("PROVIDER_ID", None)
    else:
        env["PROVIDER_ID"] = provider_id
    # Keep the reconciliation/discovery loops from being configured against the
    # developer's real backend if a future edit starts them at import.
    env.setdefault("BACKEND_URL", "http://127.0.0.1:9")

    script = textwrap.dedent(
        f"""
        import importlib, sys
        module = importlib.import_module({module!r})
        # Marker line: importing a worker logs startup info, so a bare
        # `print(module.PROVIDER_ID)` is read back with the log lines in front.
        sys.stdout.write("PROVIDER_ID=" + module.PROVIDER_ID)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(PROVIDER_ROOT),
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    for line in result.stdout.splitlines():
        if line.startswith("PROVIDER_ID="):
            return line.split("=", 1)[1]
    raise AssertionError(f"no PROVIDER_ID marker in: {result.stdout!r}")


@pytest.mark.parametrize("module,default", WORKERS)
def test_an_absent_provider_id_takes_the_default(module, default, engine="modal"):
    assert _provider_id_under(module, None, engine) == default.format(engine=engine)


@pytest.mark.parametrize("module,default", WORKERS)
@pytest.mark.parametrize("blank", BLANK_VALUES)
def test_a_blank_provider_id_takes_the_default(module, default, blank, engine="modal"):
    """The regression: `os.getenv`'s default does not fire for a present-but-empty
    variable, so this used to resolve to "" and register the worker's models
    under no provider at all."""
    assert _provider_id_under(module, blank, engine) == default.format(engine=engine)


@pytest.mark.parametrize("module,default", WORKERS)
def test_a_padded_but_real_provider_id_is_stripped_not_defaulted(module, default, engine="modal"):
    """The other half of the treatment: surrounding whitespace is noise, not
    identity, and must not become part of the provider id."""
    assert _provider_id_under(module, "  my-provider \n", engine) == "my-provider"


@pytest.mark.parametrize("module,default", WORKERS)
def test_a_real_provider_id_survives(module, default, engine="modal"):
    assert _provider_id_under(module, "my-provider", engine) == "my-provider"


def test_both_workers_use_the_same_treatment_for_both_variables():
    """Source guard: the two reads are two lines apart, and the fix is worthless
    if only one of them keeps it."""
    for module, _ in WORKERS:
        source = (PROVIDER_ROOT / f"{module.replace('.', '/')}.py").read_text()
        for name in ("PROVIDER_ID", "ENGINE"):
            for line in source.splitlines():
                if line.startswith(f"{name} = "):
                    assert ".strip()" in line, (
                        f"{module} reads {name} without .strip(): {line!r}"
                    )
                    assert f'os.getenv("{name}")' in line or f'os.environ.get("{name}")' in line, (
                        f"{module} reads {name} with a default argument, which does not "
                        f"fire for a present-but-empty variable: {line!r}"
                    )
