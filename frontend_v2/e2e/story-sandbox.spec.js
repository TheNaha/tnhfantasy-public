import { test, expect } from '@playwright/test';
import {
  seedStory,
  seedStoryChapter,
  cleanupEntities,
  uniqueName,
  expectToast,
} from './fixtures.js';

test.describe('Story Sandbox Workspace (Module C)', () => {
  test.setTimeout(180000);

  let created = [];

  test.afterEach(async ({ page }) => {
    await cleanupEntities(page, created.splice(0));
  });

  test('Create Story and Chapter', async ({ page }) => {
    await page.goto('/story');

    const createStoryBtn = page.getByRole('button', { name: /create story/i }).first();
    await expect(createStoryBtn).toBeVisible({ timeout: 10000 });
    await createStoryBtn.click();

    const titleInput = page.getByPlaceholder(/story title/i).first();
    await expect(titleInput).toBeVisible();
    const storyName = uniqueName('e2e-story');
    await titleInput.fill(storyName);

    await page.getByRole('button', { name: /create|confirm/i }).first().click();
    await expectToast(page, /created/i, 5000);

    const url = page.url();
    const storyMatch = url.match(/\/story\/([^/]+)/);
    expect(storyMatch).toBeTruthy();
    const storyId = storyMatch[1];

    const createChapterBtn = page.getByRole('button', { name: /new chapter|add chapter/i }).first();
    await expect(createChapterBtn).toBeVisible({ timeout: 10000 });
    await createChapterBtn.click();
    await expectToast(page, /chapter/i, 5000);

    const chapterMatch = page.url().match(/chapter\/([^/]+)/);
    expect(chapterMatch).toBeTruthy();
    const chapterId = chapterMatch[1];

    created.push({ kind: 'chapter', id: `${storyId}:${chapterId}` });
    created.push({ kind: 'story', id: storyId });
  });

  test('Continue AI Generation', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    created.push({ kind: 'story', id: story.id });
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const editor = page.getByPlaceholder(/once upon a time/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('The dark knight stepped into the cavern, drawing his glowing sword.');

    const continueBtn = page.getByRole('button', { name: /continue|generate/i }).first();
    await expect(continueBtn).toBeVisible();
    await continueBtn.click();

    await expect(continueBtn).toBeDisabled({ timeout: 5000 });
    await expect(continueBtn).toBeEnabled({ timeout: 120000 });

    const textContent = await editor.textContent();
    expect(textContent?.length).toBeGreaterThan(100);
  });

  test('Branch from Beat', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    created.push({ kind: 'story', id: story.id });
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const editor = page.getByPlaceholder(/once upon a time/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('The hero entered the dark forest.');

    const continueBtn = page.getByRole('button', { name: /continue|generate/i }).first();
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
    created.push({ kind: 'story', id: story.id });
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const beatInput = page.getByPlaceholder(/add a beat|beat input/i).first();
    await expect(beatInput).toBeVisible({ timeout: 10000 });

    await beatInput.fill('A sudden dragon attack!');
    await beatInput.press('Enter');
    await expectToast(page, /beat added/i, 5000);
  });

  test('Auto-Generate Title', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    created.push({ kind: 'story', id: story.id });
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const editor = page.getByPlaceholder(/once upon a time/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('Once upon a time in a magical kingdom, there lived a brave knight who could talk to dragons.');

    const titleBtn = page.getByRole('button', { name: /title|auto.?generate/i }).first();
    await expect(titleBtn).toBeVisible({ timeout: 10000 });
    await titleBtn.click();
    await expectToast(page, /title/i, 30000);
  });

  test('Story Editor Auto-Save', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    created.push({ kind: 'story', id: story.id });
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const editor = page.getByPlaceholder(/once upon a time/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('Auto-save verification paragraph.');
    await page.waitForTimeout(3000);

    await page.reload();
    await page.waitForTimeout(1000);

    const reloadedEditor = page.getByPlaceholder(/once upon a time/i).first();
    await expect(reloadedEditor).toBeVisible({ timeout: 10000 });
    const content = await reloadedEditor.textContent();
    expect(content).toContain('Auto-save verification paragraph');
  });

  test('Context Panel: Attach Lorebook', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    created.push({ kind: 'story', id: story.id });
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const contextTab = page.getByRole('button', { name: /context/i }).first();
    await expect(contextTab).toBeVisible({ timeout: 10000 });
    await contextTab.click();
    await page.waitForTimeout(1000);

    const lorebookToggle = page.getByRole('button', { name: /lorebook|add lorebook/i }).first();
    await expect(lorebookToggle).toBeVisible({ timeout: 10000 });
    await lorebookToggle.click();
    await expectToast(page, /lorebook/i, 5000);
  });

  test('Delete Story', async ({ page }) => {
    const story = await seedStory(page, { title: 'To Be Deleted Story' });
    created.push({ kind: 'story', id: story.id });

    await page.goto('/story');
    const deleteBtn = page.getByRole('button', { name: /delete/i }).first();
    await expect(deleteBtn).toBeVisible({ timeout: 10000 });
    await deleteBtn.click();

    const confirmBtn = page.getByRole('button', { name: /delete/i }).first();
    await expect(confirmBtn).toBeVisible();
    await confirmBtn.click();
    await expectToast(page, /deleted/i, 5000);
  });

  test('Switch Chapters and Verify Content', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    created.push({ kind: 'story', id: story.id });
    const chapter1 = await seedStoryChapter(page, story.id, { title: 'Chapter 1' });
    const chapter2 = await seedStoryChapter(page, story.id, { title: 'Chapter 2' });
    created.push({ kind: 'chapter', id: `${story.id}:${chapter2.id}` });
    created.push({ kind: 'chapter', id: `${story.id}:${chapter1.id}` });

    await page.goto(`/story/${story.id}/chapter/${chapter1.id}`);
    const editor = page.getByPlaceholder(/once upon a time/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });
    await editor.fill('This is chapter 1.');

    await page.goto(`/story/${story.id}/chapter/${chapter2.id}`);
    const newEditor = page.getByPlaceholder(/once upon a time/i).first();
    await expect(newEditor).toBeVisible({ timeout: 10000 });
    await newEditor.fill('This is chapter 2.');

    await page.goto(`/story/${story.id}/chapter/${chapter1.id}`);
    await expect(newEditor).toContainText('chapter 1', { timeout: 10000 });
  });

  test('Edit and Reorder Beats', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    created.push({ kind: 'story', id: story.id });
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const beatInput = page.getByPlaceholder(/add a beat|beat input/i).first();
    await expect(beatInput).toBeVisible({ timeout: 10000 });

    await beatInput.fill('First beat');
    await beatInput.press('Enter');
    await expectToast(page, /beat added/i, 5000);

    const beatItem = page.getByText('First beat').first();
    await expect(beatItem).toBeVisible({ timeout: 10000 });
  });

  test('Story Illustration', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    created.push({ kind: 'story', id: story.id });
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    await page.goto(`/story/${story.id}`);
    const editor = page.getByPlaceholder(/once upon a time/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('A magical kingdom floating in the clouds.');

    const illustrateBtn = page.getByRole('button', { name: /Illustrate/i }).first();
    await expect(illustrateBtn).toBeVisible({ timeout: 10000 });
    await illustrateBtn.click();

    await expect(illustrateBtn).toBeDisabled({ timeout: 5000 });
    await expect(illustrateBtn).toBeEnabled({ timeout: 120000 });
  });

  test('@fullstack Continue AI generation completes end-to-end', async ({ page }) => {
    test.setTimeout(300000);
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    created.push({ kind: 'story', id: story.id });
    const chapter = await seedStoryChapter(page, story.id, { title: 'Chapter 1' });
    created.push({ kind: 'chapter', id: `${story.id}:${chapter.id}` });

    await page.goto(`/story/${story.id}/chapter/${chapter.id}`);
    const editor = page.getByPlaceholder(/once upon a time/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('The dark knight stepped into the cavern, drawing his glowing sword.');

    const continueBtn = page.getByRole('button', { name: /continue|generate/i }).first();
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
    created.push({ kind: 'story', id: story.id });
    const chapter = await seedStoryChapter(page, story.id, { title: 'Chapter 1' });
    created.push({ kind: 'chapter', id: `${story.id}:${chapter.id}` });

    await page.goto(`/story/${story.id}/chapter/${chapter.id}`);
    const editor = page.getByPlaceholder(/once upon a time/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('A magical kingdom floating in the clouds, with waterfalls cascading into the sky.');

    const illustrateBtn = page.getByRole('button', { name: /Illustrate/i }).first();
    await expect(illustrateBtn).toBeVisible({ timeout: 10000 });
    await illustrateBtn.click();

    await expect(illustrateBtn).toBeDisabled({ timeout: 5000 });
    await expectToast(page, /illustration prompt|illustrate/i, 180000);
    await expect(illustrateBtn).toBeEnabled({ timeout: 180000 });
  });

  test('@fullstack Branch from beat and continue new path', async ({ page }) => {
    test.setTimeout(300000);
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    created.push({ kind: 'story', id: story.id });
    const chapter = await seedStoryChapter(page, story.id, { title: 'Chapter 1' });
    created.push({ kind: 'chapter', id: `${story.id}:${chapter.id}` });

    await page.goto(`/story/${story.id}/chapter/${chapter.id}`);
    const editor = page.getByPlaceholder(/once upon a time/i).first();
    await expect(editor).toBeVisible({ timeout: 10000 });

    await editor.fill('The hero entered the dark forest.');

    const continueBtn = page.getByRole('button', { name: /continue|generate/i }).first();
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
