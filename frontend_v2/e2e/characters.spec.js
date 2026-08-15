import { test, expect } from '@playwright/test';
import {
  seedCharacter,
  cleanupEntities,
  uniqueName,
  expectToast,
} from './fixtures.js';

test.describe('Character Vault (Module D)', () => {
  test.setTimeout(120000);

  let created = [];

  test.afterEach(async ({ page }) => {
    await cleanupEntities(page, created.splice(0));
  });

  test('Create Character from Scratch', async ({ page }) => {
    const character = await seedCharacter(page, { name: uniqueName('e2e-char') });
    created.push({ kind: 'character', id: character.id });

    await page.goto('/characters');
    await expect(page.getByRole('heading', { name: character.name }).first()).toBeVisible({ timeout: 10000 });
  });

  test('Edit Character', async ({ page }) => {
    const character = await seedCharacter(page, { name: 'Editable Character' });
    created.push({ kind: 'character', id: character.id });

    await page.goto('/characters');
    await expect(page.getByRole('heading', { name: 'Editable Character' })).toBeVisible({ timeout: 10000 });

    const editBtn = page.getByRole('button', { name: /edit/i }).first();
    await expect(editBtn).toBeVisible({ timeout: 10000 });
    await editBtn.click();

    const nameInput = page.getByPlaceholder(/character name/i);
    await expect(nameInput).toBeVisible();
    await nameInput.fill('Updated Character Name');
    await page.getByRole('button', { name: /update/i }).first().click();
    await expectToast(page, /updated/i, 5000);
    await expect(page.getByRole('heading', { name: 'Updated Character Name' }).first()).toBeVisible();
  });

  test('Search Characters', async ({ page }) => {
    const character = await seedCharacter(page, { name: uniqueName('e2e-char') });
    created.push({ kind: 'character', id: character.id });

    await page.goto('/characters');

    const searchInput = page.getByPlaceholder(/search characters/i);
    await expect(searchInput).toBeVisible({ timeout: 10000 });
    await searchInput.fill(character.name);
    await page.waitForTimeout(500);

    await expect(page.getByRole('heading', { name: character.name })).toBeVisible();
  });

  test('Auto-Fill Character Field', async ({ page }) => {
    const character = await seedCharacter(page, { name: uniqueName('e2e-char') });
    created.push({ kind: 'character', id: character.id });

    await page.goto('/characters');
    await expect(page.getByRole('heading', { name: character.name }).first()).toBeVisible({ timeout: 10000 });

    const editBtn = page.getByRole('button', { name: /edit/i }).first();
    await expect(editBtn).toBeVisible({ timeout: 10000 });
    await editBtn.click();

    const autoFillBtn = page.getByRole('button', { name: /auto-fill/i }).first();
    await expect(autoFillBtn).toBeVisible({ timeout: 10000 });
    await autoFillBtn.click();
    await expectToast(page, /generated|filled/i, 30000);
  });

  test('Delete Character', async ({ page }) => {
    const character = await seedCharacter(page, { name: 'To Be Deleted' });
    created.push({ kind: 'character', id: character.id });

    await page.goto('/characters');
    await expect(page.getByRole('heading', { name: 'To Be Deleted' })).toBeVisible({ timeout: 10000 });

    const deleteBtn = page.getByRole('button', { name: /trash|delete/i }).first();
    await expect(deleteBtn).toBeVisible({ timeout: 10000 });
    await deleteBtn.click();

    const confirmBtn = page.getByRole('button', { name: 'Delete', exact: true });
    await expect(confirmBtn).toBeVisible();
    await confirmBtn.click();
    await expectToast(page, /deleted/i, 5000);
  });
});
