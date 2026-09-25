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
      // Each page renders a content heading with its title; pages use
      // different heading levels as their visual hierarchy changes.
      const heading = page.locator('main h1, main h2, main h3, main h4').first();
      await expect(heading).toBeVisible({ timeout: 15000 });
      const text = await heading.textContent();
      expect(text?.trim().length).toBeGreaterThan(0);
    });
  }
});
