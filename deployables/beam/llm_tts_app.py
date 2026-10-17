"""Beam.cloud worker for the LLM and TTS cells.

Two more deployments alongside the four in `beam_app.py`:

  - comfy_llm:   ASGI, GPU. `WS /llm` — OpenAI-style chat over llama.cpp
  - comfy_tts:   ASGI, CPU. `WS /tts` — text to audio

`beam_app.py` has four deployments and neither of these was one of them, which
is not a gap in coverage so much as a gap in the product: `BeamLLMEngine` and
`BeamTTSEngine` have existed in the registry (`registry.py`, cells
`CATEGORY_LLM`/`beam_llm` and `CATEGORY_TTS`/`beam_tts`) and have been offered
to operators in the Providers modal the whole time, and neither had anything
serving the path they dial.

THE SHAPE OF THE MISTAKE. `@realtime` serves exactly one handler at the
deployment root — it takes no path, and a handler signature with a second
parameter fails to bind rather than failing safe, which `beam_app.py`'s own
`comfy_gpu` docstring records. So "add /llm to the existing realtime handler"
was never available. An `@asgi` deployment mounting a FastAPI app is, because
FastAPI routes websockets by path like anything else.

THE DIALECT. These two speak the CANONICAL TaskEvent dialect, not the legacy
`{"status": ...}` one the image handler uses:

    {"event": "delta",     "text": "..."}
    {"event": "completed", "outputs": [{"role": "assistant", "content": "..."}]}
    {"event": "failed",    "message": "...", "retryable": false}

`BaseInProcessEngine`'s contract, which is what `provider_client._LLMReducer`
consumes. The engine's receive loop terminates only on `event in
{completed, failed, cancelled}` (`worker_transport_engines.py`) — a frame
without an `event` key never ends the stream, so a handler that answered in
`{"status": ...}` would hold a GPU slot for the full 1800 s and then report a
retryable failure. That is the failure mode this file exists to prevent, so the
dialect is asserted rather than assumed: see `tests/test_deployable_contract.py`.

AUTH. Both deployments bill GPU and CPU time respectively and both read the
token from the payload, for the same reason `comfy_gpu` does — a `@realtime` or
websocket handler has no reliable request context to read a header from, and
the client sends the key in both places. Comparison is constant-time.
"""
from beta9 import asgi, Image, Volume
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import httpx
import json
import os

import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

# The same positional problem `beam_app.py` solves, for the same reason:
# `llama_server.py` lives under `remote_agent/` and is not a sibling of this
# file. Deploy from the REPOSITORY ROOT so the synced working directory carries
# it. See the sys.path note in beam_app.py's module docstring.
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = next(
    (
        parent
        for parent in _HERE.parents
        if (parent / "remote_agent" / "llama_server.py").is_file()
    ),
    None,
)
for _candidate in (_REPO_ROOT, _HERE):
    if _candidate:
        if str(_candidate) not in sys.path:
            sys.path.append(str(_candidate))
        if (_candidate / "remote_agent").is_dir() and str(_candidate / "remote_agent") not in sys.path:
            sys.path.append(str(_candidate / "remote_agent"))

VOL_NAME = os.getenv("BEAM_VOLUME_NAME", "comfy-storage")
LLM_DIR = os.getenv("BEAM_LLM_DIR", "llm")
TTS_DIR = os.getenv("BEAM_TTS_DIR", "tts")

GPU_TYPE = os.getenv("BEAM_GPU_TYPE", "RTX4090")
GPU_CPU = int(os.getenv("BEAM_GPU_CPU", "2"))
GPU_MEMORY = os.getenv("BEAM_GPU_MEMORY", "16Gi")
GPU_TIMEOUT = int(os.getenv("BEAM_LLM_TIMEOUT", "1800"))
GPU_KEEP_WARM = int(os.getenv("BEAM_LLM_KEEP_WARM", "40"))
#: Matches `BeamLLMEngine`'s 1800 s budget (`clamp_timeout(..., 1800.0)`), so a
#: generation that outlives the backend's patience is not also billed as a
#: severed socket. The two defaults were chosen independently and disagreed by
#: 3x, which turned every long reply into a provider failure.
LLM_CONCURRENT = int(os.getenv("BEAM_LLM_CONCURRENT", "1"))

