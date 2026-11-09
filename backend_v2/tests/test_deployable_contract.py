"""Every provider deployable must publish what its engine looks up.

`deployables/README.md` asserted a "name contract, verified" that was false: the
LLM engine performed seven `modal.*.from_name` lookups and the `tnh-llm` app
published none of them. It read like a verification because it was prose with
file:line citations in it, which is exactly what a stale contract always looks
like. Nothing executed either side.

So this module executes both sides of the contract by *parsing* them. The
engine files are AST-walked for every `modal.Cls.from_name` /
`modal.Function.from_name` call and every method reached through the class
handle; the deployables are AST-walked for every `@app.cls`, `@app.function`,
`@app.cls` method and `modal.App(...)` name. Both directions are derived from
the real source, so neither this test nor the README can drift away from the
code without the suite going red.

The check is deliberately *structural* — names and arity — rather than a
behavioural deploy. A behavioural test would need live Modal and Beam
credentials; this one needs none and therefore runs in CI on every push, which
is the only place a contract test earns its keep.

Beam and remote are URL-shaped rather than SDK-name-shaped, so their assertion
is the deployable's real route table against an explicit expectation. The
deployable side is still derived rather than restated; only the expectation is
written by hand, and each entry says why it exists.
"""

import ast

import pytest

from tests.repo_paths import require_repo_root

ROOT = require_repo_root("deployables/")


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _str_const(node):
    """The string a node is, following one level of a named constant."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _module_assignments(tree):
    """Module-level `NAME = "str"` and `NAME = os.getenv("X", "default")`."""
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        literal = _str_const(node.value)
        if literal is not None:
            out[target.id] = literal
            continue
        # os.getenv("ENV", "default") -> the default is the published name.
        if (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "getenv"
        ):
            default = _str_const(node.value.args[1]) if len(node.value.args) > 1 else None
            if default is not None:
                out[target.id] = default
    return out


def _dotted(node):
    """`modal.Cls.from_name` -> "modal.Cls.from_name"; None otherwise."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _class_method_names(class_node):
    """Method names defined on a Modal class (decorator-agnostic)."""
    return {
        item.name
        for item in class_node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _is_decorated(node, *attr_names):
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if _dotted(target) is None:
            continue
        if _dotted(target).split(".")[-1] in attr_names:
            return True
    return False


# ---------------------------------------------------------------------------
# Engine side: what does the backend ask for?
# ---------------------------------------------------------------------------


def _engine_lookups(source_path, class_name_defaults):
    """Every Modal name + method an engine reaches for.

    `class_name_defaults` maps the `self.<attr>` a lookup uses (e.g.
    `cls_name`) to the engine's default value, because those lookups carry no
    literal — the class name is resolved through the factory at runtime.
    """
    tree = ast.parse(source_path.read_text())

    functions = set()
    classes = set()
    #: class name -> methods called through its handle
    class_methods = {}

    # `<var> = modal.Cls.from_name(app, "X")` and `inst = <var>()`.
    class_handle = {}   # local var -> class name
    instance_handle = {}  # local var -> class name

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                value = node.value
                if (
                    isinstance(value, ast.Call)
                    and _dotted(value.func) in ("modal.Function.from_name", "modal.Cls.from_name")
                    and value.args
                ):
                    literal = _str_const(value.args[1]) if len(value.args) > 1 else None
                    if literal is None and isinstance(value.args[1], ast.Attribute):
                        literal = class_name_defaults.get(value.args[1].attr)
                    if literal is None:
                        continue
                    if _dotted(value.func) == "modal.Function.from_name":
                        functions.add(literal)
                    else:
                        classes.add(literal)
                        class_handle[target.id] = literal
                # `instance = SomeCls()` — remember what it holds.
                elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                    held = class_handle.get(value.func.id)
                    if held:
                        instance_handle[target.id] = held

        # `inst.method` -> that class must define `method`.
        if isinstance(node, ast.Attribute):
            held = instance_handle.get(node.value.id if isinstance(node.value, ast.Name) else None)
            if held:
                class_methods.setdefault(held, set()).add(node.attr)

    return functions, classes, class_methods


# ---------------------------------------------------------------------------
# Deployable side: what is actually published?
# ---------------------------------------------------------------------------


def _modal_deployable(source_path):
    """(app name, {class: methods}, {functions}) for one Modal deployable."""
    tree = ast.parse(source_path.read_text())
    assigns = _module_assignments(tree)

    app_name = None
    classes = {}
    functions = set()

    def resolve(node):
        """A string, following one level of a named constant."""
        literal = _str_const(node)
        if literal is not None:
            return literal
        if isinstance(node, ast.Name):
            return assigns.get(node.id)
        # `modal.App(os.getenv("MODAL_APP_NAME", "comfy-modal-stack"))`
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "getenv"
            and len(node.args) > 1
        ):
            return _str_const(node.args[1])
        return None

    for node in ast.walk(tree):
        # `app = modal.App(APP_NAME)` — an Assign, so the call is the value.
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            node = node.value
        if isinstance(node, ast.Call) and _dotted(node.func) in ("modal.App", "App"):
            if node.args and (found := resolve(node.args[0])):
                app_name = found
            continue

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _is_decorated(node, "cls"):
            classes[node.name] = _class_method_names(node)
            continue
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _is_decorated(node, "function")
        ):
            functions.add(node.name)

    return app_name, classes, functions


