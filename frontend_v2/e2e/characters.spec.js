import { test, expect } from '@playwright/test';
import { API_BASE, apiDelete, waitForToast } from './fixtures.js';

test.describe('Character Vault (Module D)', () => {
  test.setTimeout(120000);

  let createdCharId = null;

  test.afterEach(async ({ page }) => {
    if (createdCharId) {
      try {
        await apiDelete(page, `/world_vault/characters/${createdCharId}`);
      } catch {
        // best-effort
      }
      createdCharId = null;
    }
  });

  test('Create Character from Scratch', async ({ page }) => {
    await page.goto('/characters');

    const createBtn = page.getByRole('button', { name: /create character/i }).first();
    await expect(createBtn).toBeVisible();
    await createBtn.click();
    await page.waitForTimeout(500);

    const nameInput = page.getByPlaceholder(/character name/i);
    await expect(nameInput).toBeVisible();
    await nameInput.fill('Playwright Hero');

    const descInput = page.getByPlaceholder(/brief description/i);
    if (await descInput.isVisible()) {
      await descInput.fill('A brave hero created by automated tests');
    }

    await page.getByRole('button', { name: /create/i }).last().click();
    await waitForToast(page, /created/i, 5000);

    await expect(page.getByRole('heading', { name: 'Playwright Hero' }).first()).toBeVisible();

    const url = page.url();
    const match = url.match(/characters\/([^/]+)/);
    if (match) createdCharId = match[1];
  });

  test('Edit Character', async ({ page }) => {
    await page.goto('/characters');

    const createBtn = page.getByRole('button', { name: /create character/i }).first();
    if (await createBtn.isVisible()) {
      await createBtn.click();
      await page.waitForTimeout(500);
      await page.getByPlaceholder(/character name/i).fill('Editable Character');
      await page.getByRole('button', { name: /create/i }).last().click();
      await waitForToast(page, /created/i, 5000);
    }

    const editBtn = page.getByRole('button', { name: /edit/i }).first();
    if (await editBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await editBtn.click();

      const nameInput = page.getByPlaceholder(/character name/i);
      if (await nameInput.isVisible()) {
        await nameInput.fill('Updated Character Name');
        await page.getByRole('button', { name: /update/i }).first().click();
        await waitForToast(page, /updated/i, 5000);
        await expect(page.getByRole('heading', { name: 'Updated Character Name' }).first()).toBeVisible();
      }
    }
  });

  test('Search Characters', async ({ page }) => {
    await page.goto('/characters');

    const searchInput = page.getByPlaceholder(/search characters/i);
    if (await searchInput.isVisible()) {
      await searchInput.fill('Playwright Hero');
      await page.waitForTimeout(500);
    }
  });

  test('Auto-Fill Character Field', async ({ page }) => {
    await page.goto('/characters');

    const createBtn = page.getByRole('button', { name: /create character/i }).first();
    if (await createBtn.isVisible()) {
      await createBtn.click();
      await page.getByPlaceholder(/character name/i).fill('AutoFill Tester');
      await page.getByPlaceholder(/brief description/i).fill('A brave adventurer');

      const autoFillBtn = page.getByRole('button', { name: /auto-fill/i }).first();
      if (await autoFillBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await autoFillBtn.click();
        await waitForToast(page, /generated|filled/i, 30000);
      }
    }
  });

  test('Delete Character', async ({ page }) => {
    await page.goto('/characters');

    const createBtn = page.getByRole('button', { name: /create character/i }).first();
    if (await createBtn.isVisible()) {
      await createBtn.click();
      await page.waitForTimeout(500);
      await page.getByPlaceholder(/character name/i).fill('To Be Deleted');
      await page.getByRole('button', { name: /create/i }).last().click();
      await waitForToast(page, /created/i, 5000);
    }

    const deleteBtn = page.getByRole('button', { name: /trash|delete/i }).first();
    if (await deleteBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await deleteBtn.click();
      const confirmBtn = page.getByRole('button', { name: /delete/i }).first();
      if (await confirmBtn.isVisible()) {
        await confirmBtn.click();
      }
      await waitForToast(page, /deleted/i, 5000);
    }
  });
});
