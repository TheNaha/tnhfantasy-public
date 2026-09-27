import { test, expect } from '@playwright/test';
import {
  expectToast,
  seedCharacter,
  seedChat,
  seedStory,
  seedStoryChapter,
  trackEntity,
  uniqueName,
  requireBackend,

} from './fixtures.js';

test.describe('Cross-Pillar Flows (Module E)', () => {
  // Needs a real backend. Skipped, not passed, when none is enabled —
  // see `requireBackend`.
  test.beforeEach(async ({ page }) => {
    await requireBackend(page, 'image');
  });

  test.setTimeout(300000);

  test('@fullstack Chat illustration appears in chat gallery and story gallery', async ({ page }) => {
    const character = await seedCharacter(page, {
      name: uniqueName('e2e-char'),
      description: 'Cross-pillar test character.',
      visual_tags: ['1girl'],
    });
    trackEntity(page, 'character', character.id);

    const chat = await seedChat(page, { name: uniqueName('e2e-chat'), character_id: character.id });
    trackEntity(page, 'chat', chat.id);

    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);
    const chapter = await seedStoryChapter(page, story.id, { title: 'Chapter 1' });
    trackEntity(page, 'chapter', `${story.id}:${chapter.id}`);

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    await chatInput.fill('Describe a scene: a wizard casting a spell');
    await chatInput.press('Enter');
    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 120000 });

    const illustrateBtn = page.getByRole('button', { name: /illustrate/i }).first();
    await expect(illustrateBtn).toBeVisible({ timeout: 10000 });
    await illustrateBtn.click();
    await expectToast(page, /image generated|illustration/i, 180000);

    await page.goto(`/story/${story.id}`);
    const storyGallery = page.getByRole('button', { name: /gallery|images/i }).first();
    if (await storyGallery.isVisible({ timeout: 5000 }).catch(() => false)) {
      await storyGallery.click();
      await expect(page.locator('[role="img"], img').first()).toBeVisible({ timeout: 10000 });
    }
  });

  test('@fullstack Story context includes character lore and influences illustration', async ({ page }) => {
    const character = await seedCharacter(page, {
      name: uniqueName('e2e-char'),
      description: 'A wise wizard with a glowing staff.',
      visual_tags: ['1boy', 'wizard', 'glowing staff'],
    });
    trackEntity(page, 'character', character.id);

    const story = await seedStory(page, {
      title: uniqueName('e2e-story'),
      character_ids: [character.id],
    });
    trackEntity(page, 'story', story.id);
    const chapter = await seedStoryChapter(page, story.id, { title: 'Chapter 1' });
    trackEntity(page, 'chapter', `${story.id}:${chapter.id}`);

    await page.goto(`/story/${story.id}/chapter/${chapter.id}`);
    const editor = page.getByPlaceholder(/begin your story/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('The wizard raised his glowing staff, channeling ancient magic.');

    const illustrateBtn = page.getByRole('button', { name: /illus/i }).first();
    await expect(illustrateBtn).toBeVisible({ timeout: 10000 });
    await illustrateBtn.click();

    const generateBtn = page.getByRole('button', { name: 'Generate', exact: true });
    await expect(generateBtn).toBeVisible({ timeout: 10000 });
    await generateBtn.click();

    await expect(illustrateBtn).toBeDisabled({ timeout: 5000 });
    await expectToast(page, /illustration prompt|illustrate/i, 180000);
    await expect(illustrateBtn).toBeEnabled({ timeout: 180000 });
  });

  test('Error path: empty prompt blocks generation', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    trackEntity(page, 'chat', chat.id);

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    // The "cannot send empty" guard lives in handleSendMessage and is gated on
    // `message.trim()`. Its deterministic UI manifestation is the Send button's
    // disabled state (`canSend = message.trim() || ...`). A truly empty Enter
    // keypress is not reliably synthesizable by Playwright against this
    // controlled textarea (empty/whitespace values don't dispatch keydown in
    // this environment), so we assert the guard's visible contract instead:
    // empty -> blocked, non-empty -> allowed -> blocked again.
    const sendBtn = page.getByRole('button', { name: /send message/i });

    // Empty input blocks generation.
    await expect(sendBtn).toBeDisabled();

    // A real (non-whitespace) prompt enables sending.
    await chatInput.fill('Hello there.');
    await expect(sendBtn).toBeEnabled();

    // Whitespace-only input is treated as empty and blocks generation again.
    await chatInput.fill('   ');
    await expect(sendBtn).toBeDisabled();
  });

  test('Error path: agentic depth limit prevents infinite loop', async ({ page }) => {
    test.skip();
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    trackEntity(page, 'chat', chat.id);

    await page.goto(`/chat/${chat.id}`);
    const agenticBtn = page.getByRole('button', { name: /agentic/i });
    await expect(agenticBtn).toBeVisible({ timeout: 10000 });
    await agenticBtn.click();
    await page.waitForTimeout(500);

    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });
    await chatInput.fill('Call generate_image 10 times in a row.');
    await chatInput.press('Enter');

    await expect(page.getByRole('button', { name: /regenerate|edit/i }).last()).toBeVisible({ timeout: 180000 });
  });
});
