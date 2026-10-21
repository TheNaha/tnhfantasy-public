# Pytest configuration and fixtures

import json
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from api.deps import get_session
from api.main import app
import infrastructure.database as _infra_db

# Disable provider health checks in tests (LoadBalancer defaults to enabled in prod)
os.environ.setdefault("COMFY_LB_HEALTH_CHECKS_ENABLED", "0")


# Need to import all models so SQLModel metadata is complete


@pytest.fixture(autouse=True)
def _isolate_config_file(tmp_path_factory):
    """Point every test at its OWN config.json, never the live one.

    `PUT /api/settings` persists, and it persists to `config._config_path` -
    which, in the test suite, is the operator's real `backend_v2/config.json`.
    So the suite was rewriting the live configuration.

    Two per-file fixtures tried to compensate by restoring the file
    afterwards, and both are defeated by the suite's parallelism:

      - `test_settings_route.py` restores the file at teardown, so the live
        config is wrong for the whole run;
      - with eight xdist workers, worker A's restore can land BEFORE worker
        B's write, and the file is left with worker B's value.

    That is not hypothetical: running the suite left the live
    `jobs.max_concurrent` at 3 instead of the operator's 5, and rewrote the
    whole file from the defaults - which is how a setting nobody touched
    changed.

    The fix is not another restore. It is to make the write go somewhere
    else: every test gets a private copy of the operator's config, and the
    live path is restored on the way out.
    """
    import shutil

    import config as cfg

    original_path = cfg._config_path
    target = tmp_path_factory.mktemp("config") / "config.json"
    try:
        shutil.copyfile(original_path, target)
    except OSError:
        target.write_text(
            json.dumps(cfg.DEFAULT_CONFIG, indent=2), encoding="utf-8"
        )
    cfg._config_path = str(target)
    try:
        yield str(target)
    finally:
        cfg._config_path = original_path