TTS_TIMEOUT = int(os.getenv("BEAM_TTS_TIMEOUT", "600"))
TTS_KEEP_WARM = int(os.getenv("BEAM_TTS_KEEP_WARM", "20"))
TTS_CONCURRENT = int(os.getenv("BEAM_TTS_CONCURRENT", "4"))

#: Shared with the image workers so one provider row's model tree is one tree.
MODELS_ROOT = f"/mnt/data/{LLM_DIR}"

llm_image = (
    Image(python_version="python3.12")
    .add_commands([
        "apt-get update && apt-get install -y git cmake build-essential libcurl4-openssl-dev",
        # llama.cpp's own build. `LlamaStack._llama_binary` probes a list of
        # paths, so the location below is a fallback, not the only one that
        # works — but it is where this image puts it.
        "git clone --depth 1 https://github.com/ggml-org/llama.cpp /opt/llama.cpp",
        "cmake -S /opt/llama.cpp -B /opt/llama.cpp/build -DGGML_CUDA=on -DCMAKE_BUILD_TYPE=Release",
        "cmake --build /opt/llama.cpp/build --config Release -j --target llama-server",
        "ln -sf /opt/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server",
    ])
    .add_python_packages([
        "fastapi",
        "uvicorn",
        "websockets",
        "httpx",
        "huggingface_hub",
        "laya>=0.4.10",
    ])
    .build_with_gpu(gpu=GPU_TYPE)
)

#: TTS ships no model. The operator points `TTS_COMMAND` at any `text -> wav`
#: shell command, which is the same hook `remote_agent` exposes and for the same
#: reason: the voice catalogue is the operator's choice, and baking a Kokoro
#: checkpoint into every deployable to save them one env var is a bad trade.
tts_image = (
    Image(python_version="python3.12")
    .add_python_packages([
        "fastapi",
        "uvicorn",
        "websockets",
    ])
)


# =============================================================================
# Auth
# =============================================================================


def _token_ok(provided: Any) -> bool:
    """Constant-time payload-token check.

    The token is absent or the deployment is wide open, which is a configuration
    error worth failing loudly on rather than serving free inference from.
    """
    import hmac

    expected = os.getenv("BEAM_API_KEY", "").strip()
    if not expected:
        return False
    if not isinstance(provided, str):
        return False
    return hmac.compare_digest(provided, expected)


def _reject(websocket: WebSocket, message: str, retryable: bool = False) -> None:
    websocket.send_text(json.dumps({
        "event": "failed",
        "message": message,
        "retryable": retryable,
    }))


async def _read_payload(websocket: WebSocket) -> Dict[str, Any] | None:
    """The first frame, parsed. `None` if the peer closed or sent nonsense."""
    raw = await websocket.receive_text()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


# =============================================================================
# LLM
# =============================================================================

llm_app = FastAPI()
_llm_state: Dict[str, Any] = {"stack": None, "ready": False}


@llm_app.get("/health")
async def llm_health():
    """Unauthenticated on purpose — it reports no configuration, and the
    reconciler polls it to decide whether a cold worker is still starting."""
    stack = _llm_state.get("stack")
    servers = getattr(stack, "servers", {}) or {}
    return {
        "status": "healthy",
        "ready": bool(_llm_state.get("ready")),
        "models": sorted(servers),
        "unavailable": getattr(stack, "unavailable", {}) or {},
    }


