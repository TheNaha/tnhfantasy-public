# TTS System Improvements Plan

## Context

Current TTS system uses **Qwen3-TTS via ComfyUI-QwenTTS node pack** (not XTTS/Bark). Three workflows:
- `build_voice_design_workflow` — describe voices in words → generates reference audio (key feature: no reference clip needed)
- `build_voice_speak_workflow` — speak text in an already-designed voice
- `build_voice_clone_workflow` — upload reference → clone & speak

**Provider Matrix for TTS:**
| Transport | Provider Type | Status |
|-----------|---------------|--------|
| Modal | `modal_tts` | ✅ Separate app (`comfy-modal-tts`), ~44s cold start |
| Beam | `beam_tts` | ✅ Websocket dialect on Beam realtime handler |
| Remote | `remote_tts` | ✅ Self-hosted container with `TTS_COMMAND` env |
| Direct | `direct_tts` | ✅ ComfyUI rig that already serves TTS |
| Hybrid | `remote_hybrid` | ⚠️ Claims TTS but routes via ComfyUI image engine |

## Gaps to Address

### 1. No Voice Discovery API
- `RemoteTTSEngine.list_models()` returns `[]` — voices live inside container with no enumeration
- Same for `BeamTTSEngine.list_models()`
- `ModalTTSEngine.list_models()` also returns `[]`

### 2. Hybrid TTS Path Not Implemented
- `remote_hybrid` declares `capabilities: ["image", "llm", "tts"]` but cell 5 of Colab notebook only launches ComfyUI/LLM/Laya/Agent — **no dedicated TTS process**
- `HybridRemoteEngine` delegates TTS to `image_engine` (ComfyUI), not a dedicated TTS worker

### 3. Legacy `type` Field Misleading
- `VoiceModel.type` defaults to `"xtts"` — but we use Qwen3-TTS
- Frontend `TYPE_OPTIONS` in `Voices.jsx` shows: `xtts`, `bark`, `coqui`, `embedding`, `other` — none match Qwen3-TTS

### 4. No Preset Voice Library Exposure
- Qwen3-TTS has 9 preset timbres + Voice Design + reusable voice library + style control
- No API to list/select presets

### 5. Single TTS Command in Remote Container
- `remote_tts` uses `TTS_COMMAND` env var — one synthesis command for all voices
- No per-voice model selection

---

## Implementation Plan

### Phase 1: Voice Discovery API (Backend)

#### 1.1 Add `/v1/voices` endpoint to `remote_agent/server.py`
```python
# In TTS worker mode section (WORKER_MODE == "tts")
@app.get("/v1/voices", dependencies=[Depends(verify_token)])
async def list_voices():
    """Enumerate available voices from Qwen3-TTS voice library + designed voices."""
    # Qwen3-TTS stores voices in its voice library directory
    # Also scan for designed voices in output/voice/
    # Return: [{"id": "preset_friendly", "name": "Friendly", "type": "preset", "language": "en"}, ...]
```

#### 1.2 Implement voice enumeration in Qwen3-TTS node pack
- Check `ComfyUI-QwenTTS` for voice library location (typically `models/TTS/QwenTTS/voices/`)
- Preset voices: 9 built-in timbres (need to discover naming convention)
- Designed voices: saved under `output/voice/{name}/` with metadata

#### 1.3 Update `RemoteTTSEngine.list_models()` → `list_voices()`
```python
# In worker_transport_engines.py
async def list_voices(self) -> list[dict[str, Any]]:
    """Query the container's /v1/voices endpoint."""
    client = self.get_http_client()
    resp = await client.get("/v1/voices", timeout=15.0)
    if resp.status_code == 200:
        return resp.json()
    return []
```

#### 1.4 Add same to `BeamTTSEngine` and `ModalTTSEngine`
- Beam: reuse websocket or add REST endpoint to Beam TTS app
- Modal: add `/v1/voices` to `modal_app.py` TTSWorker

---

### Phase 2: Hybrid TTS Path Implementation

