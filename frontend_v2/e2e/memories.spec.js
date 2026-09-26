// E2E: Character Memories — create, view, and delete character memories.

import { test, expect } from '@playwright/test';
import {
  seedCharacter,
  trackEntity,
  uniqueName,
} from './fixtures.js';

test.describe('Character Memories (Module H)', () => {
  test.setTimeout(60000);

  test('creates and lists a memory for a character', async ({ page }) => {
    const char = await seedCharacter(page, { name: uniqueName('e2e-mem-char') });
    trackEntity(page, 'character', char.id);

    const content = uniqueName('e2e-memory-text');

    // Navigate to characters page with hash deep-link
    await page.goto(`/characters#char-${char.id}`);
    // Wait for characters data to load, then the deep-link effect opens the modal
    await expect(page.getByRole('heading', { name: 'Edit Character' })).toBeVisible({ timeout: 30000 });

    // Switch to Memories tab
    await page.locator('button', { hasText: 'Memories' }).first().click({ timeout: 10000 });

    // Click Add
    await page.getByRole('button', { name: 'Add' }).click({ timeout: 10000 });

    // Fill the memory form
    await page.locator('textarea[placeholder="Memory content…"]').fill(content);

    // Submit
    await page.getByText('Save Memory').click({ timeout: 10000 });

    // Verify the memory appears in the list
    await expect(page.getByText(content)).toBeVisible({ timeout: 15000 });
  });

  test('deletes a memory after confirmation', async ({ page }) => {
    const char = await seedCharacter(page, { name: uniqueName('e2e-del-char') });
    trackEntity(page, 'character', char.id);

    // Wait for the character to be persisted in the database
    await page.waitForTimeout(2000);

    // Navigate directly to the deep-link URL (fresh page load so the effect fires)
    await page.goto(`/characters#char-${char.id}`);

    // Wait for the API response and deep-link to fire
    const response = await page.waitForResponse(
      (resp) => resp.url().includes('/v2/characters') && resp.status() === 200,
      { timeout: 30000 }
    );
    const characters = await response.json();
    const found = characters.some((c) => c.id === char.id);

    if (found) {
      await expect(page.getByRole('heading', { name: 'Edit Character' })).toBeVisible({ timeout: 30000 });
    } else {
      // Deep-link might not have fired; retry with longer wait
      await page.waitForTimeout(5000);
      await page.goto(`/characters#char-${char.id}`);
      await expect(page.getByRole('heading', { name: 'Edit Character' })).toBeVisible({ timeout: 30000 });
    }

    // Switch to Memories tab
    await page.locator('button', { hasText: 'Memories' }).first().click({ timeout: 10000 });
    await page.getByRole('button', { name: 'Add' }).click({ timeout: 10000 });
    const content = uniqueName('e2e-del-memory');
    await page.locator('textarea[placeholder="Memory content…"]').fill(content);
    await page.getByText('Save Memory').click({ timeout: 10000 });
    await expect(page.getByText(content)).toBeVisible({ timeout: 15000 });

    // Delete — confirmation modal renders via portal to document.body
    await page.locator('[title="Delete memory"]').first().click({ timeout: 10000, force: true });
    await page.getByRole('button', { name: 'Delete', exact: true }).click({ timeout: 15000 });

    // Memory should be gone
    await expect(page.getByText(content)).not.toBeVisible({ timeout: 10000 });
  });

  test('cancels memory creation when Cancel is clicked', async ({ page }) => {
    const char = await seedCharacter(page, { name: uniqueName('e2e-cancel-char') });
    trackEntity(page, 'character', char.id);

    await page.goto(`/characters#char-${char.id}`);
    await expect(page.getByRole('heading', { name: 'Edit Character' })).toBeVisible({ timeout: 30000 });

    // Add a memory
    await page.locator('button', { hasText: 'Memories' }).first().click({ timeout: 10000 });
    await page.getByRole('button', { name: 'Add' }).click({ timeout: 10000 });
    await page.locator('textarea[placeholder="Memory content…"]').fill('A memory I want to cancel');

    // Cancel
    await page.getByRole('button', { name: 'Cancel' }).click({ timeout: 10000 });

    // The form should be gone
    await expect(page.locator('textarea[placeholder="Memory content…"]')).not.toBeVisible();
  });
});
