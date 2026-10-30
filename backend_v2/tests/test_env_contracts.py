"""Every environment variable the code reads must be documented, and vice versa.

This is a guard test, not a snapshot. The previous audit found 51 variables read
by code and present in no `.env.example*` file, and one (`INFERENCE_TIMEOUT_SECONDS`)
documented in three example files and read by nothing. A docs edit fixes that
instance; this makes the class unable to come back, which is the part that
matters — docs drift the moment anyone adds an env read.

Direction A: read by code, assigned in no example file.
    An operator cannot discover or set a knob the docs never mention. The knobs
    involved are not exotic: upload size limits, the DB pool, the model-preview
    timeouts, the job timeout. Several are the difference between a large upload
    working and 413ing.

Direction B: assigned in an example file, read by no code.
    Worse in a small way: the example is a copy-paste source, so it teaches an
    operator that setting this does something. `INFERENCE_TIMEOUT_SECONDS` was
    in three examples while `config.py` held a comment claiming the backend's job
    timeout was "aligned" with it.

The read side is resolved through the repo's own wrapper helpers
(`_env_int`, `_env_float`, `_env_bool`, `_env_var_is_set`, `resolve_env_*`).
A direct `os.getenv` scan misses 25 keys that way, including all six
`PROVIDER_HTTP_*` — which is exactly how a prior audit concluded those six were
dead code when they are read at `http_client.py:207-217` and wired at
`worker_bootstrap.py:172`.

`DYNAMIC_READS` is the set of places a key is computed rather than written
literally. They are listed rather than skipped wholesale, so a NEW dynamic read
fails the test and has to be considered on purpose.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Roots whose Python is application code. `tests` is excluded because a test may
# legitimately set a variable to exercise a path.
#
# `provider_containers` was here until 2026-10-09, when the tree was deleted and
# its workers folded into `backend_v2/services/engines/`. `Path.rglob` on a
# missing directory returns empty without raising, so the stale entry cost
# nothing visible — it silently narrowed what this guard could see, which is the
# same failure shape as every other guard in this repo that "cannot see the code
# it is guarding". The assertion in `_python_files` makes the next deletion fail
# loudly instead.
CODE_ROOTS = ("backend_v2", "remote_agent")
EXCLUDE_PARTS = {"tests", ".venv", "venv", "__pycache__", "node_modules", ".git", "dist"}

EXAMPLE_FILES = sorted(
    p
    for p in REPO.rglob(".env.example*")
    if not any(part in EXCLUDE_PARTS for part in p.parts)
    and p.parent.name not in EXCLUDE_PARTS
)

# Callables that take a variable NAME as their first argument. Resolving these is
# what makes this test see the wrapper style the codebase actually uses.
NAME_TAKING_HELPERS = {
    "os.environ.get", "os.environ.setdefault", "os.getenv", "environ.get",
    "getenv", "getenv_int", "getenv_float", "getenv_bool",
    "_env_int", "_env_float", "_env_bool", "_env_str", "_env_var_is_set",
    "_env_is_set", "_positive_int_env", "_positive_float_env", "_env_path",
    "_env_flag",
    "resolve_env_bool", "resolve_env_int", "resolve_env_float", "resolve_env_str",
    "int_env", "float_env", "bool_env", "path_env",
    "_default", "resolve_env", "env_var",
}

# Helpers whose argument is a SUFFIX that the helper itself prefixes. Detecting
# these by name is a heuristic, so it is narrow: `_env_var_is_set` is the only
# one in the tree, and its docstring says "with COMFY_ prefix". Without this the
# test reports `CORS_ORIGINS` and `JOB_TIMEOUT` as undocumented variables when
# the code actually reads `COMFY_CORS_ORIGINS` and `COMFY_JOB_TIMEOUT` — and the
# first version of this test did exactly that.
PREFIXING_HELPERS = {
    "_env_var_is_set": "COMFY_",
}

# Module-level dicts whose string values are environment-variable names. The
# values are already fully-qualified, and they are not call arguments so the AST
# walk above cannot see them. `config.ENV_VAR_OVERRIDES` is the one that matters:
# it is how `jobs.timeout`, `api.cors_origins` and friends become
# environment-controlled, and missing it would report those six as dead.
ENUMERATED_DICT_NAMES = {"ENV_VAR_OVERRIDES"}

# Places where the key is computed at runtime, so no single literal exists to
# find. Each is a decision, not a gap: if one of these is removed, this test
# fails and the entry has to go with it.
DYNAMIC_READS = {
    # Builds "COMFY_" + section.upper() + "_" + key.upper() from a pydantic
    # `Settings` field; the `env_prefix` is a class attribute, not a literal.
    "backend_v2/config.py",
    # Dynamic pass-through env forwarding for child deployment processes
    "backend_v2/services/provider_deploy.py",
    # Alias loop reads PROVIDER_UPLOAD_MAX_BYTES / REMOTE_AGENT_UPLOAD_MAX_BYTES
    # by name from a list, so the scanner cannot see the literal.
    "remote_agent/server.py",
}


def _python_files() -> list[Path]:
    # A code root that no longer exists must fail here, not silently shrink the
    # scan. `rglob` on a missing directory returns empty and raises nothing.
    missing = [root for root in CODE_ROOTS if not (REPO / root).is_dir()]
    assert not missing, (
        f"CODE_ROOTS names directories that do not exist: {missing}. "
        "Deleting a code root silently narrows what this guard can see."
    )
    out = []
    for root in CODE_ROOTS:
        for path in (REPO / root).rglob("*.py"):
            if any(part in EXCLUDE_PARTS for part in path.parts):
                continue
            out.append(path)
    return sorted(out)


def _callee_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        base = _callee_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _param_names(tree: ast.AST) -> set[str]:
    """Every parameter name declared anywhere in the module.

    A helper call whose first argument is one of these is a PASS-THROUGH, not a
    dynamic key: `def _env_int(name, default): return os.environ.get(name)` is
    the helper reading whatever the caller passed, and every one of those
    callers has a literal that is walked separately.

    This is the general rule, and it replaced two narrower ones. The first
    version skipped only functions with a parameter literally named after a known
    helper, which missed `env_name` and left six files reporting a "dynamic read"
    nobody could locate. Matching on "is this name a declared parameter" catches
    every pass-through, including ones written later.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
            for a in args:
                names.add(a.arg)
            for a in (node.args.vararg, node.args.kwarg):
                if a is not None:
                    names.add(a.arg)
    return names


