// StoryReader: public, publish-and-share story reading at /read/story/:token.
//
// NOTE: /story-reader is NOT a real route. App.jsx registers the reader at
// /read/story/:token (public token URL), and StoryReader fetches
// GET /api/v2/stories/published/{token} — there is no story list page, no
// chapter pager (all chapters render inline) and no delete flow. Tests below
// cover what the page actually offers: publishing a seeded story via
// POST /api/v2/stories/{id}/publish, reading title/description/author note/
// characters/all chapters, error handling for bad tokens, export, and share.

import { test, expect } from '@playwright/test';
import {
  apiPost,
  seedStory,
  seedStoryChapter,
  seedCharacter,
  cleanupEntities,
  uniqueName,
  expectToast,
} from './fixtures.js';

const created = [];

test.afterEach(async ({ page }) => {
  await cleanupEntities(page, created.splice(0));
});

// Publish a seeded story and return its public read URL.
async function publishStory(page, storyId) {
  const res = await apiPost(page, `/stories/${storyId}/publish`);
  return res.read_url;
}

test.describe('Story Reader (public published stories)', () => {
  test('renders a published story with description, author note and all chapters', async ({ page }) => {
    const title = uniqueName('e2e-pub-story');
    const memory = `Secret lore marker: ${uniqueName('e2e-memory')}`;

    const story = await seedStory(page, {
      title,
      description: 'A tale published by the e2e suite.',
      memory,
    });
    created.push({ kind: 'story', id: story.id });
    const ch1 = await seedStoryChapter(page, story.id, {
      title: 'The Arrival',
      content: 'Chapter One content: the wanderer reached the City of Gates.',
    });
    const ch2 = await seedStoryChapter(page, story.id, {
      title: 'The Descent',
      content: 'Chapter Two content: the gates opened beneath the market square.',
    });
    created.push({ kind: 'chapter', id: `${story.id}:${ch2.id}` });
    created.push({ kind: 'chapter', id: `${story.id}:${ch1.id}` });

    const readUrl = await publishStory(page, story.id);
    await page.goto(readUrl);

    await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('A tale published by the e2e suite.')).toBeVisible();

    await expect(page.getByRole('heading', { name: "Author's Note" })).toBeVisible();
    await expect(page.getByText(memory)).toBeVisible();

    const ch1Heading = page.getByRole('heading', { level: 2, name: /Chapter \d+: The Arrival/ });
    const ch2Heading = page.getByRole('heading', { level: 2, name: /Chapter \d+: The Descent/ });
    await expect(ch1Heading).toBeVisible();
    await expect(ch2Heading).toBeVisible();
    await expect(page.getByText('Chapter One content: the wanderer reached the City of Gates.')).toBeVisible();
    await expect(page.getByText('Chapter Two content: the gates opened beneath the market square.')).toBeVisible();
  });

  test('lists characters attached to the published story', async ({ page }) => {
    const character = await seedCharacter(page, { name: uniqueName('e2e-pub-char') });
    created.push({ kind: 'character', id: character.id });

    const story = await seedStory(page, {
      title: uniqueName('e2e-pub-story'),
      character_ids: [character.id],
    });
    created.push({ kind: 'story', id: story.id });
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    const readUrl = await publishStory(page, story.id);
    await page.goto(readUrl);

    await expect(page.getByRole('heading', { level: 2, name: 'Characters' })).toBeVisible({ timeout: 15000 });
    await expect(page.getByText(character.name, { exact: true })).toBeVisible();
  });

  test('invalid token shows an error toast and redirects to the hub', async ({ page }) => {
    await page.goto('/read/story/definitely-not-a-real-token');

    await expectToast(page, /Story not found or no longer available/);
    await page.waitForURL('**/', { timeout: 10000 });
  });

  test('exports the story as Markdown', async ({ page }) => {
    const story = await seedStory(page, {
      title: uniqueName('e2e-pub-story'),
      description: 'Markdown export target.',
    });
    created.push({ kind: 'story', id: story.id });
    const ch = await seedStoryChapter(page, story.id, {
      title: 'Chapter 1',
      content: '# Not a heading\n\nJust exportable prose.',
    });
    created.push({ kind: 'chapter', id: `${story.id}:${ch.id}` });

    const readUrl = await publishStory(page, story.id);
    await page.goto(readUrl);
    await expect(page.getByRole('heading', { level: 1, name: story.title })).toBeVisible({ timeout: 15000 });

    const downloadPromise = page.waitForEvent('download', { timeout: 15000 });
    await page.getByTitle('Export as Markdown').click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe('story.md');
    await expectToast(page, /Exported as MD/);
  });

  test('share button copies the read URL and confirms with a toast', async ({ page }) => {
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);

    const story = await seedStory(page, { title: uniqueName('e2e-pub-story') });
    created.push({ kind: 'story', id: story.id });
    await seedStoryChapter(page, story.id, { title: 'Chapter 1' });

    const readUrl = await publishStory(page, story.id);
    await page.goto(readUrl);
    await expect(page.getByRole('heading', { level: 1, name: story.title })).toBeVisible({ timeout: 15000 });

    await page.getByTitle('Share link').click();
    await expectToast(page, /Link copied!/);

    const clip = await page.evaluate(() => navigator.clipboard.readText());
    expect(clip).toBe(page.url());
  });
});