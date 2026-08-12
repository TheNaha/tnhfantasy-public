# Playwright E2E Test Suite

Workflow tests: frontend (5174) → backend (8002) → provider containers → remote inference.

## Prerequisites

The full stack must be running with providers:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d
```

Then verify the frontend answers on `http://localhost:5174` and the API on `http://localhost:8002`.

## Running

```bash
cd frontend_v2
npx playwright install chromium   # once, if not installed

npm run test:e2e                 # full suite (serial)
npm run test:e2e:ui              # UI-level tests only (skips real @fullstack generations)
npm run test:e2e:fullstack       # only the real-generation workflow tests
npx playwright test e2e/chat     # single folder
npx playwright test e2e/chat/messaging.spec.js   # single spec
npx playwright test --headed     # watch the browser
npx playwright show-report       # view the HTML report after a run
```

## Test taxonomy

| Tag | Meaning |
|---|---|
| `@fullstack` | Runs a real job end-to-end (image gen through Modal/Beam, LLM replies through llm-local). Slow and billed. |

## Conventions

- **Serial execution** (`workers: 1`) — the suite shares one real DB; parallel runs corrupt each other.
- **Unique entities** — every created entity uses `uniqueName(prefix)` (timestamp + random suffix) and is deleted via `cleanupEntities` in `afterEach`.
- **Never rely on existing user data** — the gallery/dashboard contain real generations; tests only assert on entities they created themselves.
- **Settings tests** snapshot settings before mutating and restore them after.
- **Hover to reveal** — chat message actions and sidebar delete buttons are `opacity-0` until hover; `page.hover()` first.
- **No `data-testid` in production code** — select by role, accessible name, title, or placeholder.
- **Test bugs are bugs** — if a test exposes an app bug, fix the app, don't work around it.

## Fixtures

`e2e/fixtures.js` provides:

- `apiGet/apiPost/apiPut/apiPatch/apiDelete` — API calls (page first arg, throw on !ok)
- `uniqueName(prefix)` — deterministic-unique entity names
- `expectToast(page, regex)` — strict toast assertion (react-hot-toast `[role="status"]`)
- `waitForJob(page, jobId, {timeout, expected})` — polls `GET /api/jobs/{id}` to a terminal state
- `makeTestImage()` / `toDataUrl()` — pure-Node PNG generator for uploads and masks
- `seedCharacter/seedLorebook/seedChat/seedStory/seedStoryChapter/seedPrompt/seedCollection`
- `cleanupEntities(page, [{kind, id}])` — API cleanup for every seeded kind
- `drawMaskOnCanvas(canvas, {from, to})` — draws an inpaint mask via mouse events
