"""The Colab notebook's paths have to agree with where the code actually is.

The notebook was written for Colab, where the checkout lives under
`/content`. It was then run on Modal, where the checkout lives under
`/root` — and nothing in the notebook knew that.

The result was a **hard failure at cell 5**:

    ModuleNotFoundError: No module named 'ram_manager'

because cell 5 put `/content/tnhfantasy/remote_agent` on `sys.path` — the
Colab path — while cell 3 had cloned the repository to `/root/tnhfantasy`, and
`remote_agent` was not where anything was looking for it.

The subtle part is WHY the two disagreed. Cell 3 chose the workspace root by
asking "does `/content` exist?", and cell 4 MOUNTS Google Drive at
`/content/drive` — which CREATES `/content`. So the answer to that question
depended on which cell asked it and when. On Modal, cell 3 (before the
drive mount) saw no `/content` and cloned to `/root`; cell 5 (after it) saw
`/content` and looked there.

The rule is now the same in every cell, and it is derived from the
ENVIRONMENT — Colab gets `/content`, Modal gets `/root` — so it cannot
change under a cell's feet.

These tests pin that.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys


from repo_paths import require_repo_root

ROOT = require_repo_root("the Colab notebook generator")

GENERATOR = ROOT / "scripts" / "update_colab_notebooks.py"

AGENT_DIR = ROOT / "remote_agent"

#: The Google Drive mount point. It is genuinely `/content/drive` on Colab
#: and is only ever used inside an `if is_colab` branch.
_GDRIVE = re.compile(r'["\'](/content/drive[^"\']*)["\']')

#: A path under /content that is NOT the Google Drive mount.
_HARD_CODED = re.compile(r'["\'](/content/(?!drive)[^"\']*)["\']')

#: Paths referenced by the notebook that are NOT server.py routes:
#: ComfyUI-native endpoints (not in server.py) and backend-only endpoints
#: (not in server.py). Every other notebook-referenced /path must exist in
#: remote_agent/server.py.
_EXTERNAL_PATHS = frozenset({
    "/free",
    "/object_info",
    "/system_stats",
    "/interrupt",
    "/v1/chat/completions",
    "/synthesize",
    "/vram/prepare",
    "/vram/release",
    "/vram/status",
    "/vram/stop-llm",
    "/v1/decisions",
    # Backend-only routes (the notebook registers providers against the
    # backend, not the agent). Not agent routes.
    "/api/v2/llm/catalog",
    "/api/v2/models/catalog",
    "/api/v2/providers/",
    "/api/settings",
})

#: Filesystem path prefixes that look like URL paths but are NOT agent routes.
_FILESYSTEM_PREFIXES = frozenset({
    "/content/",
    "/drive/",
    "/dev/",
    "/etc/",
    "/mnt/",
    "/proc/",
    "/root/",
    "/usr/",
    "/var/",
    "/tmp/",
    "/home/",
})

#: URL-path string literals that look like API paths (starts with /segment/...,
#: limited length to avoid matching long filesystem paths).
_PATH_LITERAL = re.compile(r'["\'](/[A-Za-z0-9_\-./{}]+?)["\']')


def _load_generator():
    spec = importlib.util.spec_from_file_location("ucn_paths", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cells() -> dict[int, str]:
    module = _load_generator()
    return {i: "".join(getattr(module, f"build_cell_{i}_source")()) for i in range(1, 8)}


def _balanced_block(source: str, start: int) -> str:
    """The parenthesised block that starts at `start`."""
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError("unbalanced parentheses")


def _normalise_rule(rule: str) -> str:
    """Collapse whitespace and the flag names, so two spellings of one rule compare equal."""
    rule = re.sub(r"\s+", " ", rule)
    rule = re.sub(r"\b_?IS_COLAB\b", "COLAB", rule)
    rule = re.sub(r"\b_?IS_MODAL\b", "MODAL", rule)
    return rule.strip()


def _workspace_rules() -> list[tuple[int, str]]:
    """Every workspace-root RULE in the notebook, normalised.

    A rule is the parenthesised conditional. A plain assignment
    """
    found = []
    for index, source in _cells().items():
        for match in re.finditer(r"\((.+?)\)", source):
            rule = match.group(1)
            if any(token in rule for token in ("IS_COLAB", "IS_MODAL", "os.path.exists")):
                found.append((index, _normalise_rule(rule)))
    return found


def _server_routes() -> set[str]:
    """Every route path registered on the FastAPI app in remote_agent/server.py.

    Parses the module via ast so the check is robust to decorator argument
    order and whitespace. Falls back to a literal-string scan if AST parse
    fails.
    """
    server_path = AGENT_DIR / "server.py"
    if not server_path.exists():
        return set()

    source = server_path.read_text()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set(_literal_routes(source))

    routes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            target = None
            if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute):
                target = deco.func.attr
            elif isinstance(deco, ast.Attribute):
                target = deco.attr
            if target not in ("get", "post", "put", "delete", "patch"):
                continue
            if isinstance(deco, ast.Call) and deco.args:
                first = deco.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    routes.add(first.value)
    return routes


def _literal_routes(source: str) -> set[str]:
    """Fallback: grab every string literal that looks like an API path."""
    routes: set[str] = set()
    for match in _PATH_LITERAL.finditer(source):
        path = match.group(1)
        if len(path) <= 60:
            routes.add(path.rstrip("/"))
    return routes


def _notebook_referenced_paths() -> set[str]:
    """API-path string literals referenced inside the notebook's cells.

    Excludes filesystem paths (prefixes under /content, /drive, /dev, /etc,
    /mnt, /proc, /root, /usr, /var, /tmp, /home) and known external paths.
    Normalises trailing slashes and brace path params so they compare with
    server.py's raw rule strings.
    """
    found: set[str] = set()
    for source in _cells().values():
        for match in _PATH_LITERAL.finditer(source):
            path = match.group(1)
            if len(path) > 60:
                continue
            # Skip filesystem paths (including bare /content, /root, /proc).
            if any(
                path == prefix.rstrip("/") or path.startswith(prefix)
                for prefix in _FILESYSTEM_PREFIXES
            ):
                continue
            # Skip URL fragments that are not API paths (e.g. /llama- in a
            # release download URL).
            if path.startswith("/llama-"):
                continue
            path = path.rstrip("/")
            path = re.compile(r"\{[^}]+\}").sub("{}", path)
            found.add(path)
    return found


class TestTheNotebookIsGenerated:
    def test_every_cell_is_valid_python(self):
        for index, source in _cells().items():
            try:
                compile(source, f"cell {index}", "exec")
            except SyntaxError as exc:
                raise AssertionError(f"cell {index} is not valid Python: {exc}") from exc

    def test_every_cell_has_a_name(self):
        module = _load_generator()
        for i in range(1, 8):
            assert hasattr(module, f"build_cell_{i}_source"), (
                f"cell {i} has no build_cell_{i}_source function"
            )
            src = "".join(getattr(module, f"build_cell_{i}_source")())
            assert src.strip(), f"cell {i} is empty"


class TestTheWorkspaceRootIsEnvironmentDerived:
    def test_every_cell_that_needs_it_defines_it(self):
        for index, source in _cells().items():
            if "WORKSPACE_ROOT" not in source:
                continue
            assert "WORKSPACE_ROOT =" in source, (
                f"cell {index} references WORKSPACE_ROOT but never assigns it"
            )
            assert "os.path.exists(\"/content\")" not in source.split("WORKSPACE_ROOT =")[0], (
                f"cell {index} decides WORKSPACE_ROOT by asking whether /content "
                f"exists before assigning it"
            )


class TestNoHardcodedWorkspacePaths:
    """Every workspace path goes through the rule.

    The rule is: Colab -> /content, Modal -> /root, fallback -> $HOME.
    A cell that hardcodes `/content/...` (outside Google Drive) or `/root/...`
    will break on the other backend.
    """

    def test_no_hardcoded_content_paths(self):
        for index, source in _cells().items():
            for match in _HARD_CODED.finditer(source):
                line_start = source.rfind("\n", 0, match.start()) + 1
                line = source[line_start : match.end()].strip()
                if any(
                    token in line
                    for token in ("WORKSPACE_ROOT", "PERSISTENT_ROOT", "os.path.join")
                ):
                    continue
                raise AssertionError(
                    f"cell {index} hardcodes a /content path outside Google Drive: {match.group(0)}"
                )

    def test_no_hardcoded_root_paths(self):
        for index, source in _cells().items():
            for match in re.finditer(r'["\'](/root/(?!tnhfantasy)[^"\']*)["\']', source):
                line_start = source.rfind("\n", 0, match.start()) + 1
                line = source[line_start : match.end()].strip()
                if any(token in line for token in ("WORKSPACE_ROOT", "PERSISTENT_ROOT")):
                    continue
                # Skip dotdirs and toolchains under /root that are not workspace
                # paths (cargo, local, cache, etc.).
                if any(seg in match.group(1) for seg in (".cargo/", ".local/", ".cache/")):
                    continue
                raise AssertionError(
                    f"cell {index} hardcodes a /root path outside tnhfantasy: {match.group(0)}"
                )


class TestTheLlamaServerIsVerified:
    """The notebook must not declare a provider healthy it cannot serve.

    The CUDA llama.cpp release is built for a specific Ubuntu and needs a
    glibc the container may not have — the b11647 CUDA 12.8 bundle wants
    GLIBC 2.38, and Modal's Debian 12 image has 2.36.

    The install used to be TRUSTED ON SIGHT: a cached bundle was restored
    from Google Drive and the notebook carried on. The binary could not
    start, the loader error scrolled past as a "device notice", and the
    notebook reported "Remote Agent is online and healthy" and "ComfyUI is
    online and healthy". The failure then surfaced much later, as a 503 from
    a provider that had been declared healthy — with nothing in the log to
    explain it.
    """

    def test_the_install_is_verified_by_running_the_binary(self):
        for index, source in _cells().items():
            if "_install_llama_server" not in source:
                continue
            assert "_llama_can_run(" in source, (
                f"cell {index} installs llama-server without checking that it "
                f"can run"
            )
            # And the check is a real run, not a file-exists test.
            assert '"--version"' in source, (
                f"cell {index} does not verify llama-server by running it"
            )

    def test_a_bundle_that_cannot_run_is_not_cached_again(self):
        """The cache is what made the failure permanent.

        The bundle was cached in Google Drive and restored on every run, so
        the same broken binary came back each time. A bundle that cannot run
        has to be discarded, not re-cached.
        """
        for index, source in _cells().items():
            if "_install_llama_server" not in source:
                continue
            body = source[source.index("def _install_llama_server"):]
            body = body[: body.index("\ndef ") if "\ndef " in body else len(body)]
            # Discarding means removing the cached bundle file (os.remove) or
            # rmtree'ing a cache directory.
            assert (
                "shutil.rmtree" in body
                or "cache_dir" in body
                or "os.remove(cached_bundle)" in body
            ), (
                f"cell {index} does not discard a non-runnable bundle"
            )


class TestNotebookRoutesExistInServer:
    """Every /path the notebook calls on the agent port must be a route in
    remote_agent/server.py (or a known external path).
    """

    def test_notebook_routes_exist_in_server(self):
        server_routes = _server_routes()
        notebook_paths = _notebook_referenced_paths()
        offending = sorted(
            p for p in notebook_paths if p not in server_routes and p not in _EXTERNAL_PATHS
        )
        assert not offending, (
            "The notebook calls agent routes that do not exist in "
            "remote_agent/server.py. Either add the route to server.py, "
            "remove the call from the notebook generator, or add the path "
            "to _EXTERNAL_PATHS if it genuinely targets another service.\n"
            f"  offending: {offending}\n"
            f"  server routes: {sorted(server_routes)}\n"
            f"  notebook paths: {sorted(notebook_paths)}"
        )

    def test_notebook_auth_header_matches_service_token(self):
        """The notebook sends `Authorization: Bearer <token>` to authenticated
        agent routes, matching SERVICE_TOKEN_HEADER in remote_agent_files.py.
        """
        from services.engines.remote_agent_files import SERVICE_TOKEN_HEADER

        assert SERVICE_TOKEN_HEADER == "Authorization", (
            f"SERVICE_TOKEN_HEADER is {SERVICE_TOKEN_HEADER!r}, expected 'Authorization'"
        )

        sources = "".join(_cells().values())
        assert "Authorization" in sources, (
            "The notebook never sets an Authorization header for agent calls"
        )
        assert "Bearer" in sources, (
            "The notebook never sends a Bearer token for agent calls"
        )


class TestNotebookModeKeyMapping:
    """The notebook's WORKER_MODE -> mode_key -> provider_type mapping must
    agree with the engine registry and the sidecar's WORKER_MODES.
    """

    def _cell5(self) -> str:
        module = _load_generator()
        return "".join(getattr(module, "build_cell_5_source")())

    def test_notebook_mode_key_mapping(self):
        from services.engines.registry import ENGINE_SPECS

        cell5 = self._cell5()

        m = re.search(r'provider_type\s*=\s*(\{[^}]+\})', cell5)
        assert m, "cell 5 has no provider_type dict literal"
        mapping = ast.literal_eval(m.group(1))

        assert set(mapping) == {
            "hybrid",
            "model",
            "storage",
            "llm",
            "tts",
        }, f"provider_type keys {set(mapping)} != expected 5 modes"

        expected_values = {
            "hybrid": "remote_hybrid",
            "model": "remote_comfy",
            "storage": "remote_comfy",
            "llm": "remote_llm",
            "tts": "remote_tts",
        }
        assert mapping == expected_values, (
            f"provider_type mapping {mapping} != {expected_values}"
        )

        # Every value must be a valid engine spec id.
        for value in mapping.values():
            assert value in ENGINE_SPECS, (
                f"provider_type value {value!r} is not an ENGINE_SPECS key"
            )

        # provider_worker_type values must be valid categories.
        m2 = re.search(r'provider_worker_type\s*=\s*(\{[^}]+\})', cell5)
        assert m2, "cell 5 has no provider_worker_type dict literal"
        worker_mapping = ast.literal_eval(m2.group(1))
        from core.entities import VALID_CATEGORIES

        for vt in worker_mapping.values():
            assert vt in VALID_CATEGORIES, (
                f"provider_worker_type value {vt!r} is not in VALID_CATEGORIES"
            )

    def test_notebook_mode_key_values_are_valid_worker_modes(self):
        cell5 = self._cell5()

        # Import server module like test_remote_agent_storage_mode.py does.
        sys.path.insert(0, str(AGENT_DIR))
        sys.modules.pop("server", None)
        import server as srv  # noqa: PLC0415

        mode_keys = set(re.findall(r'mode_key\s*==\s*["\']([^"\']+)["\']', cell5))
        assert mode_keys, "cell 5 has no mode_key comparisons"
        assert mode_keys <= set(srv.WORKER_MODES), (
            f"mode_keys {mode_keys} not all in WORKER_MODES {set(srv.WORKER_MODES)}"
        )


class TestTheShmRemountIsBounded:
    def test_it_only_runs_when_shm_is_too_small(self):
        """The remount needs CAP_SYS_ADMIN, which a container does not have.

        It ran unconditionally and printed the kernel's "mount: /dev/shm:
        permission denied" wherever the container had no privilege — on Modal,
        where /dev/shm is already 40 GB and the remount was never wanted.
        """
        remounts = 0
        for index, source in _cells().items():
            if "remount,size=" not in source:
                continue
            remounts += 1
            assert "current_shm_gb < target_shm_gb" in source, (
                f"cell {index} remounts /dev/shm without checking its size"
            )
            # And quietly: the kernel's error is not the operator's problem
            # to read.
            assert "stderr=subprocess.DEVNULL" in source, (
                f"cell {index} lets the kernel's mount error through"
            )
        assert remounts >= 1, "no remount was found at all"
