import { test, expect } from '@playwright/test';

test.describe('Navigation & Page Smoke Tests', () => {
  test.setTimeout(120000);

  const routes = [
    { path: '/', name: 'Dashboard' },
    { path: '/gallery', name: 'Gallery' },
    { path: '/generate', name: 'Simple Generator' },
    { path: '/img2img', name: 'Img2Img' },
    { path: '/inpaint', name: 'Inpaint' },
    { path: '/advanced', name: 'Advanced Generator' },
    { path: '/chat', name: 'Chat Workspace' },
    { path: '/story', name: 'Story Sandbox' },
    { path: '/characters', name: 'Character Vault' },
    { path: '/models/discover', name: 'Discover Models' },
    { path: '/models/installed', name: 'Installed Models' },
    { path: '/providers', name: 'Providers' },
    { path: '/statistics', name: 'Statistics' },
    { path: '/settings', name: 'Settings' },
  ];

  for (const route of routes) {
    test(`${route.name} loads (${route.path})`, async ({ page }) => {
      await page.goto(route.path);

      const body = page.locator('body');
      await expect(body).toBeVisible({ timeout: 30000 });

      const h1 = page.locator('h1').first();
      const h2 = page.locator('h2').first();
      const heading = (await h1.isVisible({ timeout: 2000 }).catch(() => false)) ? h1 : h2;

      if (await heading.isVisible({ timeout: 2000 }).catch(() => false)) {
        const text = await heading.textContent();
        expect(text?.length).toBeGreaterThan(0);
      }
    });
  }
});
