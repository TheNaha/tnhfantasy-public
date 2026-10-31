import { expect, test as testBase } from '@playwright/test';
import zlib from 'node:zlib';

const API_BASE = '/api/v2';
const TRACKED_ENTITIES = new WeakMap();
const ENTITY_KINDS = {
  characters: 'character',
  chats: 'chat',
  stories: 'story',
  locations: 'location',
  lorebooks: 'lorebook',
  worlds: 'world',
  collections: 'collection',
  prompts: 'prompt',
  scenarios: 'scenario',
  voices: 'voice',
  models: 'model',
  providers: 'provider',
};

function trackCreatedEntity(page, path, data) {
  const match = path.split('?')[0].match(/^\/(characters|chats|stories|locations|lorebooks|worlds|collections|prompts|scenarios|voices|models|providers)$/);
  if (match) {
    trackEntity(page, ENTITY_KINDS[match[1]], data?.id);
    return;
  }
  const chapterMatch = path.split('?')[0].match(/^\/stories\/([^/]+)\/chapters$/);
  if (chapterMatch) trackEntity(page, 'chapter', data?.id ? `${chapterMatch[1]}:${data.id}` : undefined);
}

// The single cleanup registry for the whole suite. `apiPost` records what it
// creates, so an API-seeded entity is cleaned up with no help from the spec;
// `trackEntity` is for the entities a test creates some *other* way (through the
// UI, or as a side effect of an action the test triggers) and therefore has to
// be registered by hand. One registry, one afterEach, no per-spec `created`
// array to keep in sync with it.
function trackEntity(page, kind, id) {
  if (!kind || !id) return;
  const tracked = TRACKED_ENTITIES.get(page) || [];
  tracked.push({ kind, id });
  TRACKED_ENTITIES.set(page, tracked);
}

const TERMINAL_JOB_STATUSES = new Set(['completed', 'failed', 'cancelled']);

// ---------------------------------------------------------------------------
// Path resolution
// ---------------------------------------------------------------------------

/**
 * Resolve an e2e path to a real backend URL.
 *
 * The API is not uniformly versioned. Most of it lives under `/api/v2`, but
 * `/api/settings`, `/api/prompts` and `/api/jobs` are unversioned, and this
 * harness used to prefix `/api/v2` onto whatever it was handed. Fourteen call
 * sites across five specs therefore requested routes that do not exist:
 * `GET /api/v2/settings` (404 — the real one is `/api/settings`),
 * `GET /api/v2/jobs/{id}`, `POST /api/v2/prompts`, and so on. Every helper
 * throws on `!res.ok()`, so those tests could not pass, which means the e2e CI
 * job could not have been green — the failure was invisible only because the
 * job was not the thing anyone looked at.
 *
 * Resolving here rather than at 46 call sites keeps the default short (most
 * endpoints really are `/api/v2/...`) while making an unversioned path
 * impossible to get wrong: pass the real path and it is used verbatim.
 *
 * `backend_v2/tests/test_e2e_endpoint_contract.py` walks every spec and asserts
 * each resolved path exists in `app.openapi()`, so a typo cannot come back.
 */
export function resolveApiPath(path) {
  if (typeof path !== 'string') {
    throw new TypeError(`resolveApiPath needs a string, got ${typeof path}`);
  }
  if (!path.startsWith('/')) {
    throw new Error(`e2e API path must start with '/', got ${JSON.stringify(path)}`);
  }
  // Already an absolute backend path: use it exactly as given.
  if (path === '/api' || path.startsWith('/api/')) return path;
  return API_BASE + path;
}

// ---------------------------------------------------------------------------
// Raw API helpers (page.request; page is the FIRST argument)
// ---------------------------------------------------------------------------

async function apiDelete(page, path) {
  const res = await page.request.delete(resolveApiPath(path));
  if (!res.ok()) throw new Error(`Cleanup DELETE ${path} failed: ${res.status()}`);
  return res.json().catch(() => ({}));
}

async function apiGet(page, path) {
  const res = await page.request.get(resolveApiPath(path));
  if (!res.ok()) throw new Error(`GET ${path} failed: ${res.status()}`);
  return res.json();
}

