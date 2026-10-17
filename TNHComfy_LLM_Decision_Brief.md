# TNHComfy LLM Hosting: Decision Brief

Covers the planning conversation from 2026-10-10 to 2026-10-17. It supersedes the earlier `TNHComfy_LLM_Handoff.md`, whose model picks are outdated.

**How to read the evidence tags**
- **[fetched]**: read from a web page, repo listing, config file or the user's UGI CSV during the session.
- **[computed]**: calculated from fetched configs or prices.
- **[memory]**: from background knowledge and not checked. Verify before relying on it.
- **[estimate]**: a guess.

Nothing here has been deployed or benchmarked by the assistant. A comment in the user's own code cites one measured model-load time (section 6); the assistant did not verify it.

---

## 1. TL;DR for deciders

- **Goal.** Host uncensored open-weight LLMs for a personal NSFW roleplay app on Modal serverless. It needs fast cold start, good quality, vision input, and one role for roleplay prose (`rp`) and one for background work (`util`).
- **GPU limits.** The user said L40S (48 GB) and A100 40 GB are fine and anything bigger is discouraged. Late in the conversation they asked what to do if they are limited to an L4 (24 GB). Whether L4-only is a real constraint is unresolved.
- **The community has moved to Gemma 4.** Gemma 4 31B finetunes lead the Oct 2026 r/SillyTavernAI thread. Earlier recommendations (Mistral Small 3.2 finetunes such as Magnum-Diamond and Cydonia) came from older roundups and are now backups.
- **Current candidate `rp` primary:** TheDrummer Artemis 31B v1.2 (Reddit-favoured prose). It is not on the UGI leaderboard. The measured alternatives are abliterated stock Gemma 4 (best intelligence plus willingness on UGI) and the 26B-A4B mixture-of-experts finetunes (much faster).
- **`util` should not be stock Gemma 4.** UGI willingness for the stock 31B is 2.5/10, which risks refusals during NSFW memory extraction and captioning.
- **Two 31B models cannot share one L40S.** Their weights alone are 47.7 GB. A 12B `util` next to Artemis can fit, but only if llama.cpp's default window-sized KV cache is kept (section 5).
- **The user's code is on a role-class design** (`ChatRP` / `ChatUTIL`, SDK-only, no public URLs). It has three issues: `urls` and `bench` are broken, runtime model selection and fallback are impossible, and there is no concurrency (section 6).
- **Decisions needed:** listed in section 8, each with the assistant's recommendation.

---

## 2. Project and requirements

- **TNHComfy** is a self-hosted, personal-use-only "Fantasy Engine" web app. It started as a ComfyUI wrapper and now has three pillars on one PostgreSQL + pgvector data layer (the "World Vault"):
  - image generation on serverless workers or provider containers (Modal, Beam)
  - SillyTavern-style LLM roleplay with chats, group chats, ST JSONL import/export, agentic tools, autobiographical memory (`memory_extraction` + `rag_pipeline`), idle simulation and per-entity sampler overrides
  - a Story Sandbox with branches, sessions, tags and a world graph and timeline
- **Stack:** FastAPI backend, React frontend, docker compose with Traefik. The project summary's roadmap says P1-P6 are done.
- **Known gap:** there are **no automatic backups**. The assistant advised a nightly `pg_dump` plus a copy of `data/` to another machine.
- **Documentation advice given:** split into `README.md`, `ARCHITECTURE.md` and `CONFIG.md`. State where the LLM runs and which protocol the backend uses. State the embedding model and dimension, because changing it forces re-embedding all memories. Drop commit hashes from the roadmap line.
- **Requirements for LLM hosting:**
  - uncensored, because the app includes NSFW roleplay and is for the owner only
  - hosted on Modal serverless functions, with weights in Modal Volumes
  - fast cold start, because chats are occasional
  - good quality: long-context consistency with lorebooks, instruction following and structured output
  - image reading (vision) in chat
  - multiple models are fine if they boot quickly
  - a selector with an ordered fallback list per role
- **Safety note given:** keep a hard rule against sexual content involving minors or characters who read as minors. Hosting providers enforce this regardless of model.

### Job kinds in the app (relayed from another agent)

