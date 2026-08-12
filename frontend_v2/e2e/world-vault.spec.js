import { test, expect } from '@playwright/test';
import { seedLorebook, seedLorebookEntry, cleanupEntities, uniqueName, expectToast } from './fixtures.js';

test.describe('World Vault & Lorebooks (Module D)', () => {
  test.setTimeout(120000);

  const created = [];
  let lorebookName;

  test.afterEach(async ({ page }) => {
    await cleanupEntities(page, created).catch(() => {});
    created.length = 0;
  });

  test('Lorebook toggle appears in Chat context panel', async ({ page }) => {
    lorebookName = uniqueName('e2e-lorebook');
    const lorebook = await seedLorebook(page, { name: lorebookName, description: 'E2E lore for chat context.' });
    created.push({ kind: 'lorebook', id: lorebook.id });

    await page.goto('/chat');
    await expect(page.getByRole('heading', { name: 'Context & Settings' })).toBeVisible({ timeout: 10000 });

    await expect(page.getByText('Lorebooks', { exact: true }).last()).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('button', { name: lorebookName }).first()).toBeVisible({ timeout: 10000 });
  });

  test('Lorebook appears in New Chat modal and can be attached', async ({ page }) => {
    lorebookName = uniqueName('e2e-lorebook');
    const lorebook = await seedLorebook(page, { name: lorebookName, description: 'E2E lore for new chat modal.' });
    created.push({ kind: 'lorebook', id: lorebook.id });

    await page.goto('/chat');
    await page.getByTitle('New chat').click();

    const modal = page.getByRole('heading', { name: 'Create New Chat' }).locator('..').locator('..');
    await expect(modal).toBeVisible({ timeout: 10000 });
    const toggle = modal.getByRole('button', { name: lorebookName });
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

    const list = await (await page.request.get('/api/v2/lorebooks')).json();
    const fromApi = list.find((l) => l.id === lorebook.id);
    expect(fromApi).toBeTruthy();

    await cleanupEntities(page, [{ kind: 'lorebook', id: lorebook.id }]);
    created.length = 0;

    const after = await (await page.request.get('/api/v2/lorebooks')).json();
    expect(after.find((l) => l.id === lorebook.id)).toBeFalsy();
  });
});
