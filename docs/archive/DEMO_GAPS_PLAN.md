> **ARCHIVED** — historical, kept for provenance only. This document was
> stale or superseded when archived and may contradict current code.
> **Archived. See docs/STATUS.md and docs/archive/README.md.**

> **SUPERSEDED** by `.kilo/plans/1787583794283-tnhcomfy-hardening-plan.md` (2026-08-24 audit). Many "demonstrated gaps" here were debunked — the features are already implemented. Use the new plan as the authoritative source.

# Feature-Completeness Plan — Eliminating the "Demo" Feel

> Companion to `PLAN.md` (which tracks the original 8-feature roadmap).  
> Scope: make TNHComfy usable **out-of-box for casual users** while adding **depth for power users**.  
> Auth is intentionally out of scope (local single-user AI studio). All paths below assume the standard `docker compose --profile providers` stack.

## Problem diagnosis (evidence)

| Root cause | Evidence |
|---|---|
| **Empty by default** — must hand-create every provider + token + model | 7 provider *types* registered (`infrastructure/providers/__init__.py:14-22`), **0 instances seeded**; creation is `POST /api/providers` (`providers/crud.py:244`) or auto-detection of running containers only (`provider_runtime.py:120 setup` gated to Modal+container); 4 compose provider containers sit behind `--profile providers`; `FantasyHub.jsx:76-169` is a static `CARDS` grid with no setup checklist |
| **Silent failures everywhere** | 24 `except: pass` sites swallow errors as no-ops (sample: `files.py:78,87,474,491`; `providers/crud.py:170`; `characters.py:102`; `lorebooks.py:156,191`; `lifecycle.py:174,298`) — contradicts the `ComfyError` hierarchy (`core/exceptions.py`) that `AGENTS.md` mandates |
| **Advanced Generator is stubbed** | `ComfyNode.jsx:21` explicitly "In a full implementation, we'd render inputs for primitives." — visual workflow builder is half-working |
| **Generators block on missing checkpoints with no CTA** | `Img2ImgGenerator.jsx:30`/`InpaintGenerator.jsx:25` `EMPTY_MODELS=[]`; `validateImg2Img` → `'Please select a checkpoint'` with no installer link |
| **Discoverable only if you already know where to look** | `/prompts` has no nav (`Providers.jsx:300-314` empty-state has Add action but no auto-detect) — power-user surfaces like Relationship Graph, World Timeline, Batch Studio exist but aren't surfaced from the empty home |

## Guiding principles

1. **Casual first** — from a fresh `docker compose --profile providers up`, the first 3 UI views must *do something useful* without the user reading `.env.example.*`.
2. **Progressive disclosure** — power tools hidden behind affordances, not hidden behind "figure it out".
3. **No silent errors** — every `except: pass` becomes a user-visible toast/error-boundary.
4. **Tests gate every change** (backend `pytest` + frontend `npm test`; E2E for setup flow only where trivial).

---

## Phase 1 — Onboarding & Self-Configuration (Week 1)

*Goal: a fresh stack boots to a usable state with minimal manual wiring.*

| # | Task | Files / approach | Acceptance |
|---|---|---|---|
| 1.1 | **First-run Setup Wizard** (modal, gated by a `setup_complete` flag in `Settings`/`COMFY_SETUP_COMPLETE`) | `components/OnboardingWizard.jsx` (new); trigger from `FantasyHub.jsx` when `setup_state` is incomplete; steps: (a) discover running provider containers via `GET /api/v2/providers/discovery` (`discovery.router`) and one-click enable; (b) discover local models on disk and offer to register; (c) seed a demo character + scenario. | Fresh compose → wizard auto-opens; completing it lands on `/chat`. |
| 1.2 | **Provider auto-detection button** in `Providers.jsx` (replacing the dead "no auto-detect") | `Providers.jsx:300-314`; call discovery; create `disabled` providers with credential templates; toast per result. | Clicking "Detect" lists compose-managed containers as addable rows. |
| 1.3 | **Surface 24 swallowed `except: pass`** with real toasts + `ComfyError` | Replace each with `raise ComfyError(...)` or a `toast.error`; start with the route-handlers (`files.py`, `providers/crud.py`, `characters.py`, `lorebooks.py`). | E2E: deleting a character with a 500 now shows a toast instead of silent fail. |
| 1.4 | **Generator checkpoint CTA** — when no checkpoints, link to `/models/discover` | `AdvancedGenerator.jsx`/generators; read `useModels()` list; render an action button if empty. | Empty generator page shows "Install a checkpoint" → opens Discover. |

