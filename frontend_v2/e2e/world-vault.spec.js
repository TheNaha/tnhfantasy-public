import { test, expect } from '@playwright/test';
import {
  seedLorebook,
  seedLorebookEntry,
  seedCharacter,
  cleanupEntities,
  uniqueName,
  expectToast,
  apiGet,
  apiDelete,
} from './fixtures.js';

test.describe('World Vault & Lorebooks (Module D)', () => {
  test.setTimeout(120000);

  let created = [];

  test.afterEach(async ({ page }) => {
    await cleanupEntities(page, created.splice(0));
  });

  test('Lorebook toggle appears in Chat context panel', async ({ page }) => {
    const lorebook = await seedLorebook(page, { name: uniqueName('e2e-lorebook'), description: 'E2E lore for chat context.' });
    created.push({ kind: 'lorebook', id: lorebook.id });

    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    await expect(page.getByRole('heading', { name: 'Context & Settings' })).toBeVisible({ timeout: 10000 });

    await expect(page.getByText('Lorebooks', { exact: true }).last()).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('button', { name: lorebook.name }).first()).toBeVisible({ timeout: 10000 });
  });

  test('Lorebook appears in New Chat modal and can be attached', async ({ page }) => {
    const lorebook = await seedLorebook(page, { name: uniqueName('e2e-lorebook'), description: 'E2E lore for new chat modal.' });
    created.push({ kind: 'lorebook', id: lorebook.id });

    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    await page.getByTitle('New chat').click();

    const modal = page.getByRole('heading', { name: 'Create New Chat' }).locator('..').locator('..');
    await expect(modal).toBeVisible({ timeout: 10000 });
    const toggle = modal.getByRole('button', { name: lorebook.name });
    await expect(toggle).toBeVisible({ timeout: 10000 });
    await toggle.click();

    const createResp = page.waitForResponse(
      (r) => r.request().method() === 'POST' && r.url().includes('/api/v2/chats'),
    );
    await modal.getByRole('button', { name: 'Create', exact: true }).click();

    const createdChat = await (await createResp).json();
    created.push({ kind: 'chat', id: createdChat.id });

    await expectToast(page, /New chat created/);
    expect(createdChat.active_lorebook_ids).toContain(lorebook.id);
  });

  test('Lorebook entry can be created and deleted via API', async ({ page }) => {
    const lorebook = await seedLorebook(page, { name: uniqueName('e2e-lorebook') });
    created.push({ kind: 'lorebook', id: lorebook.id });

    const entry = await seedLorebookEntry(page, lorebook.id, {
      keys: ['Crystal Sword'],
      content: 'The Crystal Sword is hidden in the Cave of Echoes.',
    });
    expect(entry.id).toBeTruthy();

    const list = await apiGet(page, '/v2/lorebooks');
    const fromApi = list.find((l) => l.id === lorebook.id);
    expect(fromApi).toBeTruthy();

    await cleanupEntities(page, [{ kind: 'lorebook', id: lorebook.id }]);
    created.length = 0;

    const after = await apiGet(page, '/v2/lorebooks');
    expect(after.find((l) => l.id === lorebook.id)).toBeFalsy();
  });

  test('Character CRUD via API and UI list', async ({ page }) => {
    const character = await seedCharacter(page, { name: uniqueName('e2e-char') });
    created.push({ kind: 'character', id: character.id });

    await page.goto('/characters');
    await expect(page.getByRole('heading', { name: character.name })).toBeVisible({ timeout: 10000 });

    const editBtn = page.getByRole('button', { name: /edit/i }).first();
    await expect(editBtn).toBeVisible({ timeout: 10000 });
    await editBtn.click();

    const nameInput = page.getByPlaceholder(/character name/i);
    await expect(nameInput).toBeVisible();
    await nameInput.fill('Updated Character Name');
    await page.getByRole('button', { name: /update/i }).first().click();
    await expectToast(page, /updated/i, 5000);
    await expect(page.getByRole('heading', { name: 'Updated Character Name' })).toBeVisible();
  });
});
