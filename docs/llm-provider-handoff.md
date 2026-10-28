# TNHComfy: LLM Hosting Handoff Summary

Context for any agent picking up this work. Written 2026-10-10 from a planning conversation with the project owner (TheNaha).

## 1. Project in one paragraph

TNHComfy is a self-hosted, personal-use-only "Fantasy Engine" web app. It began as a containerized ComfyUI wrapper and now has three pillars sharing one data layer (the "World Vault": Characters, Chats, Lorebooks, Stories, Locations, Personas, Scenarios, Tags, Memories in PostgreSQL + pgvector):

1. **Image generation**: ComfyUI workflows dispatched to serverless workers (Modal, Beam) or long-running provider containers; Postgres job queue, WebSocket progress, Civitai model discovery.
2. **LLM roleplay**: SillyTavern-style chats and group chats, ST JSONL import/export, autonomous agentic tools (scene narration, image generation, memory recall), autobiographical memory (auto-extraction + `rag_pipeline` over pgvector), idle simulation (characters reply while the user is away), per-entity sampler overrides, `llm_config` routes.
3. **Story Sandbox**: AI Dungeon-style editor with branches, sessions, tags, world graph/timeline.

Stack: FastAPI backend (request-scoped Session, `MigrationStep` runner, no Alembic), React frontend (Zustand + React Query, **bun only**, Vite dev port 5174 proxying to backend on 8002), docker compose (pgvector pg16, Traefik, `scripts/preflight.sh`). **There are no automatic backups.** The P1-P6 roadmap is complete; remaining ideas are a Visual Novel/Comic exporter and deeper idle simulation.

## 2. The question being solved

Pick open-weight LLMs and a Modal deployment for the roleplay pillar that satisfy:

- **Uncensored**, because the app is for the owner's personal use and includes NSFW roleplay.
- **Vision**: the chat must be able to read images.
- **Hosted on Modal serverless functions.**
- **Fast cold start**, because the owner chats only occasionally.
- **Good quality** (long-context consistency with lorebooks and world context, plus instruction following).
- **GPU ceiling: L40S (48GB) or A100 40GB.** The owner said anything larger is discouraged.
- Multiple models are fine if they boot quickly or switch quickly.

## 3. Recommendations made (agreed direction, not yet validated by running)

**Models**
- `rp`: a Mistral Small 3.2 24B roleplay finetune (candidates named from community roundups: Magnum-Diamond-24B, Cydonia-24B line) at Q5_K_M, about 17GB. Handles in-character prose. Exact GGUF repo/filename is still **TODO**.
- `util`: stock Mistral Small 3.2 24B Instruct (2506) at Q4_K_M plus `mmproj`, about 15GB. Handles image captioning, tool calls, memory extraction, summaries.
- Rationale: RP finetunes usually lose vision and get worse at structured output and tool calls. So images go to `util`, which returns a text description for the `rp` context, and agentic and extraction work stays off the finetune.
- Smaller fallback: 12B Mistral Nemo finetunes (faster, weaker on long context). 70B-class models do not fit the GPU limit. Possible later swap for `util`: Qwen3-30B-A3B (MoE, about 3B active, fast, but no vision).

**Serving approach (for fast cold start)**
- llama.cpp `llama-server` with GGUF, not vLLM. It mmaps the file and starts much faster, while vLLM spends time on compilation and CUDA graph capture. Concurrency is lower, which is fine for a single user.
- Prebuilt image `ghcr.io/ggml-org/llama.cpp:server-cuda`, so no compile step.
- Weights live in a Modal Volume, downloaded once. Nothing is pulled from Hugging Face at runtime.
- One Modal function per model (`serve_rp`, `serve_util`), each scaling to zero on its own idle timer (300s and 180s). "Switching models" means calling a different URL.
- OpenAI-compatible endpoints; `model="rp"` or `"util"` via `--alias`. Auth via `LLAMA_API_KEY` from Modal Secret `tnh-llm-key`.
- Suggested trick: the frontend pings `GET /health` when the user opens `/chat`, so the cold boot overlaps with typing.
- Expected cold start is a rough guess of 20-60s. It has **not been measured**.
- The llama.cpp prompt-prefix cache is lost on each cold start, so the first message after idle is slower.
- Optional: both models could share one L40S in one container (about 17GB + 15GB + KV cache fits in 48GB). That trades independent scaling for a single cold start and bill.

**Backend architecture suggestion**: a two-model router with a provider-agnostic OpenAI-compatible client interface, and selective lorebook injection (keyword and recency triggers) to avoid sending the whole world graph each turn.

## 4. Deliverables so far

- ~~`modal_llm.py`~~ **superseded.** The draft referenced here is archived at `docs/archive/modal_llm_app_draft.py`. The shipped app is `deployables/modal/llm/app.py`: same `llama-server`, but the `MODELS` literal became `models.json` (shared with the backend's `llm_router` and with `remote_agent/llama_server.py`), and the per-model `serve_rp`/`serve_util` **web servers** became one SDK-only `ChatLLM` class parametrized by model id — no public URLs, because `modal.web_server` publishes them. Deploy it with `bash scripts/deploy.sh llm`.
- Documentation advice given: split the summary file into `README.md` (what/quick start), `ARCHITECTURE.md` (chat-turn data flow: context builder → pgvector retrieval → LLM call → tool calls → job queue → Modal), and `CONFIG.md` (env vars). Fold backend/frontend conventions into an agent instruction file. The doc should state where the LLM runs, which protocol the backend uses, what `llm_config` points at, and the embedding model and dimension (changing it forces re-embedding all memories). Drop the commit hash and date from the roadmap line.

## 5. Unverified items (check before relying on them)

- Hugging Face repo ids and GGUF filenames in `MODELS`. The `rp` entry is a placeholder; the `util` entry (unsloth repo, Q4_K_M file, `mmproj-F16.gguf`) is from memory.
- The llama.cpp image tag, the `/app/llama-server` path, and flag compatibility (`--jinja`, `--mmproj`, `--alias`, `--parallel`, `LLAMA_API_KEY`).
- Current Modal API names (`scaledown_window`, `@modal.concurrent`, `@modal.web_server`) against the Modal docs.
- Whether Mistral Small 3.2's tool calling works well through llama.cpp's `--jinja` template.
- Model rankings came from community roundups, some of low quality (SEO listicles, reseller content). Cross-check r/SillyTavernAI and the UGI Leaderboard on Hugging Face.
- Real cold-start time, VRAM headroom at the chosen context sizes, and Modal per-second GPU pricing.

## 6. Open items and risks

1. **Backups**: add a nightly `pg_dump` plus a copy of `data/` to a second machine. The World Vault is the unrecoverable data.
2. **Content safety**: the owner was advised to enforce a hard rule against sexual content involving minors or characters who read as minors. Hosting providers enforce this regardless of model.
3. **Endpoint security**: the Modal URLs are public. Keep the API key mandatory.
4. Document the LLM serving layer and the embedding model.
5. Write the backend router client (`rp` vs `util`) and wire it into `llm_config`.
6. The owner offered to share UI preview screenshots for feedback (UI, features or architecture). Not yet sent.
7. Measure cold start after the first deploy, then tune quantization, context sizes and idle windows.