#: `websocket` is here because the Beam LLM/TTS dialect is a socket, not a
#: request — `@realtime` cannot serve it, so those paths are `@app.websocket`
#: on an `@asgi` deployment and a get/post-only extractor misses them entirely.
_ROUTE_VERBS = frozenset({"get", "post", "put", "delete", "patch", "websocket"})


def _served_paths(source_path):
    """Every route a FastAPI deployable registers, via decorator paths.

    A deployable may mount several apps on one deployment (`beam_app.py` has
    `storage_app`, `download_app` and `extractor_app`; `llm_tts_app.py` has
    `llm_app` and `tts_app`), so the receiver name is not pinned to `app` — only
    the verb is.
    """
    tree = ast.parse(source_path.read_text())
    paths = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in getattr(node, "decorator_list", []):
            if not isinstance(dec, ast.Call):
                continue
            dotted = _dotted(dec.func)
            if not dotted or dotted.rsplit(".", 1)[-1] not in _ROUTE_VERBS:
                continue
            if dec.args:
                literal = _str_const(dec.args[0])
                if literal:
                    paths.add(literal)
    return paths


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------

MODAL_APPS = {
    "modal": (
        "backend_v2/services/engines/modal_engine.py",
        "deployables/modal/image/modal_app.py",
        "comfy-modal-stack",
        # The image engine resolves its class at dispatch from a snapshot flag
        # (`class_name = "ComfyUISnapshot" if use_snapshot else
        # "ComfyUIStable"`), so the AST sees only the variable. Name both.
        {"class_name": "ComfyUIStable", "ComfyUISnapshot": "ComfyUISnapshot"},
        ("ComfyUISnapshot", "ComfyUIStable"),
    ),
    "modal_tts": (
        "backend_v2/services/engines/modal_tts_engine.py",
        "deployables/modal/tts/modal_app.py",
        "comfy-modal-tts",
        {"cls_name": "TTSWorker", "storage_cls_name": "TTSFileStorage"},
        ("TTSWorker", "TTSFileStorage"),
    ),
    "modal_llm": (
        "backend_v2/services/engines/llm_engine.py",
        "deployables/modal/llm/app.py",
        "tnh-llm",
        {"cls_name": "ChatLLM"},
        ("ChatLLM",),
    ),
}