def _env_vars_read() -> tuple[set[str], set[str]]:
    """Return (literal keys read, paths containing a dynamic read)."""
    keys: set[str] = set()
    dynamic: set[str] = set()
    for path in _python_files():
        rel = str(path.relative_to(REPO))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue

        # Dict literals assigned to a name in ENUMERATED_DICT_NAMES.
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target]
            if not targets or not any(t.id in ENUMERATED_DICT_NAMES for t in targets):
                continue
            value = node.value
            if isinstance(value, ast.Dict):
                for v in value.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        if v.value.isupper():
                            keys.add(v.value)

        params = _param_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _callee_name(node.func)
            if name not in NAME_TAKING_HELPERS or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                prefix = PREFIXING_HELPERS.get(name, "")
                # A prefixing helper means the bare name is NOT the variable, so
                # only the prefixed form is added.
                key = prefix + first.value
                if key.isupper():
                    keys.add(key)
            elif isinstance(first, ast.Name) and first.id in params:
                continue  # a helper reading its own parameter; the caller is walked
            else:
                dynamic.add(rel)
    keys |= _compose_vars_read()
    return keys, dynamic


# Compose files whose `${VAR}` substitutions are real reads of the operator's
# `.env`. `env_file:` entries are not scanned for reads — those name a file, and
# the variables inside it are read by the container's own code, which the Python
# sweep above already covers.
COMPOSE_FILES = tuple(sorted(REPO.glob("docker-compose*.yml")))