@llm_app.websocket("/llm")
async def llm_socket(websocket: WebSocket):
    """One OpenAI-style chat completion, streamed as canonical TaskEvents.

    The payload is `_BeamLLMEngineBase._payload`: `{"token", "messages", plus
    the sampler fields and "model"}`. Not `{"workflow": ...}` — that is the image
    dialect, and a handler shared between the two would answer every LLM request
    with "No workflow provided".
    """
    await websocket.accept()

    payload = await _read_payload(websocket)
    if payload is None:
        await _reject(websocket, "LLM request was not a JSON object")
        return
    if not _token_ok(payload.get("token")):
        await _reject(websocket, "Beam LLM rejected the provided credentials")
        return

    stack = _llm_state.get("stack")
    if stack is None or not _llm_state.get("ready"):
        # Retryable: a cold worker that has not finished loading is exactly what
        # this state means, and the backend re-dispatches.
        await _reject(websocket, "llama.cpp is still loading in this container", retryable=True)
        return

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        await _reject(websocket, "LLM request carried no messages")
        return

    try:
        port = stack.resolve(payload.get("model") or "")
    except RuntimeError as exc:
        # A model this worker does not hold is a configuration state. Retrying
        # it across the provider pool cannot succeed.
        await _reject(websocket, str(exc))
        return

    body: Dict[str, Any] = {"model": payload.get("model"), "messages": messages, "stream": True}
    for backend_key, upstream_key in _SAMPLER_KEYS.items():
        if payload.get(backend_key) is not None:
            body[upstream_key] = payload[backend_key]

    content = ""
    tool_calls: list = []
    try:
        async for frame in _llama_sse(port, body):
            for choice in frame.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    content += delta["content"]
                    await websocket.send_text(json.dumps({
                        "event": "delta", "text": delta["content"],
                    }))
                for call in delta.get("tool_calls") or []:
                    index = call.get("index", 0)
                    while len(tool_calls) <= index:
                        tool_calls.append({
                            "id": "", "type": "function",
                            "function": {"name": "", "arguments": ""},
                        })
                    if call.get("id"):
                        tool_calls[index]["id"] = call["id"]
                    function = call.get("function") or {}
                    if function.get("name"):
                        tool_calls[index]["function"]["name"] = function["name"]
                    if function.get("arguments"):
                        tool_calls[index]["function"]["arguments"] += function["arguments"]
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001 - every failure reaches the client as a frame
        await _reject(websocket, f"llama.cpp generation failed: {exc}", retryable=True)
        return

    output: Dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        output["tool_calls"] = tool_calls
    await websocket.send_text(json.dumps({"event": "completed", "outputs": [output]}))


#: Backend sampler key -> OpenAI-compatible name. `max_output_tokens` is a
#: backend name; forwarded verbatim llama.cpp ignores it and the reply truncates
#: at its own default with nothing in the log to say why.
_SAMPLER_KEYS = {
    "temperature": "temperature",
    "top_p": "top_p",
    "max_output_tokens": "max_tokens",
    "frequency_penalty": "frequency_penalty",
    "presence_penalty": "presence_penalty",
}


