"""TTS graphs for the dedicated TTS worker.

Replaces the `XTTS_v2` + `SaveAudio` graph in `core/workflow_builder.py`. That
graph named node types that exist in no provider image — `grep -i
'xtts|saveaudio' provider_containers` returns nothing — and `config.py` had
already conceded it in a comment: `ttsEnabled` is "frontend-only for now". A TTS
job was therefore built, submitted as `task_type="image"`, routed to a worker
that could not build its graph, and failed inside the container.

Why Qwen3-TTS rather than XTTS. XTTS clones from a reference clip, which means
someone has to supply one. Qwen3-TTS has a **Voice Design** node that creates a
voice from a natural-language description, plus 9 preset timbres, a reusable
voice library, and style control — and it supports Japanese. That combination is
what makes a cast's voices obtainable with no reference audio and no expertise,
which was the actual blocker.

Three graphs:

    `build_voice_design_workflow`   describe N voices in one job
    `build_voice_speak_workflow`    speak text in an adopted voice
    `build_voice_clone_workflow`    clone from an uploaded reference

Batching is the cost lever, not a convenience. A TTS container cold start is
~44s in-container (measured — see `docs/audit-2026-09-29.md`), so N separate jobs
cost N cold starts. One job with N graphs in it costs one.
"""

from __future__ import annotations

from typing import Any

from core.exceptions import ValidationError

# Node type names from the ComfyUI-QwenTTS pack. Centralised so a pack rename is
# a one-line change here rather than a search across the codebase, and so the
# tests can assert against the same constants the graphs use.
NODE_DESIGN = "QwenTTSVoiceDesign"
NODE_SPEAK = "QwenTTSSpeak"
NODE_CLONE = "QwenTTSVoiceClone"
NODE_SAVE = "SaveAudio"

# Upper bound on one design job. A batch is a UI affordance — "design the cast" —
# and an unbounded list would be one job holding a container for an hour, which
# is the opposite of what batching is for. The TTS container's own timeout
# (`MODAL_TTS_TIMEOUT`, 1800s) is the real ceiling; this is the honest one.
MAX_VOICES_PER_DESIGN_JOB = 24


class TtsCapabilityError(ValidationError):
    """No configured provider can serve `tts`.

    Raised eagerly rather than letting the job die inside a container, so the
    user gets "no provider declares the tts capability" instead of a ComfyUI
    graph error naming a node that was never installed.
    """


def _require_tts_capable(session) -> None:
    """Fail now, and legibly, if nothing can actually serve TTS.

    With `providers.capabilities` in place this is knowable before the job is
    built rather than after a container is paid for. The error names the fix
    (declare the capability) and the reason it may be missing (the TTS app is not
    deployed), because "no provider available" is otherwise indistinguishable
    from an unhealthy pool.
    """
    from sqlmodel import select

    from core.entities import Provider

    providers = session.exec(select(Provider).where(Provider.enabled.is_(True))).all()
    if any(p.serves("tts") for p in providers):
        return
    declared = ", ".join(
        f"{p.id}({','.join(p.capabilities or [p.worker_type])})" for p in providers
    ) or "none"
    raise TtsCapabilityError(
        "No enabled provider declares the 'tts' capability, so a speech job "
        f"cannot be routed. Current providers: {declared}. Set the provider's "
        "`capabilities` to include 'tts', and confirm it is enabled."
    )