async function apiPost(page, path, body) {
  const res = await page.request.post(resolveApiPath(path), {
    data: body,
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok()) throw new Error(`POST ${path} failed: ${res.status()}`);
  const data = await res.json();
  trackCreatedEntity(page, path, data);
  return data;
}

async function apiPut(page, path, body) {
  const res = await page.request.put(resolveApiPath(path), {
    data: body,
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok()) throw new Error(`PUT ${path} failed: ${res.status()}`);
  return res.json();
}

async function apiPatch(page, path, body) {
  const res = await page.request.patch(resolveApiPath(path), {
    data: body,
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok()) throw new Error(`PATCH ${path} failed: ${res.status()}`);
  return res.json();
}

async function apiUpload(page, path, fileName, buffer, mimeType, fields) {
  const fd = new FormData();
  fd.append('file', new Blob([buffer], { type: mimeType }), fileName);
  for (const [k, v] of Object.entries(fields || {})) fd.append(k, v);
  const res = await page.request.post(resolveApiPath(path), { multipart: fd });
  if (!res.ok()) throw new Error(`UPLOAD ${path} failed: ${res.status()}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Naming & misc
// ---------------------------------------------------------------------------

function uniqueName(prefix) {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
}

// ---------------------------------------------------------------------------
// Toasts (react-hot-toast renders [role="status"] items, top-right)
// ---------------------------------------------------------------------------

async function expectToast(page, regex, timeout = 15000) {
  const toast = page
    .locator('[role="status"], [class*="toast"], [class*="Toast"]')
    .filter({ hasText: regex });
  await expect(toast.first()).toBeVisible({ timeout });
}

// Backward-compatible alias used by the original specs.
async function waitForToast(page, regex, timeout = 10000) {
  await expectToast(page, regex, timeout);
}

// ---------------------------------------------------------------------------
// Job completion polling (GET /api/jobs/{id} until terminal state)
// ---------------------------------------------------------------------------

async function waitForJob(page, jobId, { timeout = 300000, expected = 'completed' } = {}) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    last = await apiGet(page, `/api/jobs/${jobId}`);
    if (TERMINAL_JOB_STATUSES.has(last.status)) break;
    await page.waitForTimeout(2000);
  }
  if (!last) throw new Error(`Job ${jobId}: no response before timeout`);
  if (last.status !== expected) {
    throw new Error(`Job ${jobId} ended '${last.status}' (expected '${expected}'): ${last.error || last.message || ''}`);
  }
  return last;
}

// ---------------------------------------------------------------------------
// Test image generation (pure Node PNG encoder — no canvas dependency)
// ---------------------------------------------------------------------------

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf) {
  let crc = 0xffffffff;
  for (let i = 0; i < buf.length; i++) crc = CRC_TABLE[(crc ^ buf[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const typeBuf = Buffer.from(type, 'ascii');
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])));
  return Buffer.concat([len, typeBuf, data, crcBuf]);
}

function makeTestImage({ width = 64, height = 64, rgb = [90, 140, 220] } = {}) {
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // color type: RGB
  const raw = Buffer.alloc(height * (1 + width * 3));
  for (let y = 0; y < height; y++) {
    const rowStart = y * (1 + width * 3);
    raw[rowStart] = 0; // filter: none
    for (let x = 0; x < width; x++) {
      const off = rowStart + 1 + x * 3;
      raw[off] = rgb[0];
      raw[off + 1] = rgb[1];
      raw[off + 2] = rgb[2];
    }
  }
  const idat = zlib.deflateSync(raw);
  return Buffer.concat([sig, pngChunk('IHDR', ihdr), pngChunk('IDAT', idat), pngChunk('IEND', Buffer.alloc(0))]);
}

function toDataUrl(pngBuffer) {
  return `data:image/png;base64,${pngBuffer.toString('base64')}`;
}

// ---------------------------------------------------------------------------
// Seeding (unique-named entities via API; returns created entity)
// ---------------------------------------------------------------------------

async function seedCharacter(page, overrides = {}) {
  return apiPost(page, '/characters', {
    name: overrides.name || uniqueName('e2e-char'),
    description: overrides.description || 'A test character created by the e2e suite.',
    personality: overrides.personality || 'Friendly and curious.',
    scenario: overrides.scenario || 'A quiet tavern on a rainy night.',
    first_mes: overrides.first_mes || 'Hello, traveler. Care to join me?',
    ...overrides,
  });
}

async function seedLorebook(page, overrides = {}) {
  return apiPost(page, '/lorebooks', {
    name: overrides.name || uniqueName('e2e-lorebook'),
    description: overrides.description || 'A test lorebook created by the e2e suite.',
    ...overrides,
  });
}

async function seedLorebookEntry(page, lorebookId, overrides = {}) {
  return apiPost(page, `/lorebooks/${lorebookId}/entries`, {
    keys: ['testkey'],
    content: 'The test kingdom of E2ELAND is ruled by the Clockwork King.',
    ...overrides,
  });
}

async function seedChat(page, overrides = {}) {
  return apiPost(page, '/chats', {
    name: overrides.name || uniqueName('e2e-chat'),
    persona_name: overrides.persona_name || 'Test User',
    ...overrides,
  });
}

async function seedStory(page, overrides = {}) {
  return apiPost(page, '/stories', {
    title: overrides.title || uniqueName('e2e-story'),
    description: overrides.description || 'A test story created by the e2e suite.',
    genre: overrides.genre || 'Fantasy',
    ...overrides,
  });
}

async function seedStoryChapter(page, storyId, overrides = {}) {
  return apiPost(page, `/stories/${storyId}/chapters`, {
    title: overrides.title || 'Chapter 1',
    // `ChapterCreate.content` is required and `extra="forbid"`, so omitting it
    // made every one of the seven chapter seeds a 422. Nothing in the e2e suite
    // read a chapter's content, which is why no assertion caught it: the helper
    // failed, the spec carried on, and 50 tests failed later on a symptom.
    content: overrides.content || '',
    ...overrides,
  });
}

async function seedChatMessage(page, chatId, overrides = {}) {
  return apiPost(page, `/chats/${chatId}/messages`, {
    role: overrides.role || 'char',
    content: overrides.content || uniqueName('e2e-message'),
    ...overrides,
  });
}

async function seedLocation(page, overrides = {}) {
  return apiPost(page, '/locations', {
    name: overrides.name || uniqueName('e2e-location'),
    description: overrides.description || 'A misty valley where the gates of the test realm open.',
    atmosphere: overrides.atmosphere || 'Misty and quiet.',
    tags: overrides.tags || [],
    ...overrides,
  });
}

async function seedWorld(page, overrides = {}) {
  return apiPost(page, '/worlds', {
    name: overrides.name || uniqueName('e2e-world'),
    description: overrides.description || 'A chronicle of the e2e realm.',
    character_ids: overrides.character_ids || [],
    story_ids: overrides.story_ids || [],
    chat_ids: overrides.chat_ids || [],
    location_ids: overrides.location_ids || [],
    ...overrides,
  });
}

async function seedScenario(page, overrides = {}) {
  return apiPost(page, '/scenarios', {
    name: overrides.name || uniqueName('e2e-scenario'),
    description: overrides.description || 'A test scenario created by the e2e suite.',
    prompt_template: overrides.prompt_template ?? 'You stand at the edge of the E2ELAND, where every choice echoes through the mist.',
    ...overrides,
  });
}

async function seedVoice(page, overrides = {}) {
  return apiPost(page, '/voices', {
    name: overrides.name || uniqueName('e2e-voice'),
    description: overrides.description || 'A test voice model created by the e2e suite.',
    type: overrides.type || 'qwen3_tts',
    voice_profile: overrides.voice_profile ?? 'e2e_speaker',
    language: overrides.language ?? 'en',
    preview_text: overrides.preview_text ?? 'Hello traveler, the e2e suite greets you.',
    ...overrides,
  });
}

async function seedPrompt(page, overrides = {}) {
  const body = {
    name: overrides.name || uniqueName('e2e-prompt'),
    text: overrides.prompt || 'A glowing crystal city at dusk, ultra detailed',
    category: overrides.category || 'Landscape',
    ...overrides,
  };
  delete body.prompt;
  return apiPost(page, '/api/prompts', body);
}

async function seedCollection(page, overrides = {}) {
  return apiPost(page, '/collections', {
    name: overrides.name || uniqueName('e2e-collection'),
    workspace: overrides.workspace || 'main',
    ...overrides,
  });
}

// ---------------------------------------------------------------------------
// Cleanup (delete entities created by the suite)
// ---------------------------------------------------------------------------

// Seed a fabricated metadata-only ModelV2 row (no real files). Uses a fake
// NON-NULL CivitAI id so the backend's duplicate check (get_model_by_civitai_id
// with NULL matches ANY auto-discovered row — the live worker sync registers
// those constantly) always creates a fresh row; SDXL base avoids Flux CLIP/VAE
// dependency downloads. The "Auto-discovered" description keeps the details
// modal banner intact.
async function seedModel(page, overrides = {}) {
  const name = overrides.name || uniqueName('e2e-model');
  const versionId = 1_000_000_000 + Math.floor(Math.random() * 999_999_999);
  const body = {
    civitai_data: {
      id: Math.floor(Math.random() * 999_999) + 1,
      name,
      type: overrides.type || 'LORA',
      description: `Auto-discovered ${name}`,
      nsfw: false,
      creator: { username: 'e2e' },
      stats: { downloads: 0, thumbsUp: 0, thumbsDown: 0, comments: 0 },
      modelVersions: [
        {
          id: versionId,
          name: 'v1.0',
          baseModel: 'SDXL 1.0',
          files: [{ name: `${name.toLowerCase().replace(/[^a-z0-9]+/g, '_')}.safetensors`, sizeKB: 10, primary: true }],
        },
      ],
    },
    selected_versions: [{ version_id: versionId, is_default: true }],
  };
  return apiPost(page, '/models', body);
}

const DELETE_PATHS = {
  chat: (id) => `/chats/${id}`,
  story: (id) => `/stories/${id}`,
  chapter: (id) => `/stories/${id.split(':')[0]}/chapters/${id.split(':')[1]}`,
  character: (id) => `/characters/${id}`,
  lorebook: (id) => `/lorebooks/${id}`,
  collection: (id) => `/collections/${id}`,
  prompt: (id) => `/prompts/${id}`,
  job: (id) => `/jobs/${id}`,
  model: (id) => `/models/${id}`,
  location: (id) => `/locations/${id}`,
  world: (id) => `/worlds/${id}`,
  scenario: (id) => `/scenarios/${id}`,
  voice: (id) => `/voices/${id}`,
  provider: (id) => `/providers/${id}`,
};

async function cleanupEntities(page, entities) {
  const errors = [];
  for (const { kind, id } of entities) {
    const path = DELETE_PATHS[kind]?.(id);
    if (!path) {
      errors.push(`unknown kind '${kind}'`);
      continue;
    }
    try {
      const res = await page.request.delete(resolveApiPath(path));
      if (!res.ok() && res.status() !== 404) errors.push(`${kind} ${id}: HTTP ${res.status()}`);
    } catch (e) {
      errors.push(`${kind} ${id}: ${e.message}`);
    }
  }
  if (errors.length) throw new Error(`Cleanup errors: ${errors.join('; ')}`);
}

testBase.afterEach(async ({ page }) => {
  const tracked = TRACKED_ENTITIES.get(page) || [];
  if (tracked.length) {
    const ordered = [...tracked].sort((a, b) => {
      const aRank = a.kind === 'chapter' ? 0 : 1;
      const bRank = b.kind === 'chapter' ? 0 : 1;
      return aRank - bRank;
    });
    await cleanupEntities(page, ordered);
    TRACKED_ENTITIES.delete(page);
  }
});

// ---------------------------------------------------------------------------
// Misc UI helpers
// ---------------------------------------------------------------------------

async function waitForStreamingToFinish(page) {
  const stopBtn = page.getByRole('button', { name: /stop generating|stop/i }).first();
  if (await stopBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
    await stopBtn.click();
    await page.waitForTimeout(1000);
  }
  await page.waitForTimeout(2000);
}

// Mark onboarding as complete for the next navigation (the first-visit wizard
// overlays the Fantasy Hub and would intercept clicks on its tiles).
async function dismissOnboarding(page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem('tnhfantasy_setup_complete', JSON.stringify(true));
    } catch {
      // Ignore storage errors; the wizard is dismissible anyway.
    }
  });
}

async function closeModal(page) {
  const modal = page.locator('[role="dialog"], [class*="modal"]').first();
  if (await modal.isVisible({ timeout: 1000 }).catch(() => false)) {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
  }
}

// A list card whose root is the flex "justify-between" row (voice models,
// scenarios, and anything else sharing that row layout). Actions are
// title-attributed icon buttons inside the row.
function rowCard(page, name) {
  return page
    .getByText(name, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"justify-between")][1]');
}

// The inline create/edit form of those same pages: a motion.div, not a
// role="dialog".
function inlineForm(page, heading) {
  return page
    .getByRole('heading', { name: heading, exact: true })
    .locator('xpath=ancestor::div[contains(@class,"bg-gray-900")][1]');
}

// Draw a mask on the Inpaint canvas via mouse events.
// The canvas is a native <canvas>; brush radius is ~15px at default zoom.
async function drawMaskOnCanvas(canvas, { from, to, steps = 10 }) {
  const box = await canvas.boundingBox();
  if (!box) throw new Error('Canvas not visible');
  await canvas.hover();
  await canvas.page().mouse.move(box.x + from.x * box.width, box.y + from.y * box.height);
  await canvas.page().mouse.down();
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const x = box.x + (from.x + (to.x - from.x) * t) * box.width;
    const y = box.y + (from.y + (to.y - from.y) * t) * box.height;
    await canvas.page().mouse.move(x, y, { steps: 2 });
  }
  await canvas.page().mouse.up();
}

// rowCard / inlineForm below are the locators that voices.spec.js and
// scenarios.spec.js each carried a byte-identical copy of; clickableCard is
// the clickable-card locator providers.spec.js and batch-generate.spec.js
// each had their own name for.
export {
  API_BASE,
  apiDelete,
  apiGet,
  apiPost,
  apiPut,
  apiPatch,
  apiUpload,
  trackEntity,
  uniqueName,
  expectToast,
  waitForToast,
  waitForJob,
  makeTestImage,
  toDataUrl,
  seedCharacter,
  seedLorebook,
  seedLorebookEntry,
  seedChat,
  seedStory,
  seedStoryChapter,
  seedChatMessage,
  seedLocation,
  seedWorld,
  seedScenario,
  seedVoice,
  seedPrompt,
  seedCollection,
  seedModel,
  cleanupEntities,
  waitForStreamingToFinish,
  dismissOnboarding,
  closeModal,
  drawMaskOnCanvas,
  rowCard,
  inlineForm,
};

// --- Shared e2e helpers (migrated from spec-local copies) -------------------

// /models/discover sort control (DOM order: [source, sort, nsfw, period]).
export function sortSelect(page) {
  return page.locator('select').nth(1);
}

export async function readPersisted(page, key) {
  return page.evaluate((k) => JSON.parse(localStorage.getItem(k) || 'null'), key);
}

// Installed list paginates (~20 items/page); fresh seeds sort LAST alphabetically.
// Sort by date (desc, newest first) so a seeded row lands on the first page.
export async function sortNewestFirst(page) {
  await page.locator('select').first().selectOption('date');
}

// A card that is itself the clickable element: the accessible name of a
// role=button card is its full text content (including the id / preset name).
export function clickableCard(page, name) {
  return page.getByRole('button', { name: new RegExp(name) }).first();
}

// Backwards-compatible alias: the provider list is a list of these.
export const providerCard = clickableCard;

export async function seedProvider(page, id, { enabled = false, priority = 1 } = {}) {
  return apiPost(page, '/providers', {
    id,
    type: 'llm-local',
    worker_type: 'llm',
    enabled,
    priority,
    credentials: { endpoint_url: 'http://127.0.0.1:9' },
    runtime_config: { mode: 'container', port: 8001 },
    deploy_config: { deploy_mode: 'manual' },
  });
}

export async function fetchProvider(page, id) {
  const { providers = [] } = await apiGet(page, '/providers');
  return providers.find((p) => p.id === id) || null;
}

export async function cleanupProvider(page, id) {
  try {
    await apiDelete(page, `/providers/${id}`);
  } catch {
    // Already deleted by the test itself.
  }
}

/**
 * Does this instance have a working backend for `kind`?
 *
 * A permanently-red test is a test people stop running, and then the suite stops
 * being evidence of anything. These tests need a real image worker or a real LLM
 * to talk to; a developer without one configured should get an honest SKIP, not
 * a failure that looks like a regression.
 *
 * Deliberately a *runtime* check against the API rather than a tag: a tag is a
 * promise about the environment made at authoring time, and the environment
 * changes underneath it. `@fullstack` in CI already covers the split for the
 * runner; this covers the developer.
 *
 *   test.beforeEach(async ({ page, requireBackend }) => {
 *     await requireBackend(page, 'llm');
 *   });
 *
 * @param {'image'|'llm'} kind
 */
export async function requireBackend(page, kind) {
  let providers = [];
  try {
    providers = (await apiGet(page, '/providers/'))?.providers || [];
  } catch (err) {
    testBase.skip(true, `Backend unreachable, cannot tell whether an ${kind} worker is configured: ${err.message}`);
    return;
  }

  const wanted = kind === 'llm' ? ['openai_compat', 'anthropic', 'google', 'modal_llm'] : ['modal', 'beam', 'direct_url', 'remote_comfy'];
  const usable = providers.filter((p) => wanted.includes(p.type) && p.enabled);

  if (usable.length === 0) {
    testBase.skip(
      true,
      `No enabled ${kind} provider on this instance (looked for ${wanted.join(', ')} among `
      + `${providers.length} configured). This test needs a real ${kind} backend — it is skipped, not passing.`,
    );
  }
}