class TestModalNameContract:
    """`ENGINE_SPECS` -> engine source -> deployable source, both directions."""

    @pytest.mark.parametrize("provider_type", sorted(MODAL_APPS))
    def test_every_looked_up_name_is_published(self, provider_type):
        engine_rel, rel, expected_app, cls_defaults, also_expected = MODAL_APPS[provider_type]
        source = ROOT / rel
        assert source.exists(), f"{rel} is missing; the provider type has no deployable"

        engine_source = ROOT / engine_rel
        assert engine_source.exists(), f"{engine_rel} is missing"
        functions, classes, class_methods = _engine_lookups(engine_source, cls_defaults)
        published_app, published_classes, published_functions = _modal_deployable(source)

        assert published_app == expected_app, (
            f"{rel} publishes app {published_app!r}, the contract expects {expected_app!r}"
        )

        # Classes the engine only ever names at runtime. Without this the TTS
        # and image contracts pass vacuously — every one of their lookups is
        # `self.cls_name`, which carries no literal for the AST to read.
        missing_runtime = set(also_expected) - set(published_classes)
        assert not missing_runtime, (
            f"{provider_type}: the engine resolves {sorted(also_expected)} at dispatch, "
            f"and {rel} does not define {sorted(missing_runtime)}"
        )

        missing_functions = functions - published_functions
        assert not missing_functions, (
            f"{provider_type}: engine calls Function.from_name for "
            f"{sorted(missing_functions)}, which {rel} does not define. "
            f"It defines: {sorted(published_functions)}"
        )

        missing_classes = classes - set(published_classes)
        assert not missing_classes, (
            f"{provider_type}: engine calls Cls.from_name for "
            f"{sorted(missing_classes)}, which {rel} does not define. "
            f"It defines: {sorted(published_classes)}"
        )

        for cls_name, methods in sorted(class_methods.items()):
            if cls_name not in published_classes:
                continue  # already reported above
            missing_methods = methods - published_classes[cls_name]
            assert not missing_methods, (
                f"{provider_type}: engine calls {sorted(missing_methods)} on "
                f"{cls_name}, which {rel} does not define. "
                f"It defines: {sorted(published_classes[cls_name])}"
            )

    @pytest.mark.parametrize("provider_type", sorted(MODAL_APPS))
    def test_registry_default_app_name_matches_the_deployable(self, provider_type):
        """The UI seeds `config.app_name` from this default on every save.

        `ProviderModal.schemaConfigDefaults()` copies every schema `default`
        into the payload, and `engine_factory.get_engine` reads `config.app_name`
        BEFORE its own fallback. So a wrong default here is not cosmetic: it is
        the app name every provider created through the modal will dial.
        """
        from services.engines.registry import ENGINE_SPECS

        _, _, expected_app = MODAL_APPS[provider_type][:3]
        fields = {f["key"]: f for f in ENGINE_SPECS[provider_type].get("config", [])}
        if "app_name" not in fields:
            return
        default = fields["app_name"].get("default")
        assert default == expected_app, (
            f"registry.py declares default app_name {default!r} for {provider_type}, "
            f"but the deployable publishes {expected_app!r}. A provider created in the "
            f"Providers modal would dial an app that does not exist."
        )


BEAM_EXPECTATIONS = {
    # BeamEngine (image)
    "deployables/beam/beam_app.py": {
        "/list-models", "/get-file", "/delete-file", "/delete-model",
        "/upload-file", "/validate-models", "/validate-all-models",
        "/setup", "/download-model", "/object_info", "/health",
    },
    # BeamLLMEngine / BeamTTSEngine websocket dialects.
    #
    # These were missing entirely, which is why the two types were phantoms:
    # `registry.py` offered them to operators and `_ws_target` dialled
    # `{gpu_url}/llm` and `{gpu_url}/tts`, and no deployment served either.
    # `@realtime` cannot serve them — it binds one handler at the deployment
    # root with no path routing — so they are `@asgi` FastAPI deployments.
    "deployables/beam/llm_tts_app.py": {
        "/llm", "/tts", "/health",
        "/v1/chat/completions", "/v1/models", "/v1/decisions", "/v1/voices",
        "/download-model", "/list-models", "/validate-models", "/delete-model",
    },
}


class TestBeamRouteContract:
    @pytest.mark.parametrize("rel", sorted(BEAM_EXPECTATIONS))
    def test_served_routes_cover_every_engine_call(self, rel):
        source = ROOT / rel
        assert source.exists(), f"{rel} is missing"
        served = _served_paths(source)
        expected = BEAM_EXPECTATIONS[rel]
        missing = expected - served
        assert not missing, (
            f"{rel} does not serve {sorted(missing)}. The engines dial these and get "
            f"nothing. It serves: {sorted(served)}"
        )


REMOTE_EXPECTATIONS = {
    "remote_agent/server.py": {
        # Registered at module scope — every WORKER_MODE gets these.
        "/health", "/info", "/setup", "/download-model", "/list-models",
        "/delete-model", "/delete-file", "/get-file/{path:path}", "/upload-file",
        "/validate-models", "/validate-all-models",
        # Gated behind WORKER_MODE.
        "/v1/chat/completions", "/synthesize",
    },
}


class TestRemoteRouteContract:
    @pytest.mark.parametrize("rel", sorted(REMOTE_EXPECTATIONS))
    def test_served_routes_cover_every_engine_call(self, rel):
        source = ROOT / rel
        assert source.exists(), f"{rel} is missing"
        served = _served_paths(source)
        expected = REMOTE_EXPECTATIONS[rel]
        missing = expected - served
        assert not missing, (
            f"{rel} does not serve {sorted(missing)}."
        )