def build_voice_design_workflow(
    voices: list[dict[str, Any]],
    *,
    sample_text: str = "The tide is out, and the harbour bell has not rung since spring.",
    language: str | None = None,
    client_id: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Design N voices from natural-language descriptions, in ONE job.

    Each entry in `voices` needs a `name` (the label to store) and a `description`
    (what the voice should sound like). An optional `character_id` is carried
    into the job metadata so a completed design can be attached to its character
    without a second round trip.

    Every voice also gets `sample_text` spoken in it, which is what becomes the
    character's reference. That is deliberate: the reference a voice-cloning
    model uses should be audio this model produced, so cloning it later is
    in-distribution and needs no external audio at all. The user's problem was
    having no reference samples; this makes the first one.
    """
    if not voices:
        raise ValueError("build_voice_design_workflow requires at least one voice")
    if len(voices) > MAX_VOICES_PER_DESIGN_JOB:
        raise ValueError(
            f"{len(voices)} voices exceeds the per-job limit of "
            f"{MAX_VOICES_PER_DESIGN_JOB}. Design the cast in batches; each batch "
            "costs one container cold start, which is the thing being amortised."
        )

    prompt: dict[str, Any] = {}
    specs: list[dict[str, Any]] = []
    # Node ids start at 10 so a design graph can be embedded in a larger graph
    # later without renumbering.
    next_id = 10
    for index, voice in enumerate(voices):
        name = str(voice.get("name") or "").strip()
        description = str(voice.get("description") or "").strip()
        if not name:
            raise ValueError(f"voice #{index} has no name")
        if not description:
            raise ValueError(
                f"voice {name!r} has no description. Voice Design generates a "
                "voice from a natural-language description — that description is "
                "the whole input, so there is nothing to generate from without it."
            )
        design_id = str(next_id)
        next_id += 1
        prompt[design_id] = {
            "class_type": NODE_DESIGN,
            "inputs": {
                "description": description,
                "language": voice.get("language") or language or "en",
            },
            "_meta": {"title": f"Design voice: {name}"},
        }
        speak_id = str(next_id)
        next_id += 1
        prompt[speak_id] = {
            "class_type": NODE_SPEAK,
            "inputs": {
                "text": voice.get("sample_text") or sample_text,
                "voice": [design_id, 0],
            },
            "_meta": {"title": f"Speak sample: {name}"},
        }
        save_id = str(next_id)
        next_id += 1
        prompt[save_id] = {
            "class_type": NODE_SAVE,
            "inputs": {"audio": [speak_id, 0], "filename_prefix": f"voice/{name}"},
            "_meta": {"title": f"Save: {name}"},
        }
        specs.append(
            {
                "name": name,
                "description": description,
                "character_id": voice.get("character_id"),
                "language": voice.get("language") or language,
                "save_node": save_id,
            }
        )

    metadata: dict[str, Any] = {
        "type": "voice_design",
        "voice_count": len(specs),
        "voices": specs,
        "language": language,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return {"prompt": prompt, "client_id": client_id, "type": "tts"}, metadata


def build_voice_speak_workflow(
    text: str,
    *,
    voice_profile: str | None = None,
    language: str | None = None,
    filename_prefix: str = "tts",
    client_id: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Speak `text` in an already-designed voice."""
    if not (text or "").strip():
        raise ValueError("build_voice_speak_workflow requires non-empty text")
    prompt = {
        "10": {
            "class_type": NODE_SPEAK,
            "inputs": {
                "text": text,
                "voice": voice_profile or None,
                **({"language": language} if language else {}),
            },
            "_meta": {"title": "Speak"},
        },
        "11": {
            "class_type": NODE_SAVE,
            "inputs": {"audio": ["10", 0], "filename_prefix": filename_prefix},
            "_meta": {"title": "Save audio"},
        },
    }
    metadata: dict[str, Any] = {
        "type": "tts",
        "text": text,
        "voice_profile": voice_profile,
    }
    if language:
        metadata["language"] = language
    if extra_metadata:
        metadata.update(extra_metadata)
    return {"prompt": prompt, "client_id": client_id, "type": "tts"}, metadata


def build_voice_clone_workflow(
    text: str,
    reference_audio: str,
    *,
    reference_text: str | None = None,
    language: str | None = None,
    filename_prefix: str = "tts_clone",
    client_id: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Clone a voice from an uploaded reference and speak with it.

    The third path, for a user who already has audio they want. `reference_audio`
    is a path already present on the worker's volume — the caller uploads it
    first, rather than this function taking an upload, so a 30-second clip does
    not travel through the API twice.
    """
    if not (text or "").strip():
        raise ValueError("build_voice_clone_workflow requires non-empty text")
    if not (reference_audio or "").strip():
        raise ValueError("build_voice_clone_workflow requires a reference audio path")
    prompt = {
        "10": {
            "class_type": NODE_CLONE,
            "inputs": {
                "text": text,
                "reference_audio": reference_audio,
                **({"reference_text": reference_text} if reference_text else {}),
                **({"language": language} if language else {}),
            },
            "_meta": {"title": "Clone and speak"},
        },
        "11": {
            "class_type": NODE_SAVE,
            "inputs": {"audio": ["10", 0], "filename_prefix": filename_prefix},
            "_meta": {"title": "Save audio"},
        },
    }
    metadata: dict[str, Any] = {
        "type": "tts",
        "text": text,
        "reference_audio": reference_audio,
    }
    if language:
        metadata["language"] = language
    if extra_metadata:
        metadata.update(extra_metadata)
    return {"prompt": prompt, "client_id": client_id, "type": "tts"}, metadata