async def _llama_sse(port: int, body: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """SSE frames from the loopback llama-server on `port`."""
    import httpx

    timeout = httpx.Timeout(float(GPU_TIMEOUT), read=float(GPU_TIMEOUT))
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST", f"http://127.0.0.1:{port}/v1/chat/completions", json=body,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    return
                try:
                    frame = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if isinstance(frame, dict):
                    yield frame


# ---------------------------------------------------------------------------
# Models & Auth for HTTP routes
# ---------------------------------------------------------------------------


async def verify_beam_token(request: Request):
    """Authenticate HTTP request via Authorization: Bearer <key> or X-Worker-Token."""
    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif request.headers.get("X-Worker-Token"):
        token = request.headers.get("X-Worker-Token", "").strip()
    elif "token" in request.query_params:
        token = request.query_params["token"].strip()

    if not _token_ok(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


class DownloadRequest(BaseModel):
    url: str = ""
    path: str = ""
    token: Optional[str] = None
    preview_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    model_id: Optional[str] = None


class ListModelsRequest(BaseModel):
    directory: str = ""


class DeleteModelRequest(BaseModel):
    path: str


class ValidateModelsRequest(BaseModel):
    directory: str | List[str]
    delete_invalid: bool = False


class DecisionsRequest(BaseModel):
    model: str = "laya_multilingual"
    context: str = ""
    state: str = ""
    questions: Any = Field(default_factory=list)


_LAYA_REPO_MAP = {
    "laya_multilingual": "convaiinnovations/laya-multilingual",
    "laya_typed_decisions": "convaiinnovations/laya-typed-decisions",
    "laya_english": "convaiinnovations/laya",
}
_LAYA_LOADED_MODELS: Dict[str, Any] = {}


def _evaluate_laya_cpu_sync(model_id: str, context_text: str, questions: Any) -> Dict[str, Any]:
    import time
    import laya  # type: ignore

    repo_or_path = _LAYA_REPO_MAP.get(model_id, model_id)
    candidate = os.path.join(MODELS_ROOT, model_id)
    if os.path.isdir(candidate) and os.listdir(candidate):
        repo_or_path = candidate

    laya_model = _LAYA_LOADED_MODELS.get(repo_or_path)
    if laya_model is None:
        laya_model = laya.load(repo_or_path, device="cpu")
        _LAYA_LOADED_MODELS[repo_or_path] = laya_model

    if isinstance(questions, dict):
        q_list = [{"key": k, **v} for k, v in questions.items() if isinstance(v, dict)]
    elif isinstance(questions, list):
        q_list = [q for q in questions if isinstance(q, dict) and "key" in q]
    else:
        q_list = []

    questions_dict: Dict[str, Any] = {}
    min_rubric_val: Dict[str, int] = {}
    for q in q_list:
        key = q["key"]
        q_type = q.get("type")
        if q_type == "choice":
            opts = q.get("options")
            criteria = opts if isinstance(opts, (list, dict)) else []
            questions_dict[key] = {
                "type": "choice",
                "instructions": q.get("question") or q.get("prompt") or "",
                "criteria": criteria,
            }
        elif q_type == "score":
            rubric_raw = q.get("rubric") or {}
            if isinstance(rubric_raw, dict):
                sorted_keys = sorted(rubric_raw.keys(), key=lambda x: int(x))
                min_rubric_val[key] = int(sorted_keys[0]) if sorted_keys else 1
                criteria = [rubric_raw[k] for k in sorted_keys]
            else:
                min_rubric_val[key] = 1
                criteria = [str(x) for x in (q.get("options") or [])]
            questions_dict[key] = {
                "type": "score",
                "instructions": q.get("question") or q.get("prompt") or "",
                "criteria": criteria or ["1", "2", "3", "4", "5"],
            }
        elif q_type in ("noul", "yes_no"):
            questions_dict[key] = {
                "type": "noul",
                "instructions": q.get("statement") or q.get("prompt") or q.get("question") or "",
            }

    t0 = time.perf_counter()
    raw_result = laya_model.predict(context_text, questions_dict)
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    raw_answers = raw_result.get("answers", {}) if isinstance(raw_result, dict) else {}
    answers: Dict[str, Any] = {}
    for q in q_list:
        key = q["key"]
        q_type = q.get("type")
        ans = raw_answers.get(key)
        if ans is None:
            continue
        if q_type == "choice":
            choice_val = ans.get("choice") or ans.get("selected")
            probs_val = ans.get("probabilities") or ans.get("probs") or {}
            answers[key] = {
                "choice": str(choice_val) if choice_val is not None else "",
                "probabilities": dict(probs_val or {}),
            }
        elif q_type == "score":
            score_raw = ans.get("score")
            if score_raw is None:
                score_raw = ans.get("expected", 0.0)
            score_num = float(score_raw)
            offset = min_rubric_val.get(key, 0)
            if offset > 0:
                score_num += float(offset)
            answers[key] = {"score": round(score_num, 2)}
        elif q_type in ("noul", "yes_no"):
            prob_val = ans.get("noul") if "noul" in ans else ans.get("probability", 0.0)
            answers[key] = {"probability": float(prob_val) if prob_val is not None else 0.0}

    return {
        "status": "success",
        "model_id": model_id,
        "engine_used": "beam_laya_cpu",
        "provider_tier": "beam_laya",
        "latency_ms": latency_ms,
        "answers": answers,
        "results": answers,
    }


@llm_app.post("/v1/chat/completions", dependencies=[Depends(verify_beam_token)])
async def chat_completions(request: Request):
    stack = _llm_state.get("stack")
    if stack is None or not _llm_state.get("ready"):
        raise HTTPException(status_code=503, detail="llama.cpp is still loading")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    try:
        port = stack.resolve(body.get("model") or "")
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    stream = body.get("stream", False)
    if stream:
        async def _stream_generator():
            async for frame in _llama_sse(port, body):
                yield f"data: {json.dumps(frame)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_stream_generator(), media_type="text/event-stream")
    else:
        async with httpx.AsyncClient(timeout=float(GPU_TIMEOUT)) as client:
            resp = await client.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=body)
            return JSONResponse(status_code=resp.status_code, content=resp.json())


@llm_app.get("/v1/models", dependencies=[Depends(verify_beam_token)])
async def list_models_v1():
    stack = _llm_state.get("stack")
    servers = getattr(stack, "servers", {}) or {}
    data = [
        {"id": m, "object": "model", "owned_by": "beam", "permission": []}
        for m in sorted(servers)
    ]
    return {"object": "list", "data": data}


@llm_app.post("/v1/decisions", dependencies=[Depends(verify_beam_token)])
async def evaluate_decisions(req: DecisionsRequest):
    """Evaluate parallel typed System 1 questions using Laya on CPU (0 MB GPU VRAM)."""
    import asyncio
    try:
        res = await asyncio.to_thread(
            _evaluate_laya_cpu_sync,
            req.model,
            req.context or req.state,
            req.questions,
        )
        return res
    except ImportError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": f"laya package not installed on Beam worker: {exc}",
                "retryable": False,
            },
        )
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "message": f"Laya CPU evaluation failed: {exc}",
                "retryable": False,
            },
        )


