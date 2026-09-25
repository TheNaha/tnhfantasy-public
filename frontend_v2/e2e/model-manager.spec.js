// Module F: Model manager — strict UI tests for /models/discover (DiscoverTab)
// and /models/installed (InstalledTab).
//
// Seed strategy: fabricated metadata-only ModelV2 rows (LORA, SDXL 1.0 base →
// never triggers dependency downloads) created via POST /api/v2/models with a
// fake non-null CivitAI id (a null id would FUSE into a real worker-discovered
// row) and an "Auto-discovered" description (details-modal banner). Rows are
// ephemeral and removed via cleanupEntities({ kind: 'model' }). The model ends
// up in models/loras, so tests on the Installed page switch to the "LoRAs"
// category chip and sort newest-first (paginated grid).
//
// Live CivitAI search is deliberately NOT exercised (network-dependent).

import { test, expect } from '@playwright/test';
import {
    apiGet,
    uniqueName,
    expectToast,
    cleanupEntities,
    seedModel,
    sortSelect,
    readPersisted,
    sortNewestFirst,
} from './fixtures.js';

const created = [];

test.afterEach(async ({ page }) => {
  await cleanupEntities(page, created.splice(0));
});

test.describe('Model manager — Discover', () => {
  test('discover page loads with search, source select and URL import', async ({ page }) => {
    await page.goto('/models/discover');

    await expect(page.getByRole('heading', { level: 1, name: 'Discover Models' })).toBeVisible();
    await expect(page.getByText('Search and import models from CivitAI or HuggingFace')).toBeVisible();

    const search = page.getByPlaceholder('Search models...');
    await expect(search).toBeVisible();

    const source = page.locator('select').first();
    await expect(source).toHaveValue('civitai');
    await expect(source.locator('option:checked')).toHaveText('CivitAI');

    const urlInput = page.getByPlaceholder('Paste CivitAI or HuggingFace URL...');
    await expect(urlInput).toBeVisible();
    const importBtn = page.getByLabel('Import model from URL');
    await expect(importBtn).toBeDisabled();
    await urlInput.fill('https://example.com/not-a-model');
    await expect(importBtn).toBeEnabled();
  });

  test('URL import rejects non-CivitAI/HuggingFace URLs with an error toast', async ({ page }) => {
    await page.goto('/models/discover');

    await page.getByPlaceholder('Paste CivitAI or HuggingFace URL...').fill('https://example.com/not-a-model');
    await page.getByLabel('Import model from URL').click();
    await expectToast(page, /URL must be from CivitAI/);
  });

  test('source switch to HuggingFace persists and hides the CivitAI filters', async ({ page }) => {
    await page.goto('/models/discover');

    const source = page.locator('select').first();
    await source.selectOption('huggingface');
    await expect.poll(() => readPersisted(page, 'civitai_discover_source')).toBe('huggingface');
    await expect(page.getByPlaceholder('@username')).toHaveCount(0);

    await source.selectOption('civitai');
    await expect(page.getByPlaceholder('@username')).toBeVisible();
  });

  test('sort filter persists to localStorage and Clear resets filters', async ({ page }) => {
    await page.goto('/models/discover');

    await sortSelect(page).selectOption('Newest');
    await expect.poll(() => readPersisted(page, 'civitai_discover_sort')).toBe('Newest');

    await page.getByRole('button', { name: 'Clear', exact: true }).click();
    await expect.poll(() => readPersisted(page, 'civitai_discover_sort')).toBe('');
  });
});