| Job | Role | Frequency |
|---|---|---|
| `chat_reply` | rp | every user message |
| `memory_extraction` | util | about every 2nd message (`MEMORY_EXTRACTION_MIN_NEW_TURNS = 2`), enqueued after the reply finishes |
| `narrator` | rp | when the user presses narrate |
| `caption` / `tool_call` | util | only with images or the agentic loop |

- The LLM pool has one worker per LLM provider, so with two roles an extraction can overlap the next user message.
- Containers stay warm for about 60 s after their last call.

---

## 3. Conversation timeline

1. **Opening question.** The assistant listed hosted options from search roundups (Claude, DeepSeek V4, GLM, Kimi, Gemini/GPT) and architecture tips: two-model setup, vision captioning separate from the roleplay model, a provider-agnostic interface, and selective lorebook injection.
2. **Open-weight on Modal.** The assistant suggested Mistral Small 3.2 24B RP finetunes, with 12B Nemo as the smaller tier and 70B judged not worth the cold start and cost. Cold-start tips were: weights in a Volume, quantize, llama.cpp instead of vLLM, `scaledown_window`, and matching the GPU to the model.
3. **Project summary review.** Documentation and backup advice as above, plus a two-model split: a roleplay finetune for prose and a stock instruct model for tool calls and extraction.
4. **First `modal_llm.py`.** One llama.cpp `web_server` per model. Later superseded.
5. **Model discovery.** The assistant checked Magnum-Diamond, the Cydonia merge and the Unsloth Mistral Small 3.2 GGUF. A March 2026 roundup added Cydonia v4.3, Magidonia, Dolphin Venice, Goetia and Pantheon.
6. **Reddit thread.** Reddit was blocked for the assistant's tools, so the user pasted the r/SillyTavernAI "Models 16B to 31B" thread (dated about Oct 5, 2026). It changed the picks to Gemma 4 finetunes (section 4).
7. **Registry-driven `modal_llm.py`** (one function per enabled model, pattern-based download, `bench`, `urls`). It imported cleanly on `modal` 1.6.1.
8. **UGI leaderboard.** The Space could not be read directly and a direct download was blocked. The user attached `ugi-leaderboard-data.csv` (1,326 rows, 71 columns, tests through 2026-10-02). The assistant analysed it (section 4).
9. **Final lists with GGUF files verified** (section 4). The assistant's registry was updated to match.
10. **The user shared their own finished `modal_llm/app.py`**, which supersedes the assistant's script. The assistant never saw its `registry.py` or `models.json`. Review findings are in section 6.
11. **A second agent's single-container proposal** was relayed and evaluated (section 5).
12. **L4-only options** were evaluated (section 7).

---

## 4. Model evidence

### UGI leaderboard (user-supplied CSV, non-thinking rows) [fetched]

W/10 is the leaderboard's willingness score. NatInt is its intelligence score. UGI is the overall score. Thinking-prefill rows score higher: for example, the coder3101 31B reaches UGI 65.7.

| Model | UGI | Writing | W/10 | NatInt |
|---|---|---|---|---|
| coder3101/gemma-4-31B-it-heretic | 56.4 | 39.6 | 10 | 35.6 |
| llmfan46/gemma-4-31B-it-uncensored-heretic | 53.8 | 38.3 | 9.5 | 34.7 |
| google/gemma-4-31B-it (stock) | 21.5 | 38.6 | 2.5 | 34.4 |
| MuXodious/gemma-4-26B-A4B-it-SOMPOA-heresy | 40.4 | 43.5 | 8.0 | 34.7 |
| llmfan46/gemma-4-26B-A4B-it-ultra-uncensored-heretic | 45.0 | 42.1 | 8.8 | 33.7 |
| Naphula/Goetia-26B-A4B-v1.3-Absolute-Heretic-ARA | 43.8 | 40.9 | 8.2 | 29.7 |
| google/gemma-4-26B-A4B-it (stock) | 20.8 | 41.6 | 1.8 | 34.4 |
| FlareRebellion/WeirdCompound-v1.7-24b | 48.0 | 47.0 | 8.0 | 30.2 |
| TheDrummer/Cydonia-24B-v4.3 | 44.5 | 41.4 | 7.0 | 19.5 |
| Mistral Small 3.2 24B Instruct (stock) | 40.4 | 36.3 | 6.5 | 23.9 |
| Doctor-Shotgun/MS3.2-24B-Magnum-Diamond | 22.8 | 35.9 | 2.2 | 23.6 |
| llmfan46/gemma-3-12b-it-ultra-uncensored-heretic | 38.0 | 29.3 | 9.5 | 20.7 |
| grimjim/gemma-3-12b-it-norm-preserved-biprojected-abliterated | 40.1 | 30.4 | 9.2 | 21.3 |
| coder3101/gemma-4-E4B-it-heretic | 37.7 | 22.3 | 9.8 | 18.7 |
| trohrbaugh/Qwen3.5-9B-heretic-v2 | 37.6 | 32.5 | 9.2 | 16.1 |
| google/gemma-4-12B-it (stock) | 15.2 | 31.6 | 1.2 | 25.8 |

