import { expect, test } from '@playwright/test';

/**
 * The session view, in a real browser.
 *
 * Three defects lived here and none of them were visible to a unit test,
 * because each one is about what the page does *when a person uses it*:
 *
 * 1. The scroll sentinel was disabled in session view, so a 1,411-session
 *    library could never reach page two. The view looked like it only ever had
 *    the handful of cards the virtualizer happened to mount — which is exactly
 *    how "I only got 3" reads.
 * 2. The sort collapsed all three of the gallery's sort modes into
 *    `sort === 'date_asc' ? 1 : -1`, so Random silently ordered sessions by
 *    date — a control that looks like it did something and provably did not.
 * 3. A session's images were plain `<img>` with no handler, so the one place a
 *    session actually showed its images was the one place you could not open
 *    one.
 */

const sessionCard = (page) => page.locator('section[aria-label^="Session"]').first();

test.describe('session view', () => {
    test.beforeEach(async ({ page }) => {
        const errors = [];
        page.on('pageerror', (e) => errors.push(String(e)));
        page.errors = errors;

        await page.goto('/gallery', { waitUntil: 'networkidle' });
        await page.getByRole('button', { name: /Group by session/i }).first().click();
        await expect(sessionCard(page)).toBeVisible({ timeout: 20000 });
    });

    test('renders session cards rather than a handful of images', async ({ page }) => {
        const cards = page.locator('section[aria-label^="Session"]');
        expect(await cards.count()).toBeGreaterThan(0);
        // Each card states its own image count, which is what makes a session
        // legible before you expand it.
        await expect(cards.first()).toContainText(/image/i);
        expect(page.errors).toEqual([]);
    });

    test('expands to images that are clickable, and they open the detail modal', async ({ page }) => {
        await sessionCard(page).locator('button[aria-expanded]').first().click();

        // The member images are the buttons named by their asset path. The
        // header thumbnail has an empty alt, so it is not one of them — which is
        // how this test avoids clicking the expand toggle twice.
        const members = sessionCard(page).locator('button[aria-label]');
        await expect(members.first()).toBeVisible({ timeout: 20000 });
        const assetPath = await members.first().getAttribute('aria-label');
        expect(assetPath).toMatch(/\.png$/i);

        await members.first().click();
        const dialog = page.locator('[role="dialog"]');
        await expect(dialog).toBeVisible({ timeout: 15000 });
        // The modal is the same one the grid opens, so it carries the same
        // actions — which is the point: a session's images behave like images.
        await expect(dialog).toContainText(/Details/i);
        await expect(dialog).toContainText(/Download/i);
    });

    test('loading more sessions is reachable by scrolling', async ({ page }) => {
        // The regression: the sentinel was switched off in session view, so the
        // view could never page past the first 100 sessions no matter how far
        // you scrolled.
        const requests = [];
        page.on('request', (r) => {
            if (r.url().includes('/api/v2/sessions')) requests.push(r.url());
        });

        for (let i = 0; i < 6; i += 1) {
            await page.mouse.wheel(0, 4000);
            await page.waitForTimeout(700);
        }
        await page.waitForTimeout(1500);

        const paged = requests.filter((u) => /offset=/.test(u));
        expect(
            paged.length,
            `never asked for a second page of sessions (saw ${requests.length} request(s): ${requests.join(', ')})`
        ).toBeGreaterThan(0);
    });

    test('the sort control reaches the session ordering', async ({ page }) => {
        const names = () => page.locator('section[aria-label^="Session"] h3, section[aria-label^="Session"] .text-sm.font-semibold');
        const firstFew = async () => (await names().allTextContents()).slice(0, 5).map((t) => t.trim());

        const newest = await firstFew();
        await page.locator('select').filter({ hasText: /Newest First/ }).first().selectOption('date_asc');
        await page.waitForTimeout(1500);
        const oldest = await firstFew();

        expect(oldest).not.toEqual(newest);
    });
});