#### 2.1 Decide Hybrid TTS Architecture
**Option A: Dedicated TTS Process in Hybrid Container** (Recommended)
- Run separate TTS worker (Kokoro/Qwen) on CPU or shared GPU
- Launch in cell 5 alongside ComfyUI/LLM/Laya
- Register with agent on different port (e.g., `:8004`)

**Option B: ComfyUI-QwenTTS via Image Engine** (Current, but not launched)
- Already installs `ComfyUI-QwenTTS` custom node in hybrid mode
- Need to launch ComfyUI with TTS workflow support
- But ComfyUI is already running for images — TTS jobs would queue behind images

**Decision**: Option A — dedicated lightweight TTS process avoids VRAM contention with ComfyUI.

#### 2.2 Update Colab Notebook (Cell 5)
```python
# Add TTS service launch for hybrid mode
if mode_key == "hybrid":
    t_tts = threading.Thread(target=launch_tts_track, daemon=True)
    t_tts.start()
    active_threads.append(t_tts)

def launch_tts_track():
    # Option: Run Kokoro-82M via TTS_COMMAND (lightweight, CPU-friendly)
    # Or Qwen3-TTS via separate ComfyUI instance on different port
    pass
```

#### 2.3 Update `HybridRemoteEngine` to Route TTS Properly
```python
# In hybrid_engine.py
async def inference(self, workflow, ...):
    if self._is_tts_workflow(workflow):
        # Route to dedicated TTS endpoint (agent_port + 3 = 8004)
        # Or via agent's /synthesize if agent runs TTS
        pass
```

#### 2.4 Add TTS Port to Provider Config
- Hybrid provider config: add `tts_port: 8004`
- Update `remote_hybrid` spec in `registry.py`

---

### Phase 3: VoiceModel Schema & Type System

#### 3.1 Update `VoiceModel` Entity
```python
# core/entities.py
class VoiceModel(SQLModel, table=True):
    ...
    type: str = Field(default="qwen3_tts")  # Was "xtts"
    # Add engine-specific fields:
    voice_preset: str | None = Field(default=None)  # e.g. "friendly", "professional"
    voice_style: str | None = Field(default=None)   # style control parameters
    source: str = Field(default="design")  # "design" | "preset" | "clone" | "manual"
```

#### 3.2 Migration
- Add `voice_preset`, `voice_style`, `source` columns
- Update existing rows: `type` → `"qwen3_tts"`

#### 3.3 Update Frontend `TYPE_OPTIONS`
```jsx
// Voices.jsx
const TYPE_OPTIONS = [
    { value: 'qwen3_tts', label: 'Qwen3-TTS (Design)' },
    { value: 'qwen3_preset', label: 'Qwen3-TTS (Preset)' },
    { value: 'clone', label: 'Voice Clone' },
    { value: 'other', label: 'Other' },
];
```

#### 3.4 Add Preset Voice Selection to Voice Create/Edit Form
- Fetch presets via new `useVoicePresets` hook → `GET /api/v2/voices/presets`
- Dropdown for preset selection when type = `qwen3_preset`

---

### Phase 4: Preset Voice Library API

#### 4.1 Backend: `/api/v2/voices/presets` endpoint
```python
# api/routes/world_vault/voices.py
@router.get("/presets")
async def list_voice_presets(session: Session = Depends(get_session)):
    """Return Qwen3-TTS built-in preset timbres."""
    # Static list from Qwen3-TTS documentation, or query from a provider
    return [
        {"id": "friendly", "name": "Friendly", "description": "Warm, approachable", "language": "en"},
        {"id": "professional", "name": "Professional", "description": "Clear, authoritative", "language": "en"},
        # ... 9 presets
    ]
```

#### 4.2 Frontend: `useVoicePresets` hook + UI integration
- Add preset selector in Voice Design modal
- When preset selected, auto-fill description or use preset directly

---

### Phase 5: Remote TTS Container Enhancement

#### 5.1 Replace Single `TTS_COMMAND` with Model-Aware Dispatch
- Current: One `TTS_COMMAND` for all voices
- New: Per-voice command selection based on `voice_profile` / `voice_preset`
- Support multiple TTS engines in one container (Kokoro for speed, Qwen for quality)

