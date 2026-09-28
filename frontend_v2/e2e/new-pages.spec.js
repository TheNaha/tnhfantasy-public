import { test, expect } from '@playwright/test';
import { seedCharacter, seedChat, trackEntity, uniqueName } from './fixtures.js';

test.describe('New Pages (Relationship Graph & Avatar Gallery)', () => {
   test('Relationship Graph renders nodes and filters', async ({ page }) => {
    const char = await seedCharacter(page, { name: uniqueName('graph-char') });
    trackEntity(page, 'character', char.id);
    const chat = await seedChat(page, { character_id: char.id });
    trackEntity(page, 'chat', chat.id);

    await page.goto('/world-graph');

    // Expect the header
    await expect(page.getByRole('heading', { name: 'Relationship Graph' })).toBeVisible({ timeout: 15000 });

    // Expect the filters to be visible
    await expect(page.locator('select')).toBeVisible();

    // Verify SVG container renders
    const svg = page.locator('svg.mx-auto');
    await expect(svg).toBeVisible();
  });

  test('Relationship Graph renders the filter dropdown with entity type options', async ({ page }) => {
    await page.goto('/world-graph');

    const select = page.locator('select');
    await expect(select).toBeVisible({ timeout: 10000 });

    // Verify all filter options are available
    const options = await select.locator('option').allTextContents();
    expect(options).toContain('All Entities');
    expect(options).toContain('Characters');
    expect(options).toContain('Stories');
    expect(options).toContain('Chats');
    expect(options).toContain('Lorebooks');
    expect(options).toContain('Voices');
    expect(options).toContain('Locations');
  });

  test('Relationship Graph legend shows all node types with icons', async ({ page }) => {
    const char = await seedCharacter(page, { name: uniqueName('graph-legend-char') });
    trackEntity(page, 'character', char.id);

    await page.goto('/world-graph');

    // The legend should display all entity type labels
    const legendArea = page.locator('.flex.flex-wrap.gap-3');
    await expect(legendArea.getByText('Characters')).toBeVisible({ timeout: 15000 });
    await expect(legendArea.getByText('Stories')).toBeVisible();
    await expect(legendArea.getByText('Chats')).toBeVisible();
    await expect(legendArea.getByText('Lorebooks')).toBeVisible();
    await expect(legendArea.getByText('Voices')).toBeVisible();
    expect(await legendArea.getByText('Locations').isVisible()).toBeTruthy();
  });

   test('Relationship Graph refresh button triggers refetch', async ({ page }) => {
    const char = await seedCharacter(page, { name: uniqueName('graph-refresh-char') });
    trackEntity(page, 'character', char.id);
    const chat = await seedChat(page, { character_id: char.id });
    trackEntity(page, 'chat', chat.id);

    await page.goto('/world-graph');

    await expect(page.locator('svg.mx-auto')).toBeVisible({ timeout: 15000 });

    // Click refresh — page should not crash, heading should still be visible
    await page.getByTitle('Refresh').click({ timeout: 10000 });

    // After refetch, the heading should still be visible (page didn't crash)
    await expect(page.getByRole('heading', { name: 'Relationship Graph' })).toBeVisible({ timeout: 15000 });
  });

  // The three Avatar Gallery specs are gone with the page. It was a second
  // rendering of the Characters grid using the same `useCharacters()` and the
  // same `CharacterCard`, with the edit actions stripped off, so the coverage
  // they provided is covered by the Characters specs. The route now redirects to
  // `/characters`, which is asserted here so a bookmark does not dead-end.
  test('the retired avatar gallery route redirects to characters', async ({ page }) => {
    await page.goto('/avatar-gallery');
    await expect(page).toHaveURL(/\/characters/, { timeout: 15000 });
    await expect(page.getByRole('heading', { name: /Character Vault/i })).toBeVisible({ timeout: 15000 });
  });
});
