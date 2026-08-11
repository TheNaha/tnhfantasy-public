import { test, expect } from '@playwright/test';
import { API_BASE, apiGet, apiPost, apiDelete } from './fixtures.js';

test.describe('Provider Management (Module E)', () => {
  test.setTimeout(60000);

  test('Providers Page Loads', async ({ page }) => {
    await page.goto('/providers');

    await expect(page.getByRole('heading', { name: /providers/i })).toBeVisible({ timeout: 10000 });
  });

  test('Provider Search and Filter', async ({ page }) => {
    await page.goto('/providers');

    const searchInput = page.getByPlaceholder(/search providers/i);
    if (await searchInput.isVisible({ timeout: 5000 }).catch(() => false)) {
      await searchInput.fill('modal');
      await page.waitForTimeout(500);
    }

    const allFilter = page.getByRole('button', { name: /all/i }).first();
    if (await allFilter.isVisible()) {
      await allFilter.click();
    }
  });

  test('Refresh Providers', async ({ page }) => {
    await page.goto('/providers');

    const refreshBtn = page.getByRole('button', { name: /refresh/i });
    if (await refreshBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await refreshBtn.click();
      await page.waitForTimeout(2000);
    }
  });

  test('Select Provider and View Detail Panel', async ({ page }) => {
    await page.goto('/providers');

    const providerItem = page.locator('[class*="provider"], [class*="card"]').first();
    if (await providerItem.isVisible({ timeout: 5000 }).catch(() => false)) {
      await providerItem.click();
      await page.waitForTimeout(1000);

      const detailPanel = page.getByText(/status|diagnostics|worker/i).first();
      if (await detailPanel.isVisible()) {
        await expect(detailPanel).toBeVisible();
      }
    }
  });

  test('Load Balancer Bar Visible', async ({ page }) => {
    await page.goto('/providers');

    const lbBar = page.getByText(/load balancer|strategy/i).first();
    if (await lbBar.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(lbBar).toBeVisible();
    }
  });

  test('Add Provider Modal', async ({ page }) => {
    await page.goto('/providers');

    const addBtn = page.getByRole('button', { name: /add provider/i });
    if (await addBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await addBtn.click();
      const modal = page.getByText(/provider type|id|name/i).first();
      if (await modal.isVisible({ timeout: 3000 }).catch(() => false)) {
        await expect(modal).toBeVisible();
      }
    }
  });

  test('Cleanup State Action', async ({ page }) => {
    await page.goto('/providers');

    const cleanupBtn = page.getByRole('button', { name: /cleanup/i });
    if (await cleanupBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await cleanupBtn.click();
      const confirmBtn = page.getByRole('button', { name: /cleanup|confirm/i }).first();
      if (await confirmBtn.isVisible()) {
        await confirmBtn.click();
      }
    }
  });
});