- WeirdCompound-v1.7 also has avg NSFW 7.8 and avg dark 7.5. Magnum-Diamond has NSFW 7.0 and dark 7.2 despite its low willingness. Those two columns' definitions were not checked.
- **The CSV has no rows for Artemis, Dark Thoughts, Writers, Split-Untied or StyleTune.** The only Gemma 4 finetunes on it are abliterations and merges.
- **No abliterated Gemma 4 12B exists on the board.** Stock Ministral 3 has W/10 6.0 (8B) and 4.2 (14B).
- **UGI measures willingness and intelligence, not roleplay prose quality.**

### Reddit thread (r/SillyTavernAI, ~Oct 5 2026) [fetched via user paste]

One week of anecdotes from a few testers.

- Gemma 4 31B finetunes lead: Artemis 1.2 (TheDrummer), Dark Thoughts V2, Split-Untied, Writers-31B-V2, Spectre-37B.
- Artemis 1.2: one tester saw 1 hard refusal in 30 NSFW prompts and called it intelligent, but it keeps a positivity bias and tends to go soft on dark content. Another called it a sidegrade to an abliterated stock Gemma 4. One comment says it scores very well on Caliperbench v3.
- **Quant warnings:** Artemis v1.1 Q3/Q4 quants were reported as gibberish. One tester found Artemis at IQ3_XXS "painful" on comprehension.
- Gemma 4 holds up to about 80K context, degrades after about 110K, and has a very large KV cache. Qwen3.8 27B is a dark horse but was inconsistent and slop-prone for some testers.
- Writers-31B-V2 was called "goated" for long roleplay (tested in Russian). Dark Thoughts V2 had the best multilingual behaviour. Split-Untied leaks English with the stock preset.
- **Speed on an RTX 4060 Ti 16 GB** (bandwidth close to an L4), single slot, KV q4_0:

| Model | Quant | Generation | Prompt processing |
|---|---|---|---|
| Dark Thoughts V2 31B | IQ3_XXS | ~23 tok/s (with MTP speculative decoding) | 306 tok/s |
| Artemis 31B v1.2 | IQ3_XXS | ~21 tok/s (with MTP) | ~550 tok/s |
| StyleTune-V2 26B-A4B | IQ4_XS | ~63 tok/s (no MTP; speculation hurts RP on this MoE) | ~413 tok/s |
| WaifuGemma4 26B-A4B | IQ3_XXS | ~85 tok/s | ~1300 tok/s |

### GGUF repos and files [fetched listings]

Sizes are decimal GB. "i1" repos are mradermacher imatrix quants. **Most Gemma 4 finetune repos ship no `mmproj`.**

