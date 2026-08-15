// E2E: World Vault Hub — search across entities and navigate from search results.

import { test, expect } from '@playwright/test';
import {
  cleanupEntities,
  seedCharacter,
  seedStory,
  uniqueName,
} from './fixtures.js';

test.describe('World Vault Hub (Module J)', () => {
  test.setTimeout(60000);

  let created = [];

  test.afterEach(async ({ page }) => {
    await cleanupEntities(page, created.splice(0));
  });

  test('renders the hub with heading, search and entity counts', async ({ page }) => {
    const char = await seedCharacter(page, { name: uniqueName('hub-char') });
    created.push({ kind: 'character', id: char.id });

    await page.goto('/world-vault');

    await expect(page.getByRole('heading', { name: 'World Vault' })).toBeVisible({ timeout: 15000 });
    await expect(page.locator('input[placeholder="Search across all entities..."]')).toBeVisible();
    await expect(page.getByText('Entity Counts')).toBeVisible();

    // Entity counts section should show at least one entity type
    // The backend returns lowercase keys like "characters", "chats", etc.
    await expect(page.locator('.text-xs.text-gray-400.capitalize').filter({ hasText: /character/i }).first()).toBeVisible({ timeout: 15000 });
  });

  test('search returns matching entities across types', async ({ page }) => {
    const searchTerm = uniqueName('e2e-hub-search');
    const char = await seedCharacter(page, {
      name: `Hero ${searchTerm}`,
      description: `A brave warrior known as ${searchTerm}`,
    });
    created.push({ kind: 'character', id: char.id });

    const story = await seedStory(page, {
      title: `The Tale of ${searchTerm}`,
      description: `An epic story about ${searchTerm}`,
    });
    created.push({ kind: 'story', id: story.id });

    await page.goto('/world-vault');

    // Type the search term
    await page.locator('input[placeholder="Search across all entities..."]').fill(searchTerm);

    // Wait for debounced search (300ms) + API response
    await page.waitForTimeout(1000);

    // Wait for results to appear
    await expect(page.getByText(`Hero ${searchTerm}`)).toBeVisible({ timeout: 15000 });
    await expect(page.getByText(`The Tale of ${searchTerm}`)).toBeVisible({ timeout: 10000 });
  });

  test('clicking a character search result navigates to the character deep-link', async ({ page }) => {
    const char = await seedCharacter(page, { name: uniqueName('e2e-deep-link-char') });
    created.push({ kind: 'character', id: char.id });

    await page.goto('/world-vault');

    // Search for the character
    await page.locator('input[placeholder="Search across all entities..."]').fill(char.name);
    await page.waitForTimeout(800);

    // Click the character result
    await page.getByRole('button', { name: char.name }).first().click();

    // Should navigate to /characters#char-<id>
    await expect(page).toHaveURL(new RegExp(`/characters#char-${char.id}`), { timeout: 10000 });
  });

  test('filtering search by entity type narrows results', async ({ page }) => {
    const charName = uniqueName('e2e-filter-char');
    const char = await seedCharacter(page, { name: charName });
    created.push({ kind: 'character', id: char.id });

    const story = await seedStory(page, { title: `Story ${charName}` });
    created.push({ kind: 'story', id: story.id });

    await page.goto('/world-vault');

    // Type a search that should match both character and story
    await page.locator('input[placeholder="Search across all entities..."]').fill(charName);
    await page.waitForTimeout(800);

    // Both should appear with "all" filter
    await expect(page.getByText(charName).first()).toBeVisible({ timeout: 15000 });

    // Filter to only characters
    await page.locator('select').selectOption('character');
    await page.waitForTimeout(800);

    // The story's specific text should be gone
    await expect(page.getByText(`Story ${charName}`)).not.toBeVisible();
    // The character should still be visible
    await expect(page.getByText(charName).first()).toBeVisible();
  });
});