def _compose_vars_read() -> set[str]:
    """Variables the compose layer substitutes out of `.env`.

    A compose file is a consumer of `.env` exactly as much as Python is: it
    interpolates `${NAME}` and `${NAME:-default}`. The scan walked Python only, so
    a variable that exists solely to configure compose — `COMFY_FRONTEND_BIND`,
    which decides the address the frontend *and therefore the whole API* is served
    on — was reported as "documented in an example file and read by no code". That
    is a false positive on a security-relevant setting, and it is the kind that
    teaches a reader to ignore this test.

    Also covers the `${NAME}` form used inside `command:`, `environment:` and
    `labels:`, which is how the variable reaches the container.
    """
    found: set[str] = set()
    for path in COMPOSE_FILES:
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Strip comments so a `${VAR}` mentioned in prose is not a read. A `#`
        # inside a quoted string would confuse this, so only whole-line and
        # trailing `# ` are dropped — compose files here do not put `#` in values.
        for line in text.splitlines():
            stripped = line.split(" #", 1)[0]
            if stripped.lstrip().startswith("#"):
                continue
            for m in re.finditer(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", stripped):
                found.add(m.group(1))
    return found


def _env_vars_assigned() -> dict[str, list[str]]:
    """Every `KEY=...` assignment in an example file, mapped to where it appears.

    Assignments inside a comment are counted separately. A commented
    `OPENAI_API_KEY=` is the codebase's deliberate pattern for a credential the
    operator must supply: it is visible, and the surrounding comment says
    REQUIRED. Treating that as undocumented would push someone to uncomment a
    key by accident, and treating it as fully assigned would lose the signal that
    it needs no value until an engine is enabled. So: `assigned` for a real
    assignment, `commented` for the other case, and the test reports each
    differently.
    """
    assigned: dict[str, list[str]] = {}
    commented: dict[str, list[str]] = {}
    for path in EXAMPLE_FILES:
        rel = str(path.relative_to(REPO))
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            body = line.lstrip()
            is_comment = body.startswith("#")
            if is_comment:
                body = body.lstrip("#").lstrip()
            m = re.match(r"^(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", body)
            if not m:
                continue
            bucket = commented if is_comment else assigned
            bucket.setdefault(m.group(1), []).append(rel)
    return assigned, commented


def _all_documented() -> set[str]:
    """Keys that appear in any example file, assigned or commented."""
    assigned, commented = _env_vars_assigned()
    return set(assigned) | set(commented)


# Read by a third party rather than by this repo, so their absence from the
# examples is not drift. Each is consumed by an external library or the runtime.
THIRD_PARTY = {
    "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE", "PYTHONPATH", "PYTHONHASHSEED",
    "PATH", "HOME", "HOSTNAME", "TERM", "LANG", "TZ", "NODE_ENV", "NPM_CONFIG_*",
    "CI", "GITHUB_*", "USER", "UID", "PWD", "SHLVL", "PORT", "HOST",
    # The `modal` SDK reads these itself, via `modal.Config`.
    "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "MODAL_ENVIRONMENT", "MODAL_PROFILE",
    # Provider engines set these; the SDK/framework honours them.
    "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "NVIDIA_DRIVER_CAPABILITIES",
    "XDG_RUNTIME_DIR", "XDG_DATA_DIR", "XDG_CONFIG_HOME",
    # Build/runtime-level, set by compose, no application code reads them.
    "COMFY_UVICORN_RELOAD", "HF_HOME", "XDG_CACHE_HOME", "VITE_*",
}


class TestDirectionA:
    def test_every_env_var_read_by_code_is_documented(self):
        read, _ = _env_vars_read()
        assigned, commented = _env_vars_assigned()
        undocumented = sorted(
            k for k in read - set(assigned) - set(commented) - THIRD_PARTY
            # A var read via an explicit allowlist is a deliberate decision.
            if k not in _ALLOWLISTED_UNDOCUMENTED
        )
        assert undocumented == [], (
            f"{len(undocumented)} environment variables are read by code and "
            "assigned in no .env.example* file, so an operator cannot discover "
            "or set them:\n  "
            + "\n  ".join(
                f"{k}  (default: {_default_for(k)})" for k in undocumented
            )
        )

    def test_a_new_dynamic_read_has_to_be_declared(self):
        """Dynamic reads cannot be resolved to a key, so each is a decision.
        A new one must be added to `DYNAMIC_READS` on purpose."""
        _, dynamic = _env_vars_read()
        unexpected = sorted(dynamic - DYNAMIC_READS)
        assert unexpected == [], (
            "new dynamic environment-variable read(s). If the key is computed at "
            "runtime it cannot be checked automatically — add it to DYNAMIC_READS "
            "with a reason, or make the literal visible:\n  "
            + "\n  ".join(unexpected)
        )

    def test_the_allowlist_has_not_grown(self):
        """`_ALLOWLISTED_UNDOCUMENTED` is a decision list, not a dump. Growing it
        is how this test becomes decorative, so entries must say why."""
        # `assert not x`, not `assert x == []`: this is a dict comprehension, and
        # an EMPTY dict does not equal an empty list, so the first version of
        # this test failed with "allowlist entries with no reason: {}" — which
        # reads as though the list is empty when the opposite was meant.
        without_reason = {
            key: reason
            for key, reason in _ALLOWLISTED_UNDOCUMENTED.items()
            if not reason.strip()
        }
        assert not without_reason, f"allowlist entries with no reason: {without_reason}"

    def test_every_allowlist_entry_is_still_read(self):
        """An allowlist entry for a variable that no longer exists is a stale
        exemption that quietly widens the allowlist."""
        read, _ = _env_vars_read()
        stale = sorted(set(_ALLOWLISTED_UNDOCUMENTED) - read)
        assert not stale, (
            f"allowlist entries for variables nothing reads any more: {stale}. "
            "Delete them, or the allowlist is quietly growing."
        )


class TestDirectionB:
    def test_no_example_file_documents_a_var_nothing_reads(self):
        read, _ = _env_vars_read()
        assigned, _commented = _env_vars_assigned()
        unread = sorted(
            k for k in assigned
            if k not in read
            # Consumed by the `modal` SDK and the interpreter, not by this repo.
            and k not in THIRD_PARTY
            and not any(k.startswith(p) for p in ("GITHUB_", "VITE_", "NPM_"))
        )
        assert unread == [], (
            f"{len(unread)} variables are assigned in an "
            ".env.example* file and read by no code, so the example teaches an "
            "operator that setting them does something:\n  "
            + "\n  ".join(f"{k}  ({', '.join(assigned[k])})" for k in unread)
        )

    def test_every_example_file_exists_and_is_not_empty(self):
        assert EXAMPLE_FILES, "found no .env.example* files at all"
        for path in EXAMPLE_FILES:
            assert path.read_text(encoding="utf-8").strip(), f"{path} is empty"


# ── `.env.example` is the CANONICAL backend reference ────────────────────────
# The two directions above check the union of every example file, which is the
# right invariant but leaves a hole: a backend variable documented only in
# `.env.example.provider.engines` counts as documented, so the canonical backend
# reference could be emptied out one variable at a time and stay green.
#
# Keeping it (rather than deleting it as a duplicate of `config.py`'s `Settings`)
# is the right call: `Settings` declares a field and its pydantic default, and
# says nothing about whether the variable gates a feature, what breaks when it is
# unset, or which code reads it. This file is the only place that knowledge is.
# It is also the compose `env_file` template (via `env_file: - .env` in
# docker-compose.yml), so compose vars (POSTGRES_*, COMFY_FRONTEND_BIND,
# COMFY_PROVIDER_TOKEN) appear as active values alongside the documented-but-
# commented tunables.
#
# The scope rule is by CODE ROOT, not by prefix: `COMFY_` covers the backend, the
# image worker, the LLM worker, the TTS worker and the remote agent, so prefix
# alone would drag `MODAL_*` and the provider credentials in here.
BACKEND_ROOT = "backend_v2"
BACKEND_EXAMPLE = REPO / ".env.example"


class TestTheBackendExampleIsCanonical:
    @staticmethod
    def _backend_reads() -> set[str]:
        """Variables read by `backend_v2/` code only."""
        keys: set[str] = set()
        for path in _python_files():
            if not str(path.relative_to(REPO)).startswith(f"{BACKEND_ROOT}/"):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            params = _param_names(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _callee_name(node.func)
                if name not in NAME_TAKING_HELPERS or not node.args:
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    key = PREFIXING_HELPERS.get(name, "") + first.value
                    if key.isupper():
                        keys.add(key)
                elif isinstance(first, ast.Name) and first.id in params:
                    continue
        return keys

    def test_every_backend_variable_is_documented_there(self):
        documented = _all_documented()
        backend_only = {
            k for k in self._backend_reads()
            if k.startswith("COMFY_") or k in {"PYTHONUNBUFFERED", "OUTPUT_DIR", "INPUT_DIR"}
        }
        missing = sorted(k for k in backend_only if k not in documented)
        assert not missing, (
            "these variables are read by backend_v2/ and appear in no .env.example* "
            "file:\n  " + "\n  ".join(missing)
        )

    def test_it_is_referenced_from_a_place_a_reader_will_find(self):
        """The orphan problem, stated as a test.

        A file nothing points at cannot stay correct: it is not read while it is
        being written, so it drifts, and nothing reports the drift. Two entry
        points a reader actually visits — the README's setup steps and the
        deployment guide — must name it, or this is an orphan again.
        """
        for doc in ("README.md", "docs/deployment.md"):
            path = REPO / doc
            assert path.exists(), f"{doc} is missing entirely"
            text = path.read_text(encoding="utf-8")
            assert ".env.example" in text, (
                f"{doc} never mentions .env.example, so the only "
                "documentation for the backend's environment variables is "
                "unreachable from the documentation"
            )

    def test_its_database_section_does_not_claim_compose_leaves_the_url_unset(self):
        """The stale-premise guard for this file specifically.

        It said "Compose does NOT set `COMFY_DATABASE_URL`", which read as "no
        code path can set it" — while `env_file: - .env` supplies it on every
        `up`, and this repo's own `.env` does. An operator reading it would
        conclude the variable was inert. The accurate statement is narrower: the
        compose `environment:` block does not set it, and `POSTGRES_*` decides.
        """
        text = BACKEND_EXAMPLE.read_text(encoding="utf-8")
        assert "env_file" in text, (
            ".env.example's database section must account for the fact "
            "that `env_file: - .env` can and does supply COMFY_DATABASE_URL"
        )


# Deliberately NOT documented in an example file, with the reason. Keep this
# short and keep the reasons real: an entry here is a decision someone can
# challenge, not a bucket.
#
# The prior two Modal entries (`MODAL_VOLUME_NAME`, `MODAL_BUILD_GPU_TYPE`)
# described a `modal deploy` parameter that only the deleted container worker
# read; the in-process engines resolve their app names from the provider row.
# They were removed rather than re-justified, because "an allowlist entry for a
# variable nothing reads" is exactly the stale exemption this list is not allowed
# to become.
_ALLOWLISTED_UNDOCUMENTED: dict[str, str] = {
    # Set by docker-compose for the containers, not for a human to tune, and
    # already documented in the compose file's own environment block.
    "POSTGRES_HOST": "compose-only; the DSN is assembled from POSTGRES_* at database.py:71",
    "POSTGRES_PORT": "compose-only; see POSTGRES_HOST",
    # Build argument to the image, read at module import in the remote agent.
    "MODAL_APP_NAME": "Modal deploy parameter, not an operator knob",
    "REMOTE_AGENT_ALLOW_INSECURE": "documented in docker-compose.yml; defaults False",
}


def _default_for(key: str) -> str:
    """Best-effort: the default literal passed at the read site, if there is one."""
    needle = f'"{key}"'
    for path in _python_files():
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in re.finditer(re.escape(needle) + r"\s*,\s*([^)\n]+)", src):
            return f"{m.group(1).strip()[:40]} in {path.relative_to(REPO)}"
    return "see the read site"


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_example_files_parse_as_env_assignments(path: Path):
    """A malformed line silently teaches nothing. Spot-check that every
    non-blank, non-comment line is either an assignment or a section header."""
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
    ):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert re.match(r"^(export\s+)?[A-Z][A-Z0-9_]*\s*=", stripped), (
            f"{path.name}:{lineno} is neither a comment nor an assignment: {stripped!r}"
        )