#### 5.2 Add `/v1/voices` to Remote Agent
- Enumerate available TTS models/voices from container's engines
- Return unified list across engines

---

### Phase 6: UI Polish & Integration

#### 6.1 Voices Page Enhancements
- Add "Preset" tab alongside "Design" and "Create"
- Show preset preview buttons (queue preview job with preset)
- Filter/sort by type, language, world

#### 6.2 Character Voice Assignment
- Characters.jsx already has voice_model dropdown
- Ensure it shows `voice_preset` / `source` info
- Auto-set `voice_profile` from selected voice

#### 6.3 Chat TTS Integration
- `ChatWorkspaceContext.jsx` has `handleGenerateTTS` using `voiceId`
- Should work with new voice types once backend supports them

---

## Data Flow Summary

```
User creates voice (Design/Preset/Clone)
    → POST /api/v2/voices/design or /api/v2/voices
    → Queues TTS job (task_type="tts")
    → Load balancer routes to provider with capabilities=["tts"]
    → Provider engine (Modal/Beam/Remote/Direct) runs workflow
    → Output audio saved to storage
    → VoiceModel record updated with preview_path
    → Frontend invalidates voices query → shows new voice with audio player
```

---

## Affected Files

### Backend
- `remote_agent/server.py` — add `/v1/voices` endpoint (TTS mode)
- `backend_v2/services/engines/worker_transport_engines.py` — `list_voices()` on Remote/Beam/Modal TTS engines
- `backend_v2/services/engines/hybrid_engine.py` — route TTS workloads
- `backend_v2/services/engines/registry.py` — update `remote_hybrid` spec with TTS port
- `backend_v2/core/entities.py` — `VoiceModel` schema changes
- `backend_v2/api/routes/world_vault/voices.py` — add `/presets` endpoint
- `backend_v2/services/tts_workflow_builder.py` — support preset voices

### Frontend
- `frontend_v2/src/pages/Voices.jsx` — update TYPE_OPTIONS, add preset tab
- `frontend_v2/src/hooks/useVoices.js` — add `useVoicePresets` hook
- `frontend_v2/src/pages/Characters.jsx` — display voice preset info

### Infrastructure
- `scripts/update_colab_notebooks.py` — add TTS service launch in hybrid mode
- `remote_agent/TNHFantasy_Colab_Worker.ipynb` — regenerated from script
- `deployables/modal/tts/modal_app.py` — add `/v1/voices` to TTSWorker

---

## Validation Steps

1. **Voice Discovery**: `GET /api/v2/voices/presets` returns 9 Qwen presets; `RemoteTTSEngine.list_voices()` returns them
2. **Hybrid TTS**: Colab hybrid notebook launches TTS service; `remote_hybrid` provider routes TTS jobs correctly
3. **Voice Creation**: Design → job completes → voice appears in list with playable preview
4. **Preset Selection**: User picks preset → voice created with `source="preset"` and `voice_preset` set
5. **Character Assignment**: Character form shows preset voices correctly
6. **Chat TTS**: Narration works with designed/preset/cloned voices

---

## Open Questions

1. **Qwen3-TTS Preset Names**: What are the exact 9 preset timbre identifiers? Need to inspect `ComfyUI-QwenTTS` node pack.
2. **Hybrid TTS Engine**: Kokoro (fast, CPU) vs Qwen (quality, GPU)? Kokoro better for Colab free tier.
3. **Voice Library Persistence**: Where does Qwen3-TTS save designed voices? Need to ensure they survive container restarts.
4. **Modal TTS Voice Discovery**: Does `modal_tts` app have access to same voice library? Or separate?
5. **Backward Compat**: Existing `type="xtts"` voices — migrate or support both?

---

## Rollout Order

1. Phase 1 (Voice Discovery API) — unblocks everything else
2. Phase 3 (Schema/Type) — data model fix
3. Phase 4 (Presets) — UX improvement
4. Phase 2 (Hybrid TTS) — infrastructure
5. Phase 5 (Remote Container) — parity
6. Phase 6 (UI Polish) — final integration