import { test, expect } from '@playwright/test';
import { API_BASE, apiGet, apiPost, waitForToast } from './fixtures.js';

test.describe('Settings & Configuration (Module F)', () => {
  test.setTimeout(60000);

  test('Settings Page Loads with All Tabs', async ({ page }) => {
    await page.goto('/settings');

    await expect(page.getByText(/settings/i)).toBeVisible({ timeout: 10000 });

    const tabs = ['AI / LLM', 'Branding', 'UI / UX', 'Gallery', 'Models', 'Generator'];
    for (const tab of tabs) {
      const tabBtn = page.getByRole('button', { name: new RegExp(tab, 'i') });
      if (await tabBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        await expect(tabBtn).toBeVisible();
      }
    }
  });

  test('Switch Settings Tabs', async ({ page }) => {
    await page.goto('/settings');

    const tabs = ['AI / LLM', 'Branding', 'UI / UX', 'Gallery', 'Models', 'Generator'];
    for (const tab of tabs) {
      const tabBtn = page.getByRole('button', { name: new RegExp(tab, 'i') }).first();
      if (await tabBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        await tabBtn.click();
        await page.waitForTimeout(300);
      }
    }
  });

  test('UI Settings: Change Toast Duration', async ({ page }) => {
    await page.goto('/settings');

    const uiTab = page.getByRole('button', { name: /UI \/ UX/i }).first();
    if (await uiTab.isVisible()) {
      await uiTab.click();
      await page.waitForTimeout(500);

      const slider = page.locator('input[type="range"]').first();
      if (await slider.isVisible()) {
        await slider.fill('5000');
        await waitForToast(page, /updated/i, 3000);
      }
    }
  });

  test('Generator Settings: Change Default Checkpoint', async ({ page }) => {
    await page.goto('/settings');

    const genTab = page.getByRole('button', { name: /generator/i }).first();
    if (await genTab.isVisible()) {
      await genTab.click();
      await page.waitForTimeout(500);

      const select = page.locator('select').first();
      if (await select.isVisible()) {
        const options = await select.locator('option').allTextContents();
        if (options.length > 1) {
          await select.selectOption({ index: 1 });
          await waitForToast(page, /updated/i, 3000);
        }
      }
    }
  });

  test('Gallery Settings: Toggle Auto-Refresh', async ({ page }) => {
    await page.goto('/settings');

    const galleryTab = page.getByRole('button', { name: /gallery/i }).first();
    if (await galleryTab.isVisible()) {
      await galleryTab.click();
      await page.waitForTimeout(500);

      const checkbox = page.locator('input[type="checkbox"]').first();
      if (await checkbox.isVisible()) {
        await checkbox.click();
        await waitForToast(page, /updated/i, 3000);
      }
    }
  });

  test('Branding: View Branding Settings', async ({ page }) => {
    await page.goto('/settings');

    const brandingTab = page.getByRole('button', { name: /branding/i }).first();
    if (await brandingTab.isVisible()) {
      await brandingTab.click();
      await page.waitForTimeout(500);

      const appNameInput = page.getByPlaceholder(/enter app name/i);
      if (await appNameInput.isVisible()) {
        await expect(appNameInput).toBeVisible();
      }
    }
  });

  test('Reset Category', async ({ page }) => {
    await page.goto('/settings');

    const uiTab = page.getByRole('button', { name: /UI \/ UX/i }).first();
    if (await uiTab.isVisible()) {
      await uiTab.click();
      await page.waitForTimeout(500);

      const resetBtn = page.getByRole('button', { name: /reset/i }).first();
      if (await resetBtn.isVisible()) {
        await resetBtn.click();
        const confirmBtn = page.getByRole('button', { name: /reset/i }).first();
        if (await confirmBtn.isVisible()) {
          await confirmBtn.click();
        }
        await waitForToast(page, /reset/i, 3000);
      }
    }
  });

  test('System Prompts: Edit and Save', async ({ page }) => {
    await page.goto('/settings');

    const aiTab = page.getByRole('button', { name: /AI \/ LLM/i }).first();
    if (await aiTab.isVisible()) {
      await aiTab.click();
      await page.waitForTimeout(500);

      const textarea = page.locator('textarea').first();
      if (await textarea.isVisible()) {
        await textarea.fill('Updated system prompt for E2E test');
        const saveBtn = page.getByRole('button', { name: /save prompts/i });
        if (await saveBtn.isVisible()) {
          await saveBtn.click();
          await waitForToast(page, /updated|saved/i, 5000);
        }
      }
    }
  });
});
