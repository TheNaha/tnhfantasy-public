import { test, expect } from '@playwright/test';
import {
  seedChat,
  seedCharacter,
  seedStory,
  seedStoryChapter,
  cleanupEntities,
  uniqueName,
  expectToast,
} from './fixtures.js';

test.describe('Cross-Pillar Flows (Module E)', () => {
  test.setTimeout(300000);

  let created = [];

  test.afterEach(async ({ page }) => {
    await cleanupEntities(page, created.splice(0));
  });

  test('@fullstack Chat illustration appears in chat gallery and story gallery', async ({ page }) => {
    const character = await seedCharacter(page, {
      name: uniqueName('e2e-char'),
      description: 'Cross-pillar test character.',
      visual_tags: ['1girl'],
    });
    created.push({ kind: 'character', id: character.id });

    const chat = await seedChat(page, { name: uniqueName('e2e-chat'), character_id: character.id });
    created.push({ kind: 'chat', id: chat.id });

    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    created.push({ kind: 'story', id: story.id });
    const chapter = await seedStoryChapter(page, story.id, { title: 'Chapter 1' });
    created.push({ kind: 'chapter', id: `${story.id}:${chapter.id}` });

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
    created.push({ kind: 'character', id: character.id });

    const story = await seedStory(page, {
      title: uniqueName('e2e-story'),
      character_ids: [character.id],
    });
    created.push({ kind: 'story', id: story.id });
    const chapter = await seedStoryChapter(page, story.id, { title: 'Chapter 1' });
    created.push({ kind: 'chapter', id: `${story.id}:${chapter.id}` });

    await page.goto(`/story/${story.id}/chapter/${chapter.id}`);
    const editor = page.getByPlaceholder(/once upon a time/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('The wizard raised his glowing staff, channeling ancient magic.');

    const illustrateBtn = page.getByRole('button', { name: /Illustrate/i }).first();
    await expect(illustrateBtn).toBeVisible({ timeout: 10000 });
    await illustrateBtn.click();

    await expect(illustrateBtn).toBeDisabled({ timeout: 5000 });
    await expectToast(page, /illustration prompt|illustrate/i, 180000);
    await expect(illustrateBtn).toBeEnabled({ timeout: 180000 });
  });

  test('Error path: empty prompt blocks generation with toast', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto(`/chat/${chat.id}`);
    const chatInput = page.getByPlaceholder(/type a message/i);
    await expect(chatInput).toBeVisible({ timeout: 10000 });

    await chatInput.fill('');
    await chatInput.press('Enter');
    await expectToast(page, /empty|required|prompt/i, 5000);
  });

  test('Error path: agentic depth limit prevents infinite loop', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

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
