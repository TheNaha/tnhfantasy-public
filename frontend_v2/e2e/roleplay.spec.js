import { test, expect } from '@playwright/test';
import {
  seedChat,
  seedCharacter,
  cleanupEntities,
  uniqueName,
  expectToast,
} from './fixtures.js';

test.describe('Roleplay Workspace (Module B)', () => {
  test.setTimeout(240000);

  let created = [];

  test.afterEach(async ({ page }) => {
    await cleanupEntities(page, created.splice(0));
  });

  test('Create New Chat and Send Message', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    await chatInput.fill('Hello! Introduce yourself briefly.');
    await chatInput.press('Enter');

    const actionBtn = page.getByRole('button', { name: /regenerate|edit/i }).last();
    await expect(actionBtn).toBeVisible({ timeout: 120000 });
  });

  test('Chat Statefulness: Reload Preserves Messages', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    await chatInput.fill('persistence check passed');
    await chatInput.press('Enter');

    await expect(page.getByText('persistence check passed')).toBeVisible({ timeout: 120000 });

    const currentUrl = page.url();
    await page.reload();

    await page.waitForURL(currentUrl, { timeout: 10000 });
    await expect(page.getByText('persistence check passed')).toBeVisible({ timeout: 30000 });
  });

  test('Edit Own Message', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    await chatInput.fill('Original message for editing');
    await chatInput.press('Enter');

    await expect(page.getByText('Original message for editing')).toBeVisible({ timeout: 60000 });

    const editBtn = page.getByRole('button', { name: /edit/i }).first();
    await expect(editBtn).toBeVisible({ timeout: 10000 });
    await editBtn.click();

    const editable = page.locator('[contenteditable="true"], textarea, input[type="text"]').first();
    await expect(editable).toBeVisible();
    await editable.fill('Edited message content');
    await editable.press('Enter');
    await expect(page.getByText('Edited message content')).toBeVisible();
  });

  test('Regenerate Last AI Reply', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    await chatInput.fill('Short response please');
    await chatInput.press('Enter');

    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });

    const regenerateBtn = page.getByRole('button', { name: /regenerate/i }).first();
    await expect(regenerateBtn).toBeVisible({ timeout: 10000 });
    await regenerateBtn.click();
    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });
  });

  test('Slash Commands: /me and /time', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    await chatInput.fill('/me draws a sword');
    await chatInput.press('Enter');
    await expect(page.getByText('draws a sword', { exact: false }).first()).toBeVisible({ timeout: 30000 });

    await expect(chatInput).toBeEnabled({ timeout: 120000 });

    await chatInput.fill('/time Nightfall');
    await page.keyboard.press('Enter');
    await expect(chatInput).toBeEmpty();
  });

  test('Export Chat as Markdown', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    await chatInput.fill('Export test message');
    await chatInput.press('Enter');

    await expect(page.getByText('Export test message')).toBeVisible({ timeout: 60000 });

    const exportBtn = page.getByRole('button', { name: /export|download/i });
    await expect(exportBtn).toBeVisible({ timeout: 10000 });
    await exportBtn.click();
    await expectToast(page, /export/i, 5000);
  });

  test('Chat Rename and Persistence', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    const renameTrigger = page.getByRole('button', { name: /rename|edit/i }).first();
    await expect(renameTrigger).toBeVisible({ timeout: 10000 });
    await renameTrigger.click();

    const nameInput = page.locator('input[value*="New Chat"], input[placeholder*="name" i], input[aria-label*="name" i]').first();
    await expect(nameInput).toBeVisible();
    await nameInput.fill('Renamed Playwright Chat');
    await nameInput.press('Enter');
    await expectToast(page, /renamed|updated/i, 5000);
  });

  test('Delete Chat', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    const deleteBtn = page.getByRole('button', { name: /delete|trash/i }).first();
    await expect(deleteBtn).toBeVisible({ timeout: 10000 });
    await deleteBtn.click();

    const confirmBtn = page.getByRole('button', { name: /delete/i }).first();
    await expect(confirmBtn).toBeVisible();
    await confirmBtn.click();
    await expectToast(page, /deleted/i, 5000);
  });

  test('Agentic Mode Toggle and Illustrate', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    const agenticBtn = page.getByRole('button', { name: /agentic/i });
    await expect(agenticBtn).toBeVisible({ timeout: 10000 });
    await agenticBtn.click();
    await page.waitForTimeout(500);

    await chatInput.fill('Describe a scene: a wizard casting a spell');
    await chatInput.press('Enter');
    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });

    const illustrateBtn = page.getByRole('button', { name: /illustrate/i }).first();
    await expect(illustrateBtn).toBeVisible({ timeout: 10000 });
    await illustrateBtn.click();
    await expectToast(page, /image generated|illustration/i, 120000);
  });

  test('Chat with Character from Vault', async ({ page }) => {
    const character = await seedCharacter(page, { name: uniqueName('e2e-char') });
    created.push({ kind: 'character', id: character.id });

    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    await chatInput.fill('Hello character');
    await chatInput.press('Enter');

    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });
  });

  test('Swipe to alternate AI response', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    await chatInput.fill('Give me a simple greeting.');
    await chatInput.press('Enter');
    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });

    const regenerateBtn = page.getByRole('button', { name: /regenerate/i }).first();
    await expect(regenerateBtn).toBeVisible({ timeout: 10000 });
    await regenerateBtn.click();
    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });

    const prevSwipeBtn = page.getByRole('button', { name: /prev|</i }).first();
    await expect(prevSwipeBtn).toBeVisible({ timeout: 10000 });
    await prevSwipeBtn.click();
    await page.waitForTimeout(500);
  });

  test('Image attachment in Chat', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    const attachBtn = page.getByRole('button', { name: /attach|image/i }).first();
    await expect(attachBtn).toBeVisible({ timeout: 10000 });
    const fileInput = page.locator('input[type="file"]').first();
    await expect(fileInput).toBeVisible();
    await fileInput.setInputFiles({
      name: 'test.png',
      mimeType: 'image/png',
      buffer: Buffer.from(
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512"><rect width="100%" height="100%" fill="#808080"/></svg>'
      ),
    });

    await chatInput.fill('What is in this image?');
    await chatInput.press('Enter');
    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });
  });

  test('Suggest Reply functionality', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    const suggestBtn = page.getByTitle(/Auto-suggest reply/i).first().or(page.getByRole('button', { name: /Suggest reply/i }).first());
    await expect(suggestBtn).toBeVisible({ timeout: 10000 });
    await suggestBtn.click();
    await expect(chatInput).not.toBeEmpty({ timeout: 120000 });
  });

  test('Narrate Mode Toggle', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    const narrateBtn = page.getByTitle(/Narrate/i).first();
    await expect(narrateBtn).toBeVisible({ timeout: 10000 });
    await narrateBtn.click();
    await page.waitForTimeout(500);
    await expect(page.getByText('📖 Narrate')).toBeVisible();

    await chatInput.fill('A dragon attacks!');
    await chatInput.press('Enter');
    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });
  });
});
