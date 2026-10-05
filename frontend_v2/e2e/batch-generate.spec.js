// BatchGenerate: /batch-generate — the Batch Generation Studio.
//
// The page is self-contained: no characters/prompts/collections are consumed
// from the World Vault. It composes 4 prompt variants from a preset and posts
// them to POST /api/generate/batch, then lists the created jobs. Jobs are NOT
// awaited to completion here (4 real image jobs over a live provider would be
// slow); tests assert the created-job UI state and clean the jobs up.

import { test, expect } from '@playwright/test';
import { apiGet, clickableCard, expectToast, trackEntity } from './fixtures.js';

test.describe('Batch Generate Studio', () => {
  test('form renders presets, seed modes and generated prompt rows', async ({ page }) => {
    await page.goto('/batch-generate');

    await expect(page.getByRole('heading', { level: 1, name: 'Batch Generation Studio' })).toBeVisible();
    await expect(page.getByText('Generate character sheets, scene variations, and concept grids')).toBeVisible();

    for (const name of ['Character Sheet', 'Scene Variations', 'Concept Grid']) {
      await expect(clickableCard(page, name)).toBeVisible();
    }

    for (const mode of ['random', 'fixed', 'increment']) {
      await expect(page.getByRole('button', { name: mode, exact: true })).toBeVisible();
    }

    await expect(page.getByText('Generated Prompts', { exact: true })).toBeVisible();
    const rows = page.locator('div.bg-gray-900\\/50');
    await expect(rows.first()).toBeVisible({ timeout: 10000 });

    await expect(page.getByRole('button', { name: /Generate 4 Images/ })).toBeVisible();
  });

  test('character sheet preset resolves the character name into every prompt', async ({ page }) => {
    await page.goto('/batch-generate');

    await clickableCard(page, 'Character Sheet').click();
    const nameInput = page.getByPlaceholder('e.g. Elara Moonwhisper');
    await expect(nameInput).toBeVisible();
    await nameInput.fill('Elara Moonwhisper');

    const rows = page.locator('div.bg-gray-900\\/50');
    await expect(rows.nth(0)).toContainText('portrait of Elara Moonwhisper, front view, neutral expression');
    await expect(rows.nth(1)).toContainText('portrait of Elara Moonwhisper, side profile, neutral expression');
    await expect(rows.nth(3)).toContainText('portrait of Elara Moonwhisper, close-up, detailed face');

    await clickableCard(page, 'Scene Variations').click();
    await expect(page.getByPlaceholder('e.g. Enchanted Forest')).toBeVisible();
    await expect(page.getByPlaceholder('e.g. Elara Moonwhisper')).toHaveCount(0);
  });

  test('fixed and increment seed modes reveal the base seed input', async ({ page }) => {
    await page.goto('/batch-generate');

    const seedInput = page.getByPlaceholder('Base seed');
    await expect(seedInput).toHaveCount(0);

    await page.getByRole('button', { name: 'fixed', exact: true }).click();
    await expect(seedInput).toBeVisible();
    await seedInput.fill('12345');

    await page.getByRole('button', { name: 'increment', exact: true }).click();
    await expect(seedInput).toBeVisible();

    await page.getByRole('button', { name: 'random', exact: true }).click();
    await expect(seedInput).toHaveCount(0);
  });

  test('concept grid preset builds prompts from the base prompt', async ({ page }) => {
    await page.goto('/batch-generate');

    await clickableCard(page, 'Concept Grid').click();
    const textarea = page.getByPlaceholder('e.g. a futuristic cityscape at sunset');
    await expect(textarea).toBeVisible();
    await textarea.fill('a neon cyberpunk market');

    const rows = page.locator('div.bg-gray-900\\/50');
    await expect(rows.nth(0)).toContainText('a neon cyberpunk market, style A');
    await expect(rows.nth(1)).toContainText('a neon cyberpunk market, style B');
    await expect(rows.nth(2)).toContainText('a neon cyberpunk market, style C');
    await expect(rows.nth(3)).toContainText('a neon cyberpunk market, style D');
  });

  test('submitting a batch creates jobs, shows a toast and lists them', async ({ page }) => {
    test.setTimeout(120000);
    await page.goto('/batch-generate');

    await clickableCard(page, 'Concept Grid').click();
    await page.getByPlaceholder('e.g. a futuristic cityscape at sunset').fill('a small e2e test scene');

    const responsePromise = page.waitForResponse(
      (res) => res.url().includes('/api/generate/batch') && res.request().method() === 'POST',
      { timeout: 30000 }
    );
    await page.getByRole('button', { name: /Generate \d+ Images/ }).click();

    const response = await responsePromise;
    const { jobs, count } = await response.json();
    expect(count).toBe(4);
    expect(jobs).toHaveLength(4);
    for (const job of jobs) trackEntity(page, 'job', job.id);

    await expectToast(page, /Created 4 generation jobs/);

    const section = page
      .getByText('Batch Jobs', { exact: true })
      .locator('xpath=ancestor::div[contains(@class,"rounded-xl")][1]');
    await expect(section).toBeVisible({ timeout: 10000 });

    const rows = section.locator('div.space-y-2 > div');
    await expect(rows).toHaveCount(4);
    for (let i = 0; i < 4; i++) {
      // Per-workflow metadata is merged server-side, so each row shows its
      // own prompt instead of the old "Untitled" fallback.
      await expect(rows.nth(i)).not.toContainText('Untitled');
      await expect(rows.nth(i).locator('span').last()).not.toBeEmpty();
    }

    for (const job of jobs) {
      const fetched = await apiGet(page, `/api/jobs/${job.id}`);
      expect(fetched.id).toBe(job.id);
    }
  });
});