| Model | Repo | File (size) | Vision file |
|---|---|---|---|
| Artemis 31B v1.2 | `bartowski/TheDrummer_Artemis-31B-v1.2-GGUF` | `…-Q5_K_M.gguf` (23.5), `…-Q4_K_M.gguf` (19.5), `…-IQ4_XS.gguf` (17.2), `…-IQ3_M.gguf` (16.4) | `mmproj-TheDrummer_Artemis-31B-v1.2-f16.gguf` (1.2) |
| Stock Gemma 4 31B | `unsloth/gemma-4-31B-it-GGUF` | `gemma-4-31B-it-Q4_K_M.gguf` (18.3), `…-Q5_K_M.gguf` (21.7) | `mmproj-F16.gguf` (1.2) |
| Gemma 4 31B heretic (coder3101) | `mradermacher/gemma-4-31B-it-heretic-i1-GGUF` | `gemma-4-31B-it-heretic.i1-Q5_K_M.gguf` (21.85), `…i1-Q4_K_M.gguf` (18.69) | none |
| Writers-31B-V2 | `mradermacher/Gemma-4-Writers-31B-V2-i1-GGUF` | `Gemma-4-Writers-31B-V2.i1-Q5_K_M.gguf` (21.85) | none |
| Dark Thoughts V2 31B | `mradermacher/Gemma-4-Dark-Thoughts-V2-31B-i1-GGUF` | `Gemma-4-Dark-Thoughts-V2-31B.i1-Q5_K_M.gguf` (21.85) | none |
| Split-Untied 31B | `mradermacher/Split-Untied-31B-i1-GGUF` | `Split-Untied-31B.i1-Q5_K_M.gguf` (22.8) | none |
| SOMPOA-heresy 26B-A4B | `mradermacher/gemma-4-26B-A4B-it-SOMPOA-heresy-i1-GGUF` | `gemma-4-26B-A4B-it-SOMPOA-heresy.i1-Q4_K_M.gguf` (16.8), `…Q5_K_M` (19.1) | none |
| 26B-A4B ultra-uncensored heretic | `llmfan46/gemma-4-26B-A4B-it-ultra-uncensored-heretic-GGUF` | `gemma-4-26B-A4B-it-ultra-uncensored-heretic-Q4_K_M.gguf` (16.8), `…-Q5_K_M.gguf` (19.1) | `gemma-4-26B-A4B-it-mmproj-BF16.gguf` (1.19) |
| Goetia-26B-A4B v1.3 | `mradermacher/Goetia-26B-A4B-v1.3-Absolute-Heretic-ARA-i1-GGUF` | `Goetia-26B-A4B-v1.3-Absolute-Heretic-ARA.i1-Q5_K_M.gguf` (19.1) | none |
| StyleTune-V2 26B-A4B | `mradermacher/Gemma-4-26B-A4B-StyleTune-V2-i1-GGUF` | `Gemma-4-26B-A4B-StyleTune-V2.i1-Q4_K_M.gguf` (17.2) | none |
| WeirdCompound-v1.7 24B | `mradermacher/WeirdCompound-v1.7-24b-i1-GGUF` | `WeirdCompound-v1.7-24b.i1-Q5_K_M.gguf` (16.8), `…Q4_K_M` (14.3) | none (text-only) |
| Magnum-Diamond 24B | `Doctor-Shotgun/MS3.2-24B-Magnum-Diamond-GGUF` (linked from its card) | filename not seen | none |
| Mistral Small 3.2 Instruct | `unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF` | `Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf` (14.3) | `mmproj-F16.gguf` (0.88) |
| Gemma 3 12B heretic | `llmfan46/gemma-3-12b-it-ultra-uncensored-heretic-GGUF` | `gemma-3-12b-it-heretic-Q5_K_M.gguf` (8.4); no Q4_K_M | `gemma-3-12b-it-mmproj-BF16.gguf` (0.85) |
| Gemma 3 12B stock mmproj | `unsloth/gemma-3-12b-it-GGUF` | `gemma-3-12b-it-Q4_K_M.gguf` (7.3) | `mmproj-F16.gguf` (0.85) |
| Gemma 4 E4B heretic | `Abiray/gemma-4-E4B-it-heretic-GGUF` | `gemma-4-E4B-it-heretic-Q5_K_M.gguf` (5.8) | `mmproj-F16.gguf` (0.99) |
| Qwen3.5-9B heretic v2 | `AIImageStudio/Qwen3.5-9b-heretic-v2-GGUF` | `Qwen3.5-9b-heretic-v2-q8_0.gguf` (9.5), the only quant | `Qwen3.5-9b-mmproj-BF16.gguf` (0.92) |

### Other facts

- **Gemma 4 chat-template bug:** a secondary report says Gemma 4 GGUFs built before about May 1, 2026 carry a faulty template (the model runs past its turn, prints `<end_of_turn>`, or invents user replies). The weights are unaffected. Fix: re-download a newer build, or pass `--chat-template-file`. Several repos above were built in April (heretic 31B, SOMPOA). Test three turns on any Gemma 4 GGUF.
- **Gemma 4 sampler defaults** from model cards: temperature 1.0, top_p 0.95, top_k 64. Thinking is enabled by starting the system prompt with `<|think|>`. Put images before text.
- **Artemis card:** Gemma 4 31B base; thinking and non-thinking both work; the card mentions roleplay and tool calls; no recommended samplers.
- **Cross-repo vision is untested:** using the stock Gemma 4 `mmproj` with an abliterated model should usually work, but nobody has tried it with a real image.
- **Reddit and Hugging Face API access** was blocked for some tools, so thread content came from the user's paste.