## Phase 2 — Out-of-Box Completeness (Week 2)

*Goal: a freshly-wired stack has content to play with immediately.*

| # | Task | Files / approach | Acceptance |
|---|---|---|---|
| 2.1 | **Starter pack seed step** in DB migrations (`steps.py`), idempotent | One migration inserts 1 demo character + 1 demo scenario + default `llm-local` provider pointing at the compose `provider-llm-local` container (id `llm-local`, disabled by default so it can't steal jobs until enabled). | `pytest` confirms seed rows; `Settings → Providers` shows `llm-local`. |
| 2.2 | **Dashboard quick-start** tiles on `FantasyHub` | Add tiles: "New chat", "Continue story", "Quick scenario". | 3 new cards open the right route. |
| 2.3 | **Default provider config bootstrap** for the 4 compose container types (modal, llm-local, direct-url) in `runtime.py`/registry | Map `PROVIDER_ID → {type, default credentials}` so enabling a detected container pre-fills the form. | Enabling `llm-local` from discovery pre-fills endpoint `http://provider-llm-local:8000`. |

## Phase 3 — Power-User Depth (Week 3–4)

*Goal: the features that exist but are "demo-level" become first-class.*

| # | Task | Files / approach | Acceptance |
|---|---|---|---|
| 3.1 | **Render primitive node inputs** in the Advanced visual graph | `ComfyNode.jsx:21` stub → implement string/number/boolean/ENUM widgets; read schema from `/api/nodes/object_info`. | A primitive node renders editable inputs that propagate to the submitted prompt. |
| 3.2 | **Relationship Graph interactivity** | `RelGraph.jsx` — add pan/zoom (reactflow), node click → open entity, hover tooltips. | Clicking a character node opens `/characters`. |
| 3.3 | **World Timeline polish** | Filter chips persist in URL query; `WorldTimeline.jsx`; date-group headers sticky. | Filters survive reload; groups collapse. |
| 3.4 | **Keyboard shortcuts + command palette** | Global hook (`Cmd/Ctrl+K` palette; `Ctrl+Enter` send; `Ctrl+N` new chat; `Ctrl+S` save story). | `StorySandbox`/`ChatWorkspace` respond to keys. |
| 3.5 | **Batch Studio presets v2** | `PresetManager.jsx` — save/load named batch configs to Settings. | A named batch preset survives reload. |

## Phase 4 — Polish & Guardrails (parallel)

*Goal: confidence that nothing silently breaks and power users find everything.*

| # | Task | Files / approach | Acceptance |
|---|---|---|---|
| 4.1 | **Route guard scaffold** (future auth-ready, no-auth pass-through) | Wrap `App.jsx` routes; flag authenticated routes. | `Settings` can toggle `require_auth` for a route without code edits. |
| 4.2 | **Error Boundaries per page** | `ErrorBoundary.jsx` wrapping each lazy page (`App.jsx:72-104`). | A page throwing shows a recoverable fallback, not a white screen. |
| 4.3 | **Playwright CI** | `.github/workflows/frontend-tests.yml` uncomment `npx playwright test` (currently `# e2e`). | PR E2E runs on `frontend_v2/**` changes. |

---

## Verification matrix

- Backend: `cd backend_v2 && pytest -q` (target: green; new migration seed asserts rows).
- Frontend unit: `cd frontend_v2 && npm test` (target: green; OnboardingWizard + generator CTA tested with mocked hooks).
- Lint: `npm run lint` (target: 0 errors) + `ruff check backend_v2`.
- E2E: `npx playwright test --grep-invert @fullstack` (new: onboarding wizard happy path if Phase 1.1 lands).

## Recommended start

**Phase 1.3 first** (swallow-fix) — it's pure reliability, touches isolated files, and the unit tests already assert several of those code paths. Then **1.1/1.2** (wizard + detect) which removes the "I can't do anything" feeling. I'll queue 1.4 + 2.1 in parallel.

---

*Status: plan written, not yet executed. Awaiting go-ahead on Phase 1 ordering (recommended: 1.3 → 1.1/1.2 → 1.4 → 2.1).*
