// Module E: World Timeline — date-grouped events + filter panel.
//
// Seed strategy: a chat message (POST /v2/chats/{id}/messages, role=char —
// never spawns an LLM job) and a story chapter (POST /v2/stories/{id}/chapters).

import { test, expect } from '@playwright/test';
import {
  apiGet,
  cleanupEntities,
  seedChat,
  seedChatMessage,
  seedStory,
  seedStoryChapter,
  uniqueName,
} from './fixtures.js';

const created = [];

test.afterEach(async ({ page }) => {
  await cleanupEntities(page, created.splice(0));
});

test.describe('World Timeline', () => {
  test('page renders heading, subtitle and filter controls', async ({ page }) => {
    await page.goto('/world-timeline');

    await expect(page.getByRole('heading', { level: 1, name: 'World Timeline' })).toBeVisible();
    await expect(page.getByText('Chronological view of all events across your world')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Filters', exact: true })).toBeVisible();

    // The shared dev DB accumulates events (e.g. completed jobs surface as
    // asset events), so the empty state is covered by the unit tests instead.
    await expect(page.getByText('No events yet', { exact: true })).toHaveCount(0);
  });

  test('filter panel toggles open and drives the events query', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });

    await page.goto('/world-timeline');
    const filtersBtn = page.getByRole('button', { name: 'Filters', exact: true });

    await filtersBtn.click();
    for (const label of ['Character ID', 'Story ID', 'Chat ID', 'Location']) {
      await expect(page.getByText(label, { exact: true })).toBeVisible();
    }

    const chatInput = page.getByPlaceholder('Filter by chat...');
    await expect(chatInput).toBeVisible();

    // Typing a filter value must re-fire the query with the chat_id param.
    const filteredReq = page.waitForResponse(
      (r) => r.url().includes('/api/v2/timeline') && r.url().includes(`chat_id=${chat.id}`),
    );
    await chatInput.fill(chat.id);
    await filteredReq;

    await filtersBtn.click();
    await expect(page.getByText('Chat ID', { exact: true })).toHaveCount(0);
  });

  test('seeded chat message and story chapter appear as timeline events (UI + API)', async ({ page }) => {
    const messageContent = uniqueName('e2e-timeline-message');
    const chapterTitle = uniqueName('e2e-chapter');

    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    created.push({ kind: 'chat', id: chat.id });
    await seedChatMessage(page, chat.id, { content: messageContent });

    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    created.push({ kind: 'story', id: story.id });
    const chapter = await seedStoryChapter(page, story.id, { title: chapterTitle });
    created.push({ kind: 'chapter', id: `${story.id}:${chapter.id}` });

    await page.goto('/world-timeline');

    await expect(page.getByText('No events yet', { exact: true })).toHaveCount(0, { timeout: 15000 });
    await expect(page.getByText(new RegExp(messageContent))).toBeVisible();
    await expect(page.getByText(new RegExp(chapterTitle))).toBeVisible();

    const { events } = await apiGet(page, '/timeline/timeline');

    const messageEvent = events.find((e) => e.type === 'message' && e.description.includes(messageContent));
    expect(messageEvent, 'seeded message should appear as a message event').toBeTruthy();
    expect(messageEvent.chat_id).toBe(chat.id);

    const chapterEvent = events.find((e) => e.type === 'chapter' && e.title.includes(chapterTitle));
    expect(chapterEvent, 'seeded chapter should appear as a chapter event').toBeTruthy();
    expect(chapterEvent.title).toMatch(/^Chapter \d+: /);
    expect(chapterEvent.story_id).toBe(story.id);
  });
});