---

## 5. Capacity math

### Gemma 4 KV cache [computed from fetched configs]

- **31B:** 60 layers = 50 sliding-window (window 1024, 16 KV heads × head_dim 256) + 10 full-attention (4 KV heads × 512).
- **26B-A4B:** 30 layers = 25 sliding (8 × 256) + 5 full (2 × 512). 128 experts, 8 active.
- **KV at 32k context:**

| Model | q8_0, default window-sized cache | q8_0, `--swa-full` |
|---|---|---|
| 31B | ~2.1 GB (f16: ~3.9) | ~15.7 GB (f16: ~29.5) |
| 26B-A4B | ~0.5 GB | not computed |

- The default cache can force a full prompt reprocess when something deep in the prompt changes, such as a lorebook entry appearing or disappearing, or a regeneration after an edit. `--swa-full` avoids that at the large cost above. This is probably why Reddit calls the cache "massive". **Check the `KV buffer size` lines in the llama-server startup logs before trusting any figure here.**
- Mistral Small 3.2 KV at 32k is about 2.85 GB [estimate, config from memory].

### Modal GPU prices [fetched from modal.com/pricing; CPU/RAM charges not checked]

| GPU | per second | per hour |
|---|---|---|
| L4 | $0.000222 | ≈ $0.80 |
| A10 | $0.000306 | ≈ $1.10 |
| L40S | $0.000542 | ≈ $1.95 |
| A100 40 GB | $0.000583 | ≈ $2.10 |
| A100 80 GB | $0.000694 | ≈ $2.50 |

- Modal supports multiple GPUs per container (`gpu="L4:2"`; up to 8 L4s, 4 A10s; more than 2 usually waits longer).

### Plan A: one L40S, both roles (second agent's proposal)

- Two llama-server processes on separate ports in one container.
- Artemis Q5_K_M + its mmproj is 24.7 GB. Add its KV at 32k (~2.1 GB) and a ~12B vision `util` (~9.3 GB with vision plus ~1 GB KV). Allow ~3-4 GB for CUDA contexts and buffers [estimate]. The total is about 40-42 GB of 48.
- **It only fits with the default KV cache.** With `--swa-full`, Artemis's KV alone is about 15.7 GB and nothing else fits.
- It needs `@modal.concurrent` so a reply and an extraction can both be in flight. Artemis's token speed will dip while extraction overlaps, because both processes share the GPU.
- Cost: one L40S at $1.95/hr, against $3.90/hr for two warm L40S containers.

### Plan B: `rp` on an L40S, `util` on an L4

- About $2.75/hr while both are warm. No VRAM contention, and the L4 has room for a stronger `util` (Mistral Small 3.2 at 15.2 GB, or the 26B-A4B heretic at about 18 GB).

### Plan C: no separate `util`

- Run Artemis with `--parallel 2`, using its own vision file and tool-call ability. This costs no extra VRAM, but extraction and tool quality from a roleplay finetune is untested, and slot prompt-cache behaviour is a risk.

### Plan D: L4 only (24 GB per card; ~300 GB/s bandwidth [memory])

Budget for weights + KV is about 22.6 GB (24.1 usable minus ~1.5 overhead [estimate]). Everything below fits. Speed is the limit, because dense models are bandwidth-bound.

| `rp` option | Weights + KV at 32k | Generation ceiling on L4 | Notes |
|---|---|---|---|
| 26B-A4B finetune, Q4_K_M | ~17.7-18.5 GB | ~130 tok/s (Reddit: 63-85 on a 4060 Ti) | The assistant's pick. |
| Artemis 31B IQ4_XS | 19.3 GB (no mmproj) | ~17 tok/s, expect low teens | Prompt processing ~300-550 tok/s on the Reddit card, so a 20k-token rebuild is ~40-65 s. Avoid IQ3. |
| WeirdCompound 24B Q5_K_M | 19.7 GB | ~18 tok/s | Text-only. NatInt 30.2. |

