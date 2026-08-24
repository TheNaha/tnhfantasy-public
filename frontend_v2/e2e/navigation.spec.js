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

      // Assert the app actually rendered content — not just that <body>
      // exists (which is always true even when the React tree crashes).
      // Each page renders an h1 or h2 heading with its title.
      const h1 = page.locator('h1').first();
      const h2 = page.locator('h2').first();
      const heading = h1;
      const fallback = h2;

      // Prefer h1; fall back to h2 only if h1 is not present.
      const headingToUse = (await heading.isVisible({ timeout: 3000 }).catch(() => false))
        ? heading
        : fallback;

      await expect(headingToUse).toBeVisible({ timeout: 15000 });
      const text = await headingToUse.textContent();
      expect(text?.trim().length).toBeGreaterThan(0);
    });
  }
});
