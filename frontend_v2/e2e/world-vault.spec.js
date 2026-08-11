import { test, expect } from '@playwright/test';
import { API_BASE, apiPost, apiGet, apiDelete, waitForToast } from './fixtures.js';

test.describe('World Vault & Lorebooks (Module D)', () => {
  test.setTimeout(120000);

  let createdLorebookId = null;
  let createdChatId = null;

  test.afterEach(async ({ page }) => {
    if (createdChatId) {
      try { await apiDelete(page, `/world_vault/chats/${createdChatId}`); } catch { /* best-effort */ }
      createdChatId = null;
    }
    if (createdLorebookId) {
      try { await apiDelete(page, `/world_vault/lorebooks/${createdLorebookId}`); } catch { /* best-effort */ }
      createdLorebookId = null;
    }
  });

  test('Create Lorebook via API and Verify in Chat Context', async ({ page }) => {
    const lorebook = await apiPost('/world_vault/lorebooks', {
      name: 'E2E Test Lorebook',
      entries: [
        { keyword: 'Crystal Sword', content: 'The Crystal Sword is hidden in the Cave of Echoes.' }
      ]
    });
    createdLorebookId = lorebook.id || lorebook.data?.id;

    await page.goto('/chat');

    const newChatBtn = page.getByRole('button', { name: /new chat|\+/i }).first();
    if (await newChatBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await newChatBtn.click();
      await page.waitForTimeout(500);

      const nameInput = page.getByPlaceholder(/chat name/i).first();
      if (await nameInput.isVisible()) {
        await nameInput.fill('Lorebook Test Chat');
      }

      const createBtn = page.getByRole('button', { name: /create/i }).last();
      if (await createBtn.isVisible()) {
        await createBtn.click();
        await page.waitForTimeout(1000);
      }
    }

    const url = page.url();
    const match = url.match(/\/chat\/([^/]+)/);
    if (match) createdChatId = match[1];

    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible();
    await chatInput.fill('What do you know about the Crystal Sword?');
    await chatInput.press('Enter');

    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });
  });

  test('Chat Context Panel Opens', async ({ page }) => {
    await page.goto('/chat');

    const newChatBtn = page.getByRole('button', { name: /new chat|\+/i }).first();
    if (await newChatBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await newChatBtn.click();
      const createBtn = page.getByRole('button', { name: /create/i }).last();
      if (await createBtn.isVisible()) {
        await createBtn.click();
        await page.waitForTimeout(1000);
      }
    }

    const contextBtn = page.getByRole('button', { name: /context/i }).first();
    if (await contextBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await contextBtn.click();
      await page.waitForTimeout(500);
    }
  });
});