- One L4 cannot hold a ~17 GB `rp` plus any `util`. Use a second L4 container for `util`: two L4s are about $1.60/hr, below one L40S. A 24 GB `util` card has room for Gemma 3 12B heretic (9.3 GB incl. vision, ceiling ~30 tok/s), the 26B-A4B heretic (18 GB incl. vision), or Mistral Small 3.2.
- `L4:2` in one container buys capacity, not speed: llama.cpp splits layers across the cards sequentially, so the ceiling for Artemis Q5 is about 12 tok/s [estimate, unbenchmarked].
- A10 (24 GB, about twice the L4's bandwidth [memory], $1.10/hr) roughly doubles the dense-model ceilings, if the constraint is budget and not availability.

### `util` candidates that fit beside Artemis in one L40S [UGI + fetched files]

| Model | Files | Notes |
|---|---|---|
| llmfan46 Gemma 3 12B heretic | Q5_K_M 8.4 GB + mmproj 0.85 GB | The assistant's pick. Highest willingness (9.5) with the vision file in the same repo. |
| grimjim Gemma 3 12B biprojected abliterated | mradermacher i1 GGUF + unsloth `mmproj-F16.gguf` | Highest NatInt (21.3) among willing 12Bs. |
| coder3101 Gemma 4 E4B heretic | Q5_K_M 5.8 GB + mmproj 1.0 GB | Smallest and fastest. Same family as Artemis, so check the template. |
| trohrbaugh Qwen3.5-9B heretic v2 | Q8_0 9.5 GB + mmproj 0.92 GB | Tagged image-text-to-text. Lowest NatInt (16.1). Run it non-thinking. |

- Avoid stock `gemma-4-12B-it` (W/10 1.2).

---

## 6. The user's current code (`modal_llm/app.py`, review findings)

**What it is:**
- Two Modal classes built from a shared base, `ChatRP` and `ChatUTIL`, one per role. Each runs one llama-server on loopback at container start.
- Methods `complete`, `stream` and `health`, reached through the Modal SDK. There are no web endpoints and no public URLs.
- `max_containers=1`, a baked-in registry (`models.json` and `registry.py` added with `add_local_dir`), and a slim CPU download image.
- Helpers `ensure_model` (idempotent on-demand download) and `volume_state`. Default download is each role's primary only.
- A comment in the user's code cites a measured ~16 s to load a 23.5 GB GGUF from a Volume. The assistant did not verify that this counts container start to healthy.
- The assistant never saw `registry.py` or `models.json`. Against a stub registry on `modal` 1.6.1 the file imported and registered both classes plus `download`, `ensure_model` and `volume_state`.

**Strengths:** SDK-only access, no public endpoints, the slim download image, an idempotent `ensure_model`, a stdlib-only proxy, and streaming that should cancel generation when the client disconnects.

**Findings:**

1. **`urls` and `bench` are broken.** They look up `serve_<id>` functions that no longer exist, and there are no URLs. `bench` should time `.health.remote()`. The header docstring still describes POST-to-URL calls. The `stream` docstring says `.gen()`, but Modal's `Function` has `remote_gen` and no `gen`.
2. **Runtime selection and fallback are impossible.** Each class is bound to its role's primary at deploy time. Non-primary enabled models have no function, so `ensure_model` can fetch them but nothing can serve them until `models.json` is edited and redeployed.
   - **Suggested fix:** one parameterized class `ChatLLM(model_id=modal.parameter())`. Each parameter value gets its own container pool and idle timer, with no URLs. The backend walks the role's list on failure.
   - **Caveats:** GPU and idle time become class-level. Modal's docs do not say whether `max_containers=1` applies per parameter value or across all values, so test it early.
3. **No `@modal.concurrent`.** Without it Modal sends one input at a time, so `util`'s `parallel=2` slots are never used and a long extraction blocks captioning and tool calls.
4. **Minor:**
   - The header says "has not been deployed" though comments describe a past deployment failure and a measured load time.
   - The `Popen` handle is not kept, so a dead llama-server stays dead until the container scales down.
   - `vol.reload()` is needed to see files committed by another container.
   - A pre-warm should use `.health.spawn()` when `/chat` opens.
   - The first call after idle blocks through the cold start, so set generous backend timeouts.
   - The backend needs the `modal` package and a Modal token.

**Fallback semantics advised for the selector:**
- Do not treat a cold start as a failure. Give the first request a generous timeout, around 90-120 s, and fall back only on connection errors, 5xx responses, or a timeout past that budget.
- Add a circuit breaker that skips a failed endpoint for a few minutes.
- A fallback with a smaller context window needs the context builder to trim lorebook injection.
- Show a "fell back to X" indicator in the chat instead of switching silently.
- Keep roles separate: if `util` is down, skip captioning instead of sending the image to a text-only `rp` model.

**The assistant's own earlier script** (`/mnt/user-data/outputs/modal_llm.py`, a web_server-per-model registry with `rp` Artemis → Writers → heretic → SOMPOA → WeirdCompound → Magnum-Diamond, and `util` heretic 31B → 26B-A4B heretic → Mistral Small 3.2) is superseded by the user's version. It remains useful as a model and GGUF reference.

---

## 7. Corrections made along the way

- Early recommendations from March 2026 roundups were superseded by the Oct 2026 Reddit thread.
- The assistant first read Magnum-Diamond's UGI (22.8) as "much less uncensored". The full row shows low willingness (2.2) but high NSFW/dark writing scores (7.0/7.2), so it is mixed.
- The assistant's first `util` default was stock Gemma 4 31B. The CSV shows it refuses (W/10 2.5), so abliterated variants replaced it.
- The assistant's first design hid cold starts behind a `/health` ping. With no URL in the user's SDK design, use `.health.spawn()` instead.

---

## 8. Decisions needed

| # | Decision | Options | Assistant's recommendation |
|---|---|---|---|
| 1 | GPU tier | L40S/A100 40 GB allowed (A, B, C) or L4 only (D) | If the L40S is allowed: A with the default KV cache, or B. If L4 only: two L4 containers. Confirm whether L4-only is a real constraint. |
| 2 | `rp` primary | Artemis 31B (best Reddit prose); heretic stock 31B (best measured intelligence + willingness); 26B-A4B MoE (fast; best on L4) | L40S: Artemis, with the heretic and 26B-A4B in the selector for A/B. L4: the 26B-A4B ultra-uncensored heretic. |
| 3 | `util` primary | Gemma 3 12B heretic; Gemma 4 31B heretic (shares weights with `rp`); 26B-A4B heretic; Mistral Small 3.2 | Gemma 3 12B heretic if sharing a container; the 26B-A4B heretic on its own L4. |
| 4 | Modal architecture | role classes (current); one parameterized `ChatLLM`; web_server per model | Parameterized class, so the selector and fallback work at runtime. Fix `urls`/`bench` and add `@modal.concurrent` either way. |
| 5 | KV/prompt-cache policy | default window-sized cache or `--swa-full` | Default, unless lorebook-driven reprocessing proves too slow. `--swa-full` rules out the single-container plan. |
| 6 | Vision path | Artemis's own mmproj; a `util` captioner; stock mmproj on a finetune | Caption through `util` once and put the text in context, so images are not resent each turn. Keep Artemis's mmproj as an option. Test the cross-repo projector. |
| 7 | Thinking mode | off (Reddit RP default) or on | Off for roleplay. |

**Next steps:**
1. Add `@modal.concurrent`, repair `urls`/`bench`, and decide on the parameterized class.
2. Deploy, then run a three-turn template check on every Gemma 4 GGUF.
3. Read the `KV buffer size` log lines at the chosen context size.
4. Measure cold start per model after idle.
5. A/B the `rp` candidates on three real lorebook-heavy scenes. Run real chat transcripts through the `util` model's extraction, with an NSFW sample.
6. Add the nightly Postgres backup.

---

## 9. Unverified or risky items

- Nothing was deployed or benchmarked by the assistant. All speed figures are bandwidth ceilings or another person's numbers on a different card.
- The KV and memory budgets rely on the model configs, an assumed llama.cpp SWA cache behaviour, a 1.5-4 GB overhead guess, and a Mistral config recalled from memory.
- The Gemma 4 template-bug report is secondary and its affected-build cut-off date is approximate.
- Cross-repo `mmproj` compatibility, the Magnum-Diamond GGUF filename, and the exact definitions of UGI's NSFW and dark columns are unchecked.
- L4 bandwidth (~300 GB/s), A10 bandwidth, and the RTX 4060 Ti comparability come from background knowledge.
- Reddit consensus reflects a few testers in one week, and some tests were in Russian.
- Modal's docs page did not say how `max_containers` behaves across parameter values.
- Whether Modal `app.cls` with a dynamically built subclass deploys cleanly was verified only by importing locally, not by deploying.
