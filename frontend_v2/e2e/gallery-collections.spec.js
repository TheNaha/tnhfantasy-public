import { test, expect } from '@playwright/test';
import {
  apiGet,
  expectToast,
  trackEntity,
  uniqueName,
} from './fixtures.js';

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe('Gallery Collections & Favorites (Module I)', () => {
  test.setTimeout(240000);

  test('Collections panel: create, rename, and delete a collection via the UI', async ({ page }) => {
    const collName = uniqueName('e2e-coll');
    const newName = `${collName}-renamed`;

    await page.goto('/gallery');
    await page.getByTitle('Browse collections').click();
    await expect(page.getByRole('heading', { name: 'Collections' })).toBeVisible();

    // Create
    await page.getByLabel('Create new collection').click();
    await expect(page.getByRole('heading', { name: 'Create Collection' })).toBeVisible();
    await page.getByPlaceholder('e.g., Best Portraits, Landscapes...').fill(collName);
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expect(page.getByText(collName, { exact: true }).first()).toBeVisible();

    // Track for cleanup via API (the UI gives us no id)
    const collections = await apiGet(page, '/collections');
    const createdColl = collections.collections.find((c) => c.name === collName);
    expect(createdColl, `created collection '${collName}' should exist via API`).toBeTruthy();
    trackEntity(page, 'collection', createdColl.id);

    // Rename — note: once editing starts the row's name div is replaced by
    // the input, so re-locate the input by its initial value instead.
    const row = page.locator('div.group.relative', { hasText: collName }).first();
    await row.hover();
    await page.getByLabel(`Rename collection ${collName}`).click();
    const renameInput = page.locator(`input[type="text"][value="${collName}"]`);
    await renameInput.fill(newName);
    await page.keyboard.press('Enter');
    await expect(page.getByText(newName, { exact: true }).first()).toBeVisible({ timeout: 15000 });

    // Delete (via confirmation modal)
    const renamedRow = page.locator('div.group.relative', { hasText: newName }).first();
    await renamedRow.hover();
    await page.getByLabel(`Delete collection ${newName}`).click();
    await expect(page.getByText('Delete Collection?')).toBeVisible();
    await page.getByRole('button', { name: 'Delete Collection', exact: true }).click();
    await expect(page.getByText(newName, { exact: true })).toBeHidden({ timeout: 15000 });
  });

  test('Favorites filter shows only favorited images', async ({ page }) => {
    await page.goto('/gallery');
    const firstCard = page.locator('[role="img"]').first();
    await firstCard.waitFor({ state: 'visible', timeout: 30000 });

    // Ensure the first card is favorited before filtering
    const star = firstCard.getByRole('button', { name: /Add to favorites|Remove from favorites/ });
    await star.click();
    await expectToast(page, /Added to favorites|Removed from favorites/);
    const pressed = (await star.getAttribute('aria-pressed')) === 'true';
    if (!pressed) {
      await star.click();
      await expectToast(page, /Added to favorites/);
    }

    // Filter to favorites only
    await page.getByTitle('Show Favorites Only').click();
    await expect(page.locator('[role="img"]').first()).toBeVisible({ timeout: 30000 });

    // Back to all
    await page.getByTitle('Show All Images').click();
    await expect(page.locator('[role="img"]').first()).toBeVisible({ timeout: 30000 });
  });
});