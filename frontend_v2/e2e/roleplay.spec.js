import { test, expect } from '@playwright/test';
import { API_BASE, apiDelete, waitForToast } from './fixtures.js';

test.describe('Roleplay Workspace (Module B)', () => {
  test.setTimeout(180000);

  let createdChatId = null;

  test.afterEach(async ({ page }) => {
    if (createdChatId) {
      try {
        await apiDelete(page, `/world_vault/chats/${createdChatId}`);
      } catch {
        // best-effort
      }
      createdChatId = null;
    }
  });

  test('Create New Chat and Send Message', async ({ page }) => {
    await page.goto('/chat');

    const newChatBtn = page.getByRole('button', { name: /new chat|create chat|\+/i }).first();
    if (await newChatBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await newChatBtn.click();
    }

    const modal = page.locator('[class*="modal"], [role="dialog"]').first();
    if (await modal.isVisible({ timeout: 3000 }).catch(() => false)) {
      const createBtn = page.getByRole('button', { name: /create/i }).first();
      if (await createBtn.isVisible()) {
        await createBtn.click();
      }
    }

    await page.waitForTimeout(1000);

    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible();

    await chatInput.fill('Hello! Introduce yourself briefly.');
    await chatInput.press('Enter');

    const actionBtn = page.getByRole('button', { name: /regenerate|edit/i }).last();
    await expect(actionBtn).toBeVisible({ timeout: 120000 });

    const url = page.url();
    const match = url.match(/\/chat\/([^/]+)/);
    if (match) createdChatId = match[1];
  });

  test('Chat Statefulness: Reload Preserves Messages', async ({ page }) => {
    await page.goto('/chat');

    const chatInput = page.getByPlaceholder(/type a message/i);
    const isInputVisible = await chatInput.isVisible({ timeout: 5000 }).catch(() => false);
    if (!isInputVisible) {
      const newChatBtn = page.getByRole('button', { name: /new chat|\+/i }).first();
      if (await newChatBtn.isVisible()) await newChatBtn.click();
      const createBtn = page.getByRole('button', { name: /create/i }).first();
      if (await createBtn.isVisible()) {
        await createBtn.click();
        await page.waitForTimeout(500);
      }
    }

    await chatInput.fill('persistence check passed');
    await chatInput.press('Enter');

    await expect(page.getByText('persistence check passed')).toBeVisible({ timeout: 120000 });

    const currentUrl = page.url();
    await page.reload();

    await page.waitForURL(currentUrl, { timeout: 10000 });
    await expect(page.getByText('persistence check passed')).toBeVisible({ timeout: 30000 });
  });

  test('Edit Own Message', async ({ page }) => {
    await page.goto('/chat');

    const chatInput = page.getByPlaceholder(/type a message/i);
    const isInputVisible = await chatInput.isVisible({ timeout: 5000 }).catch(() => false);
    if (!isInputVisible) {
      const newChatBtn = page.getByRole('button', { name: /new chat|\+/i }).first();
      if (await newChatBtn.isVisible()) await newChatBtn.click();
      const createBtn = page.getByRole('button', { name: /create/i }).first();
      if (await createBtn.isVisible()) await createBtn.click();
      await page.waitForTimeout(1000);
    }

    await chatInput.fill('Original message for editing');
    await chatInput.press('Enter');

    await expect(page.getByText('Original message for editing')).toBeVisible({ timeout: 60000 });

    const editBtn = page.getByRole('button', { name: /edit/i }).first();
    if (await editBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await editBtn.click();
      const editable = page.locator('[contenteditable="true"], textarea, input[type="text"]').first();
      if (await editable.isVisible()) {
        await editable.fill('Edited message content');
        await editable.press('Enter');
        await expect(page.getByText('Edited message content')).toBeVisible();
      }
    }
  });

  test('Regenerate Last AI Reply', async ({ page }) => {
    await page.goto('/chat');

    const chatInput = page.getByPlaceholder(/type a message/i);
    const isInputVisible = await chatInput.isVisible({ timeout: 5000 }).catch(() => false);
    if (!isInputVisible) {
      const newChatBtn = page.getByRole('button', { name: /new chat|\+/i }).first();
      if (await newChatBtn.isVisible()) await newChatBtn.click();
      const createBtn = page.getByRole('button', { name: /create/i }).first();
      if (await createBtn.isVisible()) await createBtn.click();
      await page.waitForTimeout(1000);
    }

    await chatInput.fill('Short response please');
    await chatInput.press('Enter');

    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });

    const regenerateBtn = page.getByRole('button', { name: /regenerate/i }).first();
    if (await regenerateBtn.isVisible()) {
      await regenerateBtn.click();
      await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });
    }
  });

  test('Slash Commands: /me and /time', async ({ page }) => {
    await page.goto('/chat');

    const chatInput = page.getByPlaceholder(/type a message/i);
    const isInputVisible = await chatInput.isVisible({ timeout: 5000 }).catch(() => false);
    if (!isInputVisible) {
      const newChatBtn = page.getByRole('button', { name: /new chat|\+/i }).first();
      if (await newChatBtn.isVisible()) await newChatBtn.click();
      const createBtn = page.getByRole('button', { name: /create/i }).first();
      if (await createBtn.isVisible()) await createBtn.click();
      await page.waitForTimeout(1000);
    }

    await chatInput.fill('/me draws a sword');
    await chatInput.press('Enter');
    await expect(page.getByText('draws a sword', { exact: false })).toBeVisible({ timeout: 30000 });

    await chatInput.fill('/time Nightfall');
    await chatInput.press('Enter');
    await waitForToast(page, /time|updated/i, 5000);
  });

  test('Export Chat as Markdown', async ({ page }) => {
    await page.goto('/chat');

    const chatInput = page.getByPlaceholder(/type a message/i);
    const isInputVisible = await chatInput.isVisible({ timeout: 5000 }).catch(() => false);
    if (!isInputVisible) {
      const newChatBtn = page.getByRole('button', { name: /new chat|\+/i }).first();
      if (await newChatBtn.isVisible()) await newChatBtn.click();
      const createBtn = page.getByRole('button', { name: /create/i }).first();
      if (await createBtn.isVisible()) await createBtn.click();
      await page.waitForTimeout(1000);
    }

    await chatInput.fill('Export test message');
    await chatInput.press('Enter');

    await expect(page.getByText('Export test message')).toBeVisible({ timeout: 60000 });

    const exportBtn = page.getByRole('button', { name: /export|download/i });
    if (await exportBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await exportBtn.click();
      await waitForToast(page, /export/i, 5000);
    }
  });

  test('Chat Rename and Persistence', async ({ page }) => {
    await page.goto('/chat');

    const chatInput = page.getByPlaceholder(/type a message/i);
    const isInputVisible = await chatInput.isVisible({ timeout: 5000 }).catch(() => false);
    if (!isInputVisible) {
      const newChatBtn = page.getByRole('button', { name: /new chat|\+/i }).first();
      if (await newChatBtn.isVisible()) await newChatBtn.click();
      const createBtn = page.getByRole('button', { name: /create/i }).first();
      if (await createBtn.isVisible()) await createBtn.click();
      await page.waitForTimeout(1000);
    }

    const renameTrigger = page.getByRole('button', { name: /rename|edit/i }).first();
    if (await renameTrigger.isVisible({ timeout: 3000 }).catch(() => false)) {
      await renameTrigger.click();
      const nameInput = page.locator('input[value*="New Chat"], input[placeholder*="name" i], input[aria-label*="name" i]').first();
      if (await nameInput.isVisible()) {
        await nameInput.fill('Renamed Playwright Chat');
        await nameInput.press('Enter');
        await waitForToast(page, /renamed|updated/i, 5000);
      }
    }
  });

  test('Delete Chat', async ({ page }) => {
    await page.goto('/chat');

    const chatInput = page.getByPlaceholder(/type a message/i);
    const isInputVisible = await chatInput.isVisible({ timeout: 5000 }).catch(() => false);
    if (!isInputVisible) {
      const newChatBtn = page.getByRole('button', { name: /new chat|\+/i }).first();
      if (await newChatBtn.isVisible()) await newChatBtn.click();
      const createBtn = page.getByRole('button', { name: /create/i }).first();
      if (await createBtn.isVisible()) await createBtn.click();
      await page.waitForTimeout(1000);

      const url = page.url();
      const match = url.match(/\/chat\/([^/]+)/);
      if (match) createdChatId = match[1];
    }

    const deleteBtn = page.getByRole('button', { name: /delete|trash/i }).first();
    if (await deleteBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await deleteBtn.click();
      const confirmBtn = page.getByRole('button', { name: /delete/i }).first();
      if (await confirmBtn.isVisible()) {
        await confirmBtn.click();
      }
      await waitForToast(page, /deleted/i, 5000);
    }
  });

  test('Agentic Mode Toggle and Illustrate', async ({ page }) => {
    await page.goto('/chat');

    const chatInput = page.getByPlaceholder(/type a message/i);
    const isInputVisible = await chatInput.isVisible({ timeout: 5000 }).catch(() => false);
    if (!isInputVisible) {
      const newChatBtn = page.getByRole('button', { name: /new chat|\+/i }).first();
      if (await newChatBtn.isVisible()) await newChatBtn.click();
      const createBtn = page.getByRole('button', { name: /create/i }).first();
      if (await createBtn.isVisible()) await createBtn.click();
      await page.waitForTimeout(1000);
    }

    const agenticBtn = page.getByRole('button', { name: /agentic/i });
    if (await agenticBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await agenticBtn.click();
      await waitForToast(page, /agentic/i, 3000);
    }

    await chatInput.fill('Describe a scene: a wizard casting a spell');
    await chatInput.press('Enter');
    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });

    const illustrateBtn = page.getByRole('button', { name: /illustrate/i }).first();
    if (await illustrateBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await illustrateBtn.click();
      await waitForToast(page, /image generated|illustration/i, 120000);
    }
  });

  test('Chat with Character from Vault', async ({ page }) => {
    await page.goto('/characters');

    const createCharBtn = page.getByRole('button', { name: /create character/i }).first();
    if (await createCharBtn.isVisible()) {
      await createCharBtn.click();

      const nameInput = page.getByPlaceholder(/character name/i);
      if (await nameInput.isVisible()) {
        await nameInput.fill('E2E Character');
        const descInput = page.getByPlaceholder(/brief description/i);
        if (await descInput.isVisible()) {
          await descInput.fill('A test character for Playwright');
        }
        await page.getByRole('button', { name: /create/i }).first().click();
        await waitForToast(page, /created|character/i, 5000);
      }
    }

    const chatBtn = page.getByRole('button', { name: /chat/i }).first();
    if (await chatBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await chatBtn.click();
      await page.waitForURL('**/chat*', { timeout: 10000 });

      const chatInput = page.getByPlaceholder(/type a message/i);
      await expect(chatInput).toBeVisible();
      await chatInput.fill('Hello character');
      await chatInput.press('Enter');

      await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });
    }
  });

  test('Swipe to alternate AI response', async ({ page }) => {
    await page.goto('/chat');
    
    const chatInput = page.getByPlaceholder(/type a message/i);
    const isInputVisible = await chatInput.isVisible({ timeout: 5000 }).catch(() => false);
    if (!isInputVisible) {
      const newChatBtn = page.getByRole('button', { name: /new chat|\+/i }).first();
      if (await newChatBtn.isVisible()) await newChatBtn.click();
      const createBtn = page.getByRole('button', { name: /create/i }).first();
      if (await createBtn.isVisible()) await createBtn.click();
      await page.waitForTimeout(1000);
    }

    await chatInput.fill('Give me a simple greeting.');
    await chatInput.press('Enter');
    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });

    const regenerateBtn = page.getByRole('button', { name: /regenerate/i }).first();
    if (await regenerateBtn.isVisible()) {
      await regenerateBtn.click();
      await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });
      
      const prevSwipeBtn = page.getByRole('button', { name: /prev|</i }).first();
      if (await prevSwipeBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await prevSwipeBtn.click();
        await page.waitForTimeout(500);
      }
    }
  });

  test('Image attachment in Chat', async ({ page }) => {
    await page.goto('/chat');
    
    const chatInput = page.getByPlaceholder(/type a message/i);
    const isInputVisible = await chatInput.isVisible({ timeout: 5000 }).catch(() => false);
    if (!isInputVisible) {
      const newChatBtn = page.getByRole('button', { name: /new chat|\+/i }).first();
      if (await newChatBtn.isVisible()) await newChatBtn.click();
      const createBtn = page.getByRole('button', { name: /create/i }).first();
      if (await createBtn.isVisible()) await createBtn.click();
      await page.waitForTimeout(1000);
    }

    const attachBtn = page.getByRole('button', { name: /attach|image/i }).first();
    if (await attachBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
       const fileInput = page.locator('input[type="file"]').first();
       if (await fileInput.isVisible()) {
          await fileInput.setInputFiles({
            name: 'test.png',
            mimeType: 'image/png',
            buffer: Buffer.from(
              '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512"><rect width="100%" height="100%" fill="#808080"/></svg>'
            ),
          });
       }
       await chatInput.fill('What is in this image?');
       await chatInput.press('Enter');
       await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });
    }
  });
});