@pytest.fixture(name="engine")
def engine_fixture():
    """Create in-memory SQLite engine for testing.

    Foreign-key enforcement is switched ON. SQLite ignores FKs by default, so
    without this the whole suite was blind to exactly the class of bug Postgres
    rejects at runtime — e.g. delete_character raising IntegrityError because
    voice_models.character_id still pointed at the deleted row. Enabling it here
    means a schema/reference mistake fails in CI instead of in production.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

        # SQLite has no md5/sha by default, Postgres does. Registering the two
        # digests the application uses means a query can be written once and run
        # unchanged on both, instead of branching on dialect — which is what
        # `services/statistics_service._prompt_signature` does, keying the prompt
        # cache on an exact content hash. Without this the test dialect rejects
        # the very statement production executes.
        import hashlib

        for name, constructor in (("md5", hashlib.md5), ("sha256", hashlib.sha256)):
            dbapi_connection.create_function(
                name, 1, lambda value, c=constructor: c(value.encode("utf-8")).hexdigest()
            )

    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    """Create database session for testing."""
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def _redirect_sync_sessions(engine):
    """Point every `get_session_sync()` caller at the test database.

    Service code opens its own session through `get_session_sync()` —
    statistics aggregation, reconciliation, the load balancer, file cleanup.
    Two things made that hard to contain:

    * the redirection used to live inside `client_fixture`, so a test that
      exercised such a service *without* requesting `client` ran against the
      developer's real `data/comfy.db` — it saw production rows, and a service
      that writes would have written them.
    * modules that do `from api.deps import get_session_sync` bind the function
      into their own namespace at import time, so rebinding the attribute on
      `api.deps` (or `infrastructure.database`) afterwards never reached them.
      `api/routes/files.py` is the case that surfaced it: its `_sync_session()`
      quietly used the on-disk database.

    So this rebinds the name in every already-imported module, not just on the
    two modules that define it.
    """
    def get_session_sync_override():
        return Session(engine)

    import api.deps as _api_deps

    original_infra = _infra_db.get_session_sync
    original_deps = _api_deps.get_session_sync
    # Also redirect the module-level `engine`. Code that constructs
    # `Session(engine)` or `engine.begin()` directly bypasses `get_session_sync`
    # entirely, and in tests that resolved to the developer's real
    # `data/comfy.db` — a background job-finalize task did exactly that, ran
    # against a stale schema, and failed with "no such column", leaving the job
    # stuck in post-processing while the test polled for a terminal state. The
    # `get_session_sync` redirect alone does not cover that path.
    original_engine = _infra_db.engine
    _infra_db.engine = engine

    known_originals = {id(original_infra), id(original_deps)}

    rebound: list[tuple[object, str, object]] = []
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for module in list(sys.modules.values()):
        if module is None:
            continue
        # Only probe modules that belong to this backend. `getattr` is not a
        # passive read: a module with a PEP 562 module-level `__getattr__`
        # resolves an unknown name by *importing* the submodule it names. Probing
        # `transformers` for `get_session_sync` therefore imported
        # `transformers/models/aria/image_processing_aria.py`, which imports
        # `torchvision` — which is not in requirements.txt. The fixture raised,
        # and because it is autouse every test after the first one that touched
        # the embedding stack errored too: 1355 of 2832 tests in CI run
        # 37124915160, on a Python that had transformers installed. The local
        # venv cannot import transformers at all, so the suite was green here and
        # red in CI for three days.
        module_file = getattr(module, "__file__", None) or ""
        if not module_file.startswith(backend_root + os.sep):
            continue
        current = getattr(module, "get_session_sync", None)
        if current is not None and id(current) in known_originals:
            setattr(module, "get_session_sync", get_session_sync_override)
            rebound.append((module, current))

    _infra_db.get_session_sync = get_session_sync_override
    _api_deps.get_session_sync = get_session_sync_override
    try:
        yield
    finally:
        _infra_db.get_session_sync = original_infra
        _api_deps.get_session_sync = original_deps
        _infra_db.engine = original_engine
        for module, original in rebound:
            module.get_session_sync = original


@pytest.fixture(autouse=True, scope="session")
def _remote_agent_token():
    """Let `remote_agent/server.py` be imported by any test, in any order.

    The module refuses to import without a token:

        RuntimeError: REMOTE_AGENT_TOKEN must be set unless
        REMOTE_AGENT_ALLOW_INSECURE=1

    So the tests that import it only passed if some EARLIER test had
    happened to set the variable - which is why they worked in the serial
    suite and failed under a parallel one, where the distribution is
    different. A test that only passes in the right order is not a test.

    The token is a test value, and the tests that exercise the auth path set
    their own.
    """
    previous = os.environ.get("REMOTE_AGENT_TOKEN")
    os.environ["REMOTE_AGENT_TOKEN"] = "test-token"
    yield
    if previous is None:
        os.environ.pop("REMOTE_AGENT_TOKEN", None)
    else:
        os.environ["REMOTE_AGENT_TOKEN"] = previous


@pytest.fixture(autouse=True)
def _stub_laya_runner(monkeypatch):
    """The Director's local tier must not load a real model in a test.

    `laya.load()` pulls a 200 MB transformer out of HuggingFace and runs it
    on CPU: roughly 40 seconds on the first call in a process, and a
    DOWNLOAD on a machine that does not have it cached. With eight xdist
    workers that is eight loads, and it dominated the suite's critical path.

    The tier itself is the product behaviour and the tests assert the
    DECISION it produces, not which tier produced it. So the runner answers
    the questions deterministically instead of loading anything.
    """
    from services import laya_runner

    def _fake_evaluate(self, *, context_text, questions, model_id, **kwargs):
        answers = {}
        for question in questions or []:
            key = question.get("key")
            if not key:
                continue
            qtype = question.get("type")
            if qtype == "choice":
                options = list((question.get("options") or {}).keys())
                answers[key] = options[0] if options else "default"
            elif qtype == "noul":
                answers[key] = "false"
            elif qtype == "score":
                answers[key] = 0.5
            else:
                answers[key] = ""
        return {"answers": answers, "model_id": model_id, "latency_ms": 0.0}

    monkeypatch.setattr(laya_runner.LayaRunner, "evaluate", _fake_evaluate)
    yield


@pytest.fixture(autouse=True)
def _stub_embedding_service(monkeypatch):
    """Never load a real sentence-transformers model in a test.

    `services.embedding_service.EmbeddingService` lazy-loads
    `all-MiniLM-L6-v2` from HuggingFace on first use. One test that reached
    an embedding call spent **15 seconds** loading the model, and a cold
    machine DOWNLOADS it — 1.6 GB of models in `~/.cache/huggingface` after
    one suite run, on the test path rather than the application path.

    That is a speed problem and a correctness one: a test suite that
    downloads a model is a suite that fails on a runner without internet, or
    on one with a small disk, and the failure looks like a test failure
    rather than a missing dependency.

    The stub returns a deterministic zero vector of the model's dimension.
    A zero vector is the right no-op here: the production code already
    returns one for an empty text, and similarity against it is uniformly
    uninformative, which is what a test wants.

    The stub patches the CLASS's methods, not the factory. A test that cares
    about embedding behaviour patches the same methods
    (`monkeypatch.setattr` inside the test body runs after this fixture, so
    the test's own patch wins) - `tests/test_data_integrity_fixes.py` and
    `tests/test_rag_pipeline.py` both do exactly that. Patching the FACTORY
    instead would bypass the class patch entirely, and the test would assert
    against the stub's zeros.
    """
    import services.embedding_service as embedding_module

    def _zero_embedding(self, text):
        return [0.0] * 384

    def _zero_embeddings(self, texts):
        return [[0.0] * 384 for _ in texts]

    monkeypatch.setattr(
        embedding_module.EmbeddingService, "generate_embedding", _zero_embedding
    )
    monkeypatch.setattr(
        embedding_module.EmbeddingService, "generate_embeddings", _zero_embeddings
    )
    yield


@pytest.fixture(autouse=True)
def _reset_service_caches():
    """Clear the module-level caches in `services.statistics_service` per test.

    `_PROMPT_CACHE` and `_HISTOGRAM_CACHE` are process-global and outlive the
    database: every test gets a fresh in-memory SQLite engine, so a histogram
    cached by one test is a histogram computed against a *different* dataset.
    Nothing in the suite failed from that at random before the histogram cache
    existed because `_PROMPT_CACHE` is keyed on a content signature that differs
    per fixture; `_HISTOGRAM_CACHE` is keyed on the filter tuple, and the
    unfiltered tuple is the same string for every test in the run. Two existing
    assertions depend on it — `/api/v2/assets/dates` answering `total == 1` in
    one test and `total == 0` in another — so the reset has to be automatic
    rather than something each test remembers to ask for.
    """
    from services import statistics_service

    statistics_service._PROMPT_CACHE.clear()
    statistics_service._HISTOGRAM_CACHE.clear()
    yield
    statistics_service._PROMPT_CACHE.clear()
    statistics_service._HISTOGRAM_CACHE.clear()


@pytest.fixture(name="client")
def client_fixture(session: Session, engine):
    """Create test client with overridden database session."""
    def get_session_override():
        return session

    def get_session_sync_override():
        return Session(engine)

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def tts_capable(session):
    """A provider that declares the `tts` capability.

    Every TTS endpoint refuses with a 400 when nothing declares it — that is the
    intended behaviour, not a test obstacle — so a test that is about something
    else needs one to get past the guard. Lives here rather than in
    `test_voices.py` because the narrate routes (`chats` and `stories`) are
    guarded by the same `_require_tts_capable`.
    """
    from core.entities import Provider

    provider = Provider(
        id="tts-provider", type="modal", worker_type="image",
        capabilities=["image", "tts"], enabled=True,
    )
    session.add(provider)
    session.commit()
    return provider


@pytest.fixture
def sample_workflow():
    """Sample ComfyUI workflow for testing."""
    return {
        "nodes": {
            "1": {"class_type": "KSampler", "inputs": {}},
            "2": {"class_type": "VAEDecode", "inputs": {}},
        }
    }


@pytest.fixture
def sample_job_data(sample_workflow):
    """Sample job creation data."""
    return {
        "workflow": sample_workflow,
        "metadata": {
            "prompt": "a beautiful landscape",
            "seed": 12345,
            "width": 512,
            "height": 512
        }
    }


@pytest.fixture
def sample_provider_data():
    """Sample provider creation data."""
    return {
        "id": "test-provider",
        "type": "modal",
        "enabled": True,
        "priority": 1,
        "credentials": {"token_id": "tok_123", "token_secret": "secret_456"},
        "config": {"app_name": "test-app"}
    }


@pytest.fixture
def sample_model_data():
    """Sample model creation data."""
    return {
        "name": "test-model.safetensors",
        "directory": "checkpoints",
        "url": "https://example.com/model.safetensors",
        "source": "custom",
        "metadata": {"size": 1000000}
    }


@pytest.fixture
def sample_model_v2_data():
    """Sample model V2 creation data."""
    return {
        "civitai_data": {
            "id": 12345,
            "name": "Test Model V2",
            "type": "Checkpoint",
            "nsfw": False,
            "creator": {"username": "testuser"},
            "description": "Test description",
            "stats": {"downloadCount": 100},
            "tags": ["anime", "style"],
            "modelVersions": [
                {
                    "id": 67890,
                    "name": "v1.0",
                    "baseModel": "SD 1.5",
                    "files": [
                        {
                            "name": "model.safetensors",
                            "sizeKB": 2048000,
                            "type": "Model",
                            "metadata": {"format": "SafeTensor", "size": "pruned", "fp": "fp16"},
                            "pickleScanMessage": "No Pickle imports",
                            "virusScanMessage": "No virus found",
                            "scannedAt": "2023-01-01T00:00:00.000Z",
                            "hashes": {"AutoV2": "1234567890"},
                            "downloadUrl": "https://civitai.com/api/download/models/67890",
                            "primary": True
                        }
                    ],
                    "images": []
                }
            ]
        },
        "selected_versions": [
            {"version_id": 67890, "is_default": True}
        ]
    }