@llm_app.post("/download-model", dependencies=[Depends(verify_beam_token)])
async def download_model(req: DownloadRequest):
    if req.model_id:
        from remote_agent.llama_server import load as load_registry
        reg = load_registry()
        try:
            model = reg.get(req.model_id)
        except Exception:
            return {"ok": False, "model_id": req.model_id, "reason": "not_in_registry"}
        from huggingface_hub import snapshot_download
        target = f"{MODELS_ROOT}/{model.volume_dir}"
        os.makedirs(target, exist_ok=True)
        if getattr(model, "engine_type", "gguf") == "system1_laya":
            snapshot_download(model.repo, local_dir=target)
        else:
            patterns = [model.gguf]
            if model.mmproj:
                patterns.append(model.mmproj)
            snapshot_download(model.repo, allow_patterns=patterns, local_dir=target)
        return {"ok": True, "model_id": req.model_id, "fetched": [target]}

    # Direct URL download
    from provider_core.downloads import download_model_to_path
    from provider_core.utils import get_safe_path
    full_path = get_safe_path(MODELS_ROOT, req.path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    res = download_model_to_path(
        url=req.url,
        full_path=full_path,
        path=req.path,
        token=req.token,
        preview_url=req.preview_url,
        metadata=req.metadata,
    )
    return res


@llm_app.post("/list-models", dependencies=[Depends(verify_beam_token)])
async def list_models(req: ListModelsRequest):
    from provider_core.utils import is_model_candidate
    from pathlib import Path
    target_dir = Path(MODELS_ROOT) / (req.directory.lstrip("/")) if req.directory else Path(MODELS_ROOT)
    if not target_dir.is_dir():
        return []
    items = []
    for root, _, files in os.walk(target_dir):
        for f in files:
            if is_model_candidate(f):
                p = Path(root) / f
                items.append({
                    "name": f,
                    "path": str(p.relative_to(MODELS_ROOT)),
                    "size": p.stat().st_size,
                    "type": "model",
                })
    return items


@llm_app.post("/validate-models", dependencies=[Depends(verify_beam_token)])
async def validate_models(req: ValidateModelsRequest):
    dirs = [req.directory] if isinstance(req.directory, str) else req.directory
    results = {}
    for d in dirs:
        results[d] = {"valid": [], "invalid": [], "corrupted": []}
    return results


@llm_app.post("/delete-model", dependencies=[Depends(verify_beam_token)])
async def delete_model(req: DeleteModelRequest):
    from provider_core.utils import get_safe_path
    try:
        full_path = get_safe_path(MODELS_ROOT, req.path)
        if os.path.exists(full_path):
            os.remove(full_path)
            return {"status": "success", "deleted": True}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
    return {"status": "success", "deleted": False}


# =============================================================================
# TTS
# =============================================================================

tts_app = FastAPI()


@tts_app.get("/health")
async def tts_health():
    return {
        "status": "healthy",
        "tts_command": bool(os.getenv("TTS_COMMAND", "").strip()),
    }


@tts_app.websocket("/tts")
async def tts_socket(websocket: WebSocket):
    """One synthesis, reported as canonical TaskEvents.

    The payload is `_tts_request_from_workflow`: `{"token", "text", "voice",
    "language"}`. Both `beam_tts` and `remote_tts` read the same three fields
    out of the graph, and `d9ce436c` is the reason that extractor exists — two
    of the four transports were reading a top-level `text` that the shared
    graph builder does not put there, so every real narration arrived empty.
    """
    await websocket.accept()

    payload = await _read_payload(websocket)
    if payload is None:
        await _reject(websocket, "TTS request was not a JSON object")
        return
    if not _token_ok(payload.get("token")):
        await _reject(websocket, "Beam TTS rejected the provided credentials")
        return

    text = (payload.get("text") or "").strip()
    if not text:
        await _reject(websocket, "TTS request carried no text")
        return

    command = os.getenv("TTS_COMMAND", "").strip()
    if not command:
        # Permanent: no amount of retrying produces a configured command.
        await _reject(
            websocket,
            "Beam TTS has no TTS_COMMAND configured; point it at any "
            "`text -> wav` command and redeploy",
        )
        return

    voice = payload.get("voice") or os.getenv("TTS_DEFAULT_VOICE", "")
    language = payload.get("language") or os.getenv("TTS_DEFAULT_LANGUAGE", "")

    try:
        clip = await _synthesise(command, text, voice, language)
    except Exception as exc:  # noqa: BLE001
        await _reject(websocket, f"TTS synthesis failed: {exc}", retryable=True)
        return

    await websocket.send_text(json.dumps({"event": "completed", "outputs": [clip]}))


async def _synthesise(command: str, text: str, voice: str, language: str) -> Dict[str, Any]:
    """Run the operator's command and describe what it wrote.

    Environment-variable substitution rather than argv templating: a synthesis
    command is more often a shell pipeline than a single binary, and quoting a
    user's text into an argv is how a quote in the narration becomes a shell
    injection.
    """
    import asyncio
    import uuid

    import aiofiles

    out_dir = f"/mnt/data/{TTS_DIR}"
    os.makedirs(out_dir, exist_ok=True)
    filename = f"tts_{uuid.uuid4().hex}.wav"
    out_path = f"{out_dir}/{filename}"

    env = dict(os.environ)
    env["TTS_TEXT"] = text
    env["TTS_VOICE"] = voice or ""
    env["TTS_LANGUAGE"] = language or ""
    env["TTS_OUTPUT"] = out_path

    timeout = float(os.getenv("TTS_COMMAND_TIMEOUT", str(TTS_TIMEOUT)))
    process = await asyncio.create_subprocess_shell(
        command, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError(f"TTS command exceeded {int(timeout)}s")

    if process.returncode != 0:
        raise RuntimeError(
            f"TTS command exited {process.returncode}: "
            f"{stderr.decode('utf-8', 'replace')[-400:]}"
        )

    try:
        async with aiofiles.open(out_path, "rb") as handle:
            payload = await handle.read()
    except OSError as exc:
        # The command reported success and wrote nothing. Reporting success here
        # is how a job finalises green with no clip on it.
        raise RuntimeError(f"TTS command wrote no audio to {out_path}: {exc}")

    return {
        "path": f"{TTS_DIR}/{filename}",
        "filename": filename,
        "voice": voice,
        "language": language,
        "bytes": len(payload),
    }


# =============================================================================
# Deployment entry points
# =============================================================================


def _start_llm():
    """Load the registry and bring up one llama-server per distinct primary.

    Blocking by design, same as `LlamaStack.launch`: the first websocket would
    otherwise arrive at a server that is not up yet and be answered with a
    spurious retryable failure.
    """
    from remote_agent.llama_server import LlamaStack, load as load_registry

    registry = load_registry()
    if registry is None:
        _llm_state["ready"] = False
        return
    stack = LlamaStack(MODELS_ROOT)
    stack.launch(registry)
    _llm_state["stack"] = stack
    _llm_state["ready"] = True


@asgi(
    name="comfy-llm",
    cpu=GPU_CPU,
    memory=GPU_MEMORY,
    gpu=GPU_TYPE,
    image=llm_image,
    volumes=[Volume(VOL_NAME, mount_path="/mnt/data")],
    timeout=GPU_TIMEOUT,
    keep_warm_seconds=GPU_KEEP_WARM,
    concurrent_requests=LLM_CONCURRENT,
    on_start=_start_llm,
)
def comfy_llm():
    return llm_app


@asgi(
    name="comfy-tts",
    cpu=1,
    memory="2Gi",
    image=tts_image,
    volumes=[Volume(VOL_NAME, mount_path="/mnt/data")],
    timeout=TTS_TIMEOUT,
    keep_warm_seconds=TTS_KEEP_WARM,
    concurrent_requests=TTS_CONCURRENT,
)
def comfy_tts():
    return tts_app