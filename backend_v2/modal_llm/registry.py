"""
TNH LLM registry — the ONE definition of which model serves which role.

Read by both sides so they cannot drift:

  * ``modal_llm/app.py`` imports this to register one Modal function per enabled
    model, and embeds ``models.json`` into the image so the deployed function can
    read its own role and sampler.
  * ``backend_v2/services/llm_router.py`` imports it to resolve
    job-kind -> role -> model, and for the per-model sampler defaults.

The shape lives in ``modal_llm/models.json``. Editing that file is the whole
interface — no code changes, no reordering a hard-coded list somewhere else.

Design notes:

* One ``models.json`` beats a Python list because the file is the thing an
  operator edits, and because it can be embedded into the Modal image and read
  from the backend without either side owning a second copy.
* ``_comment`` / ``_note`` keys are carried through rather than stripped, so a
  model's rationale travels with the entry that uses it.
* Fallback order is *per role*, not global, so a role's ordering can be
  reordered without disturbing the other.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

#: The registry file, resolved by search rather than by fixed depth.
#
# Fixed-depth was wrong in both directions. This module is imported from two
# places that live at different depths: the Modal app (a sibling directory) and
# the backend service. `Path(__file__).parent.parent` is the repo root in one
# and `/` in the other — and inside the backend container, where the build
# context is `backend_v2/` and the repo root does not exist, that produced
# `/modal_llm/models.json`, a path that is present in no deployment. So the file
# lives INSIDE the deployable unit and each side looks beside itself first.
_REGISTRY_CANDIDATES = (
    Path(__file__).resolve().parent / "models.json",
    Path(__file__).resolve().parent.parent / "modal_llm" / "models.json",
    Path(__file__).resolve().parents[1] / "modal_llm" / "models.json"
    if len(Path(__file__).resolve().parents) > 1 else None,
)


def _resolve_registry_path() -> Path:
    """The models.json that exists, preferring the one beside this module."""
    env_override = os.environ.get("LLM_REGISTRY_PATH")
    if env_override:
        return Path(env_override)
    for candidate in _REGISTRY_CANDIDATES:
        if candidate and candidate.is_file():
            return candidate
    return Path(__file__).resolve().parent / "models.json"


REGISTRY_PATH = _resolve_registry_path()

#: Defaults a model entry may omit. Mirrored in the JSON's own DEFAULTS comment
#: so a reader of the file alone can see what an omitted key means.
DEFAULTS: Dict[str, Any] = {
    "mmproj": None,
    "mmproj_repo": None,
    "dir": None,
    "ctx": 32768,
    "parallel": 1,
    "kv": None,
    "gpu": "L40S",
    "idle": 300,
    "startup": 600,
    "sampler": {},
    "extra_args": [],
    "enabled": True,
}

#: Fields that are metadata, not model config. Kept for documentation but never
#: passed to llama-server or to an HTTP request.
_META_KEYS = {"role", "enabled", "_note"}


@dataclass(frozen=True)
class Model:
    """One deployable model, fully resolved with defaults applied."""

    id: str
    role: str
    repo: str
    gguf: str
    mmproj: Optional[str] = None
    mmproj_repo: Optional[str] = None
    dir: Optional[str] = None
    ctx: int = 32768
    parallel: int = 1
    kv: Optional[str] = None
    gpu: str = "L40S"
    idle: int = 300
    startup: int = 600
    sampler: Dict[str, Any] = field(default_factory=dict)
    extra_args: List[str] = field(default_factory=list)
    enabled: bool = True
    note: Optional[str] = None

    @property
    def volume_dir(self) -> str:
        """The Volume folder holding this model's weights.

        A model that shares another's weights (the `util` twin of an `rp` entry)
        declares no `dir`, and falls back to the id it shares with. That is how
        one download serves two functions.
        """
        return self.dir or self.id

    @property
    def has_vision(self) -> bool:
        return bool(self.mmproj)

    def llama_args(self) -> List[str]:
        """The llama-server flags this model needs, in order.

        Order is not cosmetic: `-m` must precede the model path, and the KV-cache
        flags must not appear twice when a model declares `extra_args`. Returned
        rather than built in place so a caller can diff it in a test.
        """
        args = [
            "-m", f"/models/{self.volume_dir}/{self.gguf}",
            "--alias", self.id,
            "-ngl", "99",
            "-c", str(self.ctx * self.parallel),
            "--parallel", str(self.parallel),
            "--jinja",
        ]
        if self.mmproj:
            args += ["--mmproj", f"/models/{self.volume_dir}/{self.mmproj}"]
        if self.kv:
            args += ["--cache-type-k", self.kv, "--cache-type-v", self.kv]
        args += list(self.extra_args)
        return args


@dataclass(frozen=True)
class Registry:
    """The parsed registry: models plus per-role fallback order."""

    models: Dict[str, Model]
    fallback: Dict[str, List[str]]

    def role_order(self, role: str) -> List[str]:
        """Model ids for a role, in fallback order, disabled ones dropped."""
        return [m for m in self.fallback.get(role, []) if m in self.enabled_ids()]

    def enabled_ids(self) -> List[str]:
        return [mid for mid, m in self.models.items() if m.enabled]

    def enabled_for(self, role: str) -> List[Model]:
        """Every enabled Model for a role, in fallback order."""
        return [self.models[mid] for mid in self.role_order(role) if mid in self.models]

    def get(self, model_id: str) -> Model:
        try:
            return self.models[model_id]
        except KeyError:
            raise KeyError(
                f"model {model_id!r} is not in the registry; "
                f"known ids: {sorted(self.models)}"
            ) from None

    def primary(self, role: str) -> Model:
        """The first enabled model for a role.

        Raises rather than returning None when a role has nothing usable: a
        caller that resolves to None would dispatch a job with no model, which
        surfaces as a provider error far from the cause.
        """
        ordered = self.enabled_for(role)
        if not ordered:
            raise LookupError(f"role {role!r} has no enabled model in the registry")
        return ordered[0]


def load(path: Optional[Path] = None) -> Registry:
    """Parse the registry, applying defaults and validating what it declares.

    Fails loudly on the two mistakes that are expensive to discover at deploy
    time: a fallback entry naming a model that does not exist, and a model whose
    role is not declared in `roles`. Both are silent in JSON.
    """
    registry_path = Path(path) if path else REGISTRY_PATH
    raw = json.loads(registry_path.read_text(encoding="utf-8"))

    roles_raw: Dict[str, Any] = raw.get("roles") or {}
    models_raw: Dict[str, Any] = raw.get("models") or {}
    if not models_raw:
        raise ValueError(f"{registry_path} declares no models")

    known_roles = set(roles_raw)
    models: Dict[str, Model] = {}
    for model_id, spec in models_raw.items():
        # `_note` is renamed off `merged`, not off `spec`: `merged` is the copy
        # the key check reads, so popping the wrong one leaves the underscore key
        # in `merged` and the check rejects the field carrying the rationale.
        merged = {**DEFAULTS, **spec}
        merged.pop("dir", None)
        merged["dir"] = spec.get("dir")
        merged.pop("_comment", None)
        merged["note"] = merged.pop("_note", None)
        role = merged.pop("role")
        merged["enabled"] = merged.pop("enabled", DEFAULTS["enabled"])
        if known_roles and role not in known_roles:
            raise ValueError(
                f"model {model_id!r} declares role {role!r}, which is not in "
                f"`roles` ({sorted(known_roles)}); a typo here silently removes "
                "the model from every role's fallback list"
            )
        allowed = {f for f in Model.__dataclass_fields__ if f != "id"}
        unknown = set(merged) - allowed
        if unknown:
            raise ValueError(
                f"model {model_id!r} has keys the registry does not use: {sorted(unknown)}"
            )
        models[model_id] = Model(id=model_id, role=role, **merged)

    fallback: Dict[str, List[str]] = {}
    for role, spec in roles_raw.items():
        order = list(spec.get("fallback") or [])
        missing = [m for m in order if m not in models]
        if missing:
            raise ValueError(
                f"role {role!r} falls back to models that do not exist: {missing}"
            )
        fallback[role] = order

    # A model in no role's fallback list is unreachable, which is the same as it
    # not existing. Say so rather than letting it deploy and never be called.
    for model_id, model in models.items():
        if model.role and model.role not in fallback:
            raise ValueError(
                f"model {model_id!r} has role {model.role!r} but `roles` declares "
                f"no fallback order for it, so it can never be reached"
            )

    return Registry(models=models, fallback=fallback)
