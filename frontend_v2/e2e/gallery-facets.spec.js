import { expect, test } from '@playwright/test';

/**
 * The faceted gallery, in a real browser.
 *
 * The unit tests mock the API and mount the components in isolation, so they
 * cannot see the three ways this breaks in practice: the gallery page failing
 * to render at all, the facet request never reaching the API, or the panel
 * writing into a filter object the listing is not actually reading. This file
 * drives the real page against the real backend.
 */

const facetPanel = (page) => page.locator('[data-testid="gallery-filter-panel"]');
const dateRail = (page) => page.locator('[data-testid="gallery-date-rail"]');

test.describe('faceted gallery', () => {
    test.beforeEach(async ({ page }) => {
        // Fail loudly on a console error rather than a silent render blank.
        const errors = [];
        page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
        page.on('pageerror', (e) => errors.push(String(e)));
        page.errors = errors;

        await page.goto('/gallery');
        // The rail is the last of these to appear — it waits on the histogram —
        // so waiting for it waits for the whole gallery.
        await expect(dateRail(page)).toBeVisible({ timeout: 20000 });
    });

    test('the gallery renders with the facet panel and the date rail', async ({ page }) => {
        await expect(facetPanel(page)).toBeVisible();
        await expect(dateRail(page)).toBeVisible();
        expect(page.errors, `console errors: ${page.errors.join(' | ')}`).toEqual([]);
    });

    test('the gallery asks the facet endpoint, and it answers', async ({ page }) => {
        const facetCalls = [];
        page.on('response', (r) => {
            if (r.url().includes('/api/v2/assets/facet')) facetCalls.push(r);
        });
        await page.reload();
        await expect(facetPanel(page)).toBeVisible({ timeout: 20000 });
        await page.waitForTimeout(1500);

        expect(facetCalls.length, 'the gallery did not call /api/v2/assets/facet').toBeGreaterThan(0);
        expect(facetCalls[0].status()).toBe(200);
        expect(facetCalls[0].url()).toContain('group_by=');
    });

    test('the date rail asks the histogram, and it answers', async ({ page }) => {
        const dateCalls = [];
        page.on('response', (r) => {
            if (r.url().includes('/api/v2/assets/dates')) dateCalls.push(r);
        });
        await page.reload();
        await expect(dateRail(page)).toBeVisible({ timeout: 20000 });
        await page.waitForTimeout(1500);

        expect(dateCalls.length, 'the date rail did not call /api/v2/assets/dates').toBeGreaterThan(0);
        expect(dateCalls[0].status()).toBe(200);
    });

    test('selecting a facet value narrows the listing', async ({ page }) => {
        const facetRequests = [];
        page.on('request', (r) => {
            if (r.url().includes('/api/v2/assets/facet')) facetRequests.push(r.url());
        });

        await page.reload();
        await expect(facetPanel(page)).toBeVisible({ timeout: 20000 });

        const chip = facetPanel(page).locator("button[aria-pressed]").first();
        await expect(chip).toBeVisible({ timeout: 10000 });
        const before = facetRequests.length;
        await chip.click();

        // A narrowed listing means a NEW request carrying the filter. Asserting on
        // the request rather than on the rendered count is deliberate: the library
        // may legitimately hold one image for a value, and "0 matching" is a
        // perfectly good answer to a filter nobody expected.
        await page.waitForTimeout(2000);
        const after = facetRequests.slice(before).join('\n');
        // The parameter is matched anywhere in the query, not immediately after
        // `?`: the client appends the filter after the ones it always sends, so
        // the real URL is `...?limit=20&group_by=…&sort=date_desc&lora=1009342`.
        expect(after, 'selecting a facet did not re-query with it').toMatch(
            /[?&](lora|tag|checkpoint)=/
        );

        await expect(chip).toHaveAttribute('aria-pressed', 'true');
    });

    test('no unhandled request failures once the page has settled', async ({ page }) => {
        const failures = [];
        page.on('response', (r) => {
            if (r.status() >= 400 && r.url().includes('/api/')) {
                failures.push(`${r.status()} ${r.url()}`);
            }
        });
        await page.reload();
        await expect(facetPanel(page)).toBeVisible({ timeout: 20000 });
        await page.waitForTimeout(2000);

        // 404 on an image thumbnail for a soft-deleted asset is expected and is
        // not this feature's problem; a 4xx/5xx on a listing or filter call is.
        const relevant = failures.filter((f) => !/thumb|file|thumbnail/.test(f));
        expect(relevant, `API failures: ${relevant.join(' | ')}`).toEqual([]);
    });
});