test.describe('Model manager — Installed', () => {
  test('installed page loads with category chips and toolbar actions', async ({ page }) => {
    await page.goto('/models/installed');

    await expect(page.getByRole('heading', { level: 1, name: 'Installed Models' })).toBeVisible();
    await expect(page.getByText('Manage your locally installed ComfyUI models')).toBeVisible();

    for (const label of ['Checkpoints', 'LoRAs', 'ControlNet', 'LLM']) {
      await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible();
    }

    for (const label of ['Refresh List', 'Batch Autopopulate Models', 'Resync All Metadata', 'Cleanup Orphaned Models']) {
      await expect(page.getByLabel(label)).toBeVisible();
    }
    await expect(page.getByText('Tags (0)', { exact: true })).toBeVisible();
    await expect(page.getByText('Show NSFW')).toBeVisible();
    await expect(page.getByPlaceholder('Search models...')).toBeVisible();
  });

  test('seeded model appears under LoRAs and search narrows the list', async ({ page }) => {
    const seed = await seedModel(page);
    created.push({ kind: 'model', id: seed.id });
    const name = seed.name;

    await page.goto('/models/installed');
    await page.getByRole('button', { name: 'LoRAs', exact: true }).click();
    await sortNewestFirst(page);
    await expect(page.getByTitle(name)).toBeVisible();

    const search = page.getByPlaceholder('Search models...');
    await search.fill(name);
    await expect(page.getByTitle(name)).toBeVisible();

    await search.fill(uniqueName('zzz-nothing'));
    await expect(page.getByText('No models found')).toBeVisible();
  });

  test('card details modal shows auto-discovered banner and closes', async ({ page }) => {
    const seed = await seedModel(page);
    created.push({ kind: 'model', id: seed.id });

    await page.goto('/models/installed');
    await page.getByRole('button', { name: 'LoRAs', exact: true }).click();
    await sortNewestFirst(page);
    await page.getByTitle(seed.name).click();

    await expect(page.getByText('Auto-discovered Model', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Match with CivitAI' }).first()).toBeVisible();
    await expect(page.getByText(/^Filename:/)).toBeVisible();

    await page.getByLabel('Close modal').click();
    await expect(page.getByText('Auto-discovered Model', { exact: true })).toHaveCount(0);
  });

  test('check dependencies action fires for a non-UNET model', async ({ page }) => {
    const seed = await seedModel(page);
    created.push({ kind: 'model', id: seed.id });

    await page.goto('/models/installed');
    await page.getByRole('button', { name: 'LoRAs', exact: true }).click();
    await sortNewestFirst(page);
    await page.getByTitle(seed.name).hover();

    const card = page.getByTitle(seed.name).locator('xpath=ancestor::div[contains(@class,"group relative")][1]');
    await card.getByLabel('Check & Download Dependencies').click();
    await expectToast(page, /Dependencies triggered!/);
  });

  test('delete model via card action with confirmation', async ({ page }) => {
    const seed = await seedModel(page);
    created.push({ kind: 'model', id: seed.id });

    await page.goto('/models/installed');
    await page.getByRole('button', { name: 'LoRAs', exact: true }).click();
    await sortNewestFirst(page);
    await page.getByTitle(seed.name).hover();

    await page.getByLabel(`Delete ${seed.name}`).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Delete Model', { exact: true })).toBeVisible();
    await dialog.getByRole('button', { name: 'Delete', exact: true }).click();

    await expectToast(page, /Deleted .* and synced providers/);
    await expect.poll(() => page.getByTitle(seed.name).count()).toBe(0);

    const all = await apiGet(page, '/models/all');
    expect(all.some((m) => m.name === seed.name), 'model should be gone via API').toBe(false);

    created.splice(created.findIndex((e) => e.id === seed.id), 1);
  });

  test('batch autopopulate modal opens and closes', async ({ page }) => {
    // Pending-models list is fed by worker auto-discovery (null CivitAI-id rows),
    // which is not deterministic in this live-stack environment — assert the
    // modal structure only, not the candidate rows.
    await page.goto('/models/installed');
    await page.getByLabel('Batch Autopopulate Models').click();

    await expect(page.getByText('Batch Autopopulate', { exact: true })).toBeVisible();
    const portal = page
      .getByText('Batch Autopopulate', { exact: true })
      .locator('xpath=ancestor::div[contains(@class,"z-[60]")][1]');
    await expect(portal.getByText(/models remaining|All Caught Up!/)).toBeVisible();

    await portal.getByRole('button', { name: 'Close', exact: true }).click();
    await expect(page.getByText('Batch Autopopulate', { exact: true })).toHaveCount(0);
  });

  test('resync-all modal opens and closes without running', async ({ page }) => {
    await page.goto('/models/installed');

    await page.getByLabel('Resync All Metadata').click();
    await expect(page.getByText('Resync All Metadata', { exact: true })).toBeVisible();
    const portal = page
      .getByText('Resync All Metadata', { exact: true })
      .locator('xpath=ancestor::div[contains(@class,"z-[60]")][1]');
    await expect(portal.getByRole('button', { name: 'Start Resync' })).toBeVisible();

    await portal.getByRole('button', { name: 'Close', exact: true }).click();
    await expect(page.getByText('Resync All Metadata', { exact: true })).toHaveCount(0);
  });

  test('cleanup orphans reports the removed count in its toast', async ({ page }) => {
    await page.goto('/models/installed');

    await page.getByLabel('Cleanup Orphaned Models').click();
    await expectToast(page, /Cleanup complete! Removed \d+ orphaned models\./);
  });
});