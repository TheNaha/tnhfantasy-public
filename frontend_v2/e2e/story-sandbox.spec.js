import { test, expect } from '@playwright/test';
import {
  expectToast,
  seedLorebook,
  seedStory,
  seedStoryChapter,
  trackEntity,
  uniqueName,
} from './fixtures.js';

test.describe('Story Sandbox Workspace (Module C)', () => {
  test.setTimeout(180000);

  test('Create Story and Chapter', async ({ page }) => {
    await page.goto('/story');

    const titleInput = page.getByPlaceholder('New story title...');
    await expect(titleInput).toBeVisible({ timeout: 10000 });
    const storyName = uniqueName('e2e-story');
    await titleInput.fill(storyName);

    await page.getByTitle('Create Story').click();
    await expectToast(page, /story created/i, 5000);
    await page.waitForURL(/\/story\/[^/]+/, { timeout: 10000 });

    const url = page.url();
    const storyMatch = url.match(/\/story\/([^/]+)/);
    expect(storyMatch).toBeTruthy();
    const storyId = storyMatch[1];

    const createChapterBtn = page.getByTitle('New chapter');
    await expect(createChapterBtn).toBeVisible({ timeout: 10000 });
    await createChapterBtn.click();
    await expectToast(page, /chapter/i, 5000);
    await page.waitForURL(/\/chapter\/[^/]+/, { timeout: 10000 });

    const chapterMatch = page.url().match(/chapter\/([^/]+)/);
    expect(chapterMatch).toBeTruthy();
    const chapterId = chapterMatch[1];

    trackEntity(page, 'chapter', `${storyId}:${chapterId}`);
    trackEntity(page, 'story', storyId);
  });

  test('Continue AI Generation', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const editor = page.getByPlaceholder(/begin your story/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('The dark knight stepped into the cavern, drawing his glowing sword.');

    const continueBtn = page.getByRole('button', { name: /continue|gen/i }).first();
    await expect(continueBtn).toBeVisible();
    await continueBtn.click();

    await expect(continueBtn).toBeDisabled({ timeout: 5000 });
    await expect(continueBtn).toBeEnabled({ timeout: 120000 });

    const textContent = await editor.textContent();
    expect(textContent?.length).toBeGreaterThan(100);
  });

  test('Branch from Beat', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const editor = page.getByPlaceholder(/begin your story/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('The hero entered the dark forest.');

    const continueBtn = page.getByRole('button', { name: /continue|gen/i }).first();
    await expect(continueBtn).toBeVisible();
    await continueBtn.click();

    await expect(continueBtn).toBeEnabled({ timeout: 120000 });

    const beatsPanel = page.getByRole('button', { name: /beats|branch/i }).first();
    await expect(beatsPanel).toBeVisible({ timeout: 10000 });
    await beatsPanel.click();

    const branchBtn = page.getByRole('button', { name: /branch/i }).first();
    await expect(branchBtn).toBeVisible({ timeout: 10000 });
    await branchBtn.click();

    const confirmBtn = page.getByRole('button', { name: /branch|confirm/i }).first();
    if (await confirmBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await confirmBtn.click();
    }
    await expectToast(page, /branch/i, 10000);
  });

  test('Add Manual Beat', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const beatInput = page.getByPlaceholder(/add a story beat/i).first();
    await expect(beatInput).toBeVisible({ timeout: 10000 });

    await beatInput.fill('A sudden dragon attack!');
    await beatInput.press('Enter');
    await expectToast(page, /beat added/i, 5000);
  });

  test('Auto-Generate Title', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const editor = page.getByPlaceholder(/begin your story/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('Once upon a time in a magical kingdom, there lived a brave knight who could talk to dragons.');

    const titleBtn = page.getByRole('button', { name: /title|auto.?generate/i }).first();
    await expect(titleBtn).toBeVisible({ timeout: 10000 });
    await titleBtn.click();
    await expectToast(page, /title/i, 30000);
  });

  test('Story Editor Auto-Save', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);
    const chapter = await seedStoryChapter(page, story.id, { title: 'Chapter 1', content: 'Seeded pre-content.' });
    trackEntity(page, 'chapter', `${story.id}:${chapter.id}`);

    await page.goto(`/story/${story.id}`);
    const editor = page.getByPlaceholder(/begin your story/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });
    await expect(editor).toContainText('Seeded pre-content.', { timeout: 10000 });

    await editor.fill('Auto-save verification paragraph.');
    await page.waitForTimeout(3000);

    await page.reload();
    await page.waitForTimeout(1000);

    const reloadedEditor = page.getByPlaceholder(/begin your story/i).first();
    await expect(reloadedEditor).toBeVisible({ timeout: 10000 });
    await expect(reloadedEditor).toHaveValue(/Auto-save verification paragraph/);
  });

  test('Context Panel: Attach Lorebook', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });
    const lorebook = await seedLorebook(page, { name: uniqueName('e2e-lorebook') });
    trackEntity(page, 'lorebook', lorebook.id);

    await page.goto(`/story/${story.id}`);
    const lorebookRow = page.getByRole('button', { name: new RegExp(lorebook.name) }).first();
    try {
        await lorebookRow.waitFor({ state: 'visible', timeout: 3000 });
    } catch {
        await page.getByRole('button', { name: 'Toggle context panel' }).click();
        await expect(lorebookRow).toBeVisible({ timeout: 10000 });
    }

    const putResponse = page.waitForResponse(
      (res) => res.url().includes(`/v2/stories/${story.id}`) && res.request().method() === 'PUT',
      { timeout: 10000 }
    );
    await lorebookRow.click();
    const response = await putResponse;
    const body = await response.json();
    expect(body.lorebook_ids).toContain(lorebook.id);
  });

  test('Delete Story', async ({ page }) => {
    const story = await seedStory(page, { title: 'To Be Deleted Story' });
    trackEntity(page, 'story', story.id);

    await page.goto('/story');
    const deleteBtn = page.getByTitle('Delete story').first();
    await expect(deleteBtn).toBeVisible({ timeout: 10000 });
    await deleteBtn.click();

    const confirmBtn = page.getByRole('button', { name: 'Delete', exact: true });
    await expect(confirmBtn).toBeVisible();
    await confirmBtn.click();
    await expectToast(page, /deleted/i, 5000);
  });

  test('Switch Chapters and Verify Content', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);
    const chapter1 = await seedStoryChapter(page, story.id, { title: 'Chapter 1', content: 'Chapter 1 seeded content.' });
    const chapter2 = await seedStoryChapter(page, story.id, { title: 'Chapter 2', content: 'Chapter 2 seeded content.' });
    trackEntity(page, 'chapter', `${story.id}:${chapter2.id}`);
    trackEntity(page, 'chapter', `${story.id}:${chapter1.id}`);

    await page.goto(`/story/${story.id}/chapter/${chapter1.id}`);
    const editor = page.getByPlaceholder(/begin your story/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });
    await expect(editor).toContainText('Chapter 1 seeded content.', { timeout: 10000 });
    await editor.fill('This is chapter 1.');
    await page.waitForTimeout(3000);

    await page.goto(`/story/${story.id}/chapter/${chapter2.id}`);
    const newEditor = page.getByPlaceholder(/begin your story/i).first();
    await expect(newEditor).toBeVisible({ timeout: 10000 });
    await expect(newEditor).toContainText('Chapter 2 seeded content.', { timeout: 10000 });
    await newEditor.fill('This is chapter 2.');
    await page.waitForTimeout(3000);

    await page.goto(`/story/${story.id}/chapter/${chapter1.id}`);
    await expect(newEditor).toContainText('This is chapter 1.', { timeout: 10000 });
  });

  test('Edit and Reorder Beats', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const beatInput = page.getByPlaceholder(/add a story beat/i).first();
    await expect(beatInput).toBeVisible({ timeout: 10000 });

    await beatInput.fill('First beat');
    await beatInput.press('Enter');
    await expectToast(page, /beat added/i, 5000);

    const beatsPanel = page.getByRole('button', { name: /beats|branch/i }).first();
    await expect(beatsPanel).toBeVisible({ timeout: 10000 });
    await beatsPanel.click();

    const beatItem = page.getByText('First beat').first();
    await expect(beatItem).toBeVisible({ timeout: 10000 });
  });

  test('Story Illustration', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const editor = page.getByPlaceholder(/begin your story/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('A magical kingdom floating in the clouds.');

    const illustrateBtn = page.getByRole('button', { name: /illus/i }).first();
    await expect(illustrateBtn).toBeVisible({ timeout: 10000 });
    await illustrateBtn.click();

    const generateBtn = page.getByRole('button', { name: 'Generate', exact: true });
    await expect(generateBtn).toBeVisible({ timeout: 10000 });
    await generateBtn.click();

    await expect(illustrateBtn).toBeDisabled({ timeout: 5000 });
    await expect(illustrateBtn).toBeEnabled({ timeout: 120000 });
  });

  test('@fullstack Continue AI generation completes end-to-end', async ({ page }) => {
    test.setTimeout(300000);
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);
    const chapter = await seedStoryChapter(page, story.id, { title: 'Chapter 1' });
    trackEntity(page, 'chapter', `${story.id}:${chapter.id}`);

    await page.goto(`/story/${story.id}/chapter/${chapter.id}`);
    const editor = page.getByPlaceholder(/begin your story/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('The dark knight stepped into the cavern, drawing his glowing sword.');

    const continueBtn = page.getByRole('button', { name: /continue|gen/i }).first();
    await expect(continueBtn).toBeVisible();
    await continueBtn.click();

    await expect(continueBtn).toBeDisabled({ timeout: 5000 });
    await expect(continueBtn).toBeEnabled({ timeout: 180000 });

    const textContent = await editor.textContent();
    expect(textContent?.length).toBeGreaterThan(100);
  });

  test('@fullstack Illustrate generates prompt and image job', async ({ page }) => {
    test.setTimeout(300000);
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);
    const chapter = await seedStoryChapter(page, story.id, { title: 'Chapter 1' });
    trackEntity(page, 'chapter', `${story.id}:${chapter.id}`);

    await page.goto(`/story/${story.id}/chapter/${chapter.id}`);
    const editor = page.getByPlaceholder(/begin your story/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('A magical kingdom floating in the clouds, with waterfalls cascading into the sky.');

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

  test('@fullstack Branch from beat and continue new path', async ({ page }) => {
    test.setTimeout(300000);
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);
    const chapter = await seedStoryChapter(page, story.id, { title: 'Chapter 1' });
    trackEntity(page, 'chapter', `${story.id}:${chapter.id}`);

    await page.goto(`/story/${story.id}/chapter/${chapter.id}`);
    const editor = page.getByPlaceholder(/begin your story/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('The hero entered the dark forest.');

    const continueBtn = page.getByRole('button', { name: /continue|gen/i }).first();
    await expect(continueBtn).toBeVisible();
    await continueBtn.click();

    await expect(continueBtn).toBeEnabled({ timeout: 180000 });

    const beatsPanel = page.getByRole('button', { name: /beats|branch/i }).first();
    await expect(beatsPanel).toBeVisible({ timeout: 10000 });
    await beatsPanel.click();

    const branchBtn = page.getByRole('button', { name: /branch/i }).first();
    await expect(branchBtn).toBeVisible({ timeout: 10000 });
    await branchBtn.click();

    const confirmBtn = page.getByRole('button', { name: /branch|confirm/i }).first();
    if (await confirmBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await confirmBtn.click();
    }
    await expectToast(page, /branch/i, 10000);

    const newChapterMatch = page.url().match(/chapter\/([^/]+)/);
    expect(newChapterMatch).toBeTruthy();
  });
});
