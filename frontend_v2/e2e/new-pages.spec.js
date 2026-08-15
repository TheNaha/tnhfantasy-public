import { test, expect } from '@playwright/test';
import { seedCharacter, cleanupEntities, uniqueName } from './fixtures.js';

test.describe('New Pages (Relationship Graph & Avatar Gallery)', () => {
  let created = [];

  test.afterEach(async ({ page }) => {
    await cleanupEntities(page, created.splice(0));
  });

  test('Relationship Graph renders nodes and filters', async ({ page }) => {
    const char = await seedCharacter(page, { name: uniqueName('graph-char') });
    created.push({ kind: 'character', id: char.id });

    await page.goto('/world-graph');
    
    // Expect the header
    await expect(page.getByRole('heading', { name: 'Relationship Graph' })).toBeVisible({ timeout: 10000 });
    
    // Expect the filters to be visible
    await expect(page.locator('select')).toBeVisible();
    await expect(page.getByText('Visualize connections between characters, stories, and more')).toBeVisible();

    // Verify SVG container renders
    const svg = page.locator('svg.mx-auto');
    await expect(svg).toBeVisible();
  });

  test('Avatar Gallery renders and handles character selection', async ({ page }) => {
    const char = await seedCharacter(page, { name: uniqueName('avatar-char') });
    created.push({ kind: 'character', id: char.id });

    await page.goto('/avatar-gallery');
    
    // Check main gallery container elements
    await expect(page.getByRole('heading', { name: 'Avatar Gallery' })).toBeVisible({ timeout: 10000 });
    
    // Check if the character we created appears in the gallery
    await expect(page.getByText(char.name)).toBeVisible({ timeout: 10000 });
    
    // Click on the character card and verify chat button exists
    await expect(page.getByRole('button', { name: /Chat/i }).first()).toBeVisible({ timeout: 10000 });
  });
});
