import { test, expect } from '@playwright/test';
import {
  apiGet,
  apiPost,
  uniqueName,
  expectToast,
  seedCharacter,
  seedChat,
  cleanupEntities,
} from './fixtures.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Open a seeded chat by clicking its row in the sidebar, then wait until the
// right-hand context panel has mounted (desktop layout shows it by default).
async function openSeededChat(page, chatName) {
  await page.goto('/chat');
  await page.getByText(chatName, { exact: true }).first().click();
  await expect(page.getByText('Allow image generation', { exact: true })).toBeVisible({ timeout: 15000 });
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe('Chat Workspace Nuances (Module H)', () => {
  test.setTimeout(240000);

  const created = [];
  test.afterEach(async ({ page }) => {
    await cleanupEntities(page, created.splice(0));
  });

  test('Context switches persist via the API', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-switch') });
    created.push({ kind: 'chat', id: chat.id });

    await openSeededChat(page, chat.name);

    const imgRow = page
      .getByText('Allow image generation', { exact: true })
      .locator('..').locator('..');
    const narrationRow = page
      .getByText('Allow narration', { exact: true })
      .locator('..').locator('..');
    const imgSwitch = imgRow.locator('button[role="switch"]');
    const narrationSwitch = narrationRow.locator('button[role="switch"]');

    await expect(imgSwitch).toHaveAttribute('aria-checked', 'true');
    await expect(narrationSwitch).toHaveAttribute('aria-checked', 'true');

    await imgSwitch.click();
    await expect(imgSwitch).toHaveAttribute('aria-checked', 'false');
    await expect
      .poll(async () => (await apiGet(page, `/v2/chats/${chat.id}`)).allow_image_generation, { timeout: 15000 })
      .toBe(false);

    await imgSwitch.click();
    await expect(imgSwitch).toHaveAttribute('aria-checked', 'true');
    await expect
      .poll(async () => (await apiGet(page, `/v2/chats/${chat.id}`)).allow_image_generation, { timeout: 15000 })
      .toBe(true);
  });

  test('System prompt override saves, shows Clear override, and resets', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-override') });
    created.push({ kind: 'chat', id: chat.id });

    await openSeededChat(page, chat.name);

    const panel = page.locator('.glass-panel', { hasText: 'System Prompt' });
    await panel.getByRole('button', { name: 'Chat Prompt', exact: true }).click();

    const overrideText = 'You are the stern warden of the e2e keep.';
    await page.getByPlaceholder('Override everything — write a complete system prompt…').fill(overrideText);
    await page.getByRole('button', { name: 'Save override' }).click();

    await expect(panel.getByRole('button', { name: 'Clear override' })).toBeVisible();
    await expect
      .poll(async () => (await apiGet(page, `/v2/chats/${chat.id}`)).system_prompt_override, { timeout: 15000 })
      .toBe(overrideText);

    await panel.getByRole('button', { name: 'Clear override' }).click();
    await expect(panel.getByRole('button', { name: 'Clear override' })).toBeHidden();
    await expect
      .poll(async () => (await apiGet(page, `/v2/chats/${chat.id}`)).system_prompt_override, { timeout: 15000 })
      .toBeNull();
  });

  test('Auto-title renames the chat through the LLM', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-title') });
    created.push({ kind: 'chat', id: chat.id });

    await openSeededChat(page, chat.name);

    await page.getByRole('button', { name: 'Title', exact: true }).click();
    await expectToast(page, /Title generated!/, 120000);

    await expect
      .poll(async () => (await apiGet(page, `/v2/chats/${chat.id}`)).name, { timeout: 15000 })
      .not.toBe(chat.name);
  });

  test('Scenes gallery opens for a chat linked to a character', async ({ page }) => {
    const character = await seedCharacter(page, { name: uniqueName('e2e-scene-char') });
    expect(character.id, 'created character should expose an id').toBeTruthy();

    // Creating a character auto-creates "{name}'s Gallery" — clean that up too
    const collections = await apiGet(page, '/collections');
    const gallery = collections.collections.find((c) => c.character_id === character.id);
    if (gallery) created.push({ kind: 'collection', id: gallery.id });

    const chat = await seedChat(page, {
      name: uniqueName('e2e-scene-chat'),
      character_id: character.id,
    });

    // Delete chat + collection BEFORE the character (FK constraints)
    created.push({ kind: 'chat', id: chat.id });
    created.push({ kind: 'character', id: character.id });

    await openSeededChat(page, chat.name);

    const scenesBtn = page.getByRole('button', { name: 'View Scenes Gallery' });
    await expect(scenesBtn).toBeVisible();
    await scenesBtn.click();

    const heading = page.getByRole('heading', { name: `${character.name} Scenes` });
    await expect(heading).toBeVisible();

    // The modal close button is an icon-only X beside the heading
    await heading.locator('..').locator('button').click();
    await expect(heading).toBeHidden();
  });

  test('Export chat as Markdown is available once the chat has a message', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-export') });
    created.push({ kind: 'chat', id: chat.id });

    // Seed one user message without triggering an LLM reply
    await apiPost(page, `/v2/chats/${chat.id}/messages`, {
      role: 'user',
      content: 'A single seeded message.',
      no_reply: true,
    });

    await openSeededChat(page, chat.name);

    const exportBtn = page.getByTitle('Export chat as Markdown');
    await expect(exportBtn).toBeVisible();
    await expect(exportBtn).toBeEnabled();
    await expect(page.getByText('A single seeded message.').first()).toBeVisible({ timeout: 15000 });
  });
});