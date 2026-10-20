import { test, expect } from '@playwright/test';

/**
 * The LLM Studio page header.
 *
 * The title column and the tab strip share a row. The strip used to carry
 * `shrink-0` and `overflow-x-auto` together, and `shrink-0` won: the strip
 * kept its full intrinsic width, spilled past the page, and the last tab was
 * unreachable. The title column, being an unconstrained flex child, was left
 * whatever was left over — a column two characters wide.
 */
test.describe('LLM Studio header', () => {
    const VIEWPORTS = [
        { name: 'wide', width: 1919, height: 1080 },
        { name: 'desktop', width: 1440, height: 900 },
        { name: 'laptop', width: 1280, height: 800 },
        { name: 'tablet', width: 900, height: 800 },
    ];

    for (const vp of VIEWPORTS) {
        test(`lays out at ${vp.name} (${vp.width}px)`, async ({ page }) => {
            const viewportWidth = vp.width;
            await page.setViewportSize({ width: vp.width, height: vp.height });
            await page.goto('/llm-studio?tab=workflow', { waitUntil: 'domcontentloaded' });
            await page.waitForTimeout(2000);

            const title = page.locator('h1', { hasText: 'Multi-Agent Workflow' });
            await expect(title).toBeVisible();
            const box = await title.boundingBox();

            // The title must be ONE line. It was wrapping to five.
            const lineHeight = await title.evaluate(
                (el) => parseFloat(getComputedStyle(el).fontSize) * 1.25
            );
            expect(
                box.height,
                `title wrapped onto multiple lines (${box.height}px tall, one line is ~${Math.round(lineHeight)}px)`
            ).toBeLessThan(lineHeight * 1.6);

            // Nothing may spill past the viewport horizontally.
            const overflow = await page.evaluate(() => ({
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth,
            }));
            expect(
                overflow.scrollWidth,
                `the page scrolls horizontally: ${overflow.scrollWidth} > ${overflow.clientWidth}`
            ).toBeLessThanOrEqual(overflow.clientWidth + 1);

            // Every tab must be VISIBLE, not merely reachable by scrolling.
            // The strip wraps rather than scrolls, so a tab cannot be hidden
            // behind a horizontal scroll the user never notices.
            const tabStrip = page.locator('div').filter({ has: page.getByRole('button', { name: /^Workflow$/ }) }).last();
            const tabButtons = tabStrip.getByRole('button');
            const tabCount = await tabButtons.count();
            expect(tabCount, 'the tab strip lost its buttons').toBeGreaterThanOrEqual(9);

            const hidden = [];
            for (let i = 0; i < tabCount; i += 1) {
                const btn = tabButtons.nth(i);
                const name = (await btn.innerText()).trim().split('\n')[0];
                const b = await btn.boundingBox();
                if (!b) {
                    hidden.push(`${name} (no box)`);
                    continue;
                }
                // Inside the viewport horizontally.
                if (b.x < 0 || b.x + b.width > viewportWidth + 1) {
                    hidden.push(`${name} (x=${Math.round(b.x)} w=${Math.round(b.width)})`);
                }
            }
            expect(hidden, `tabs pushed out of the viewport: ${hidden.join(', ')}`).toEqual([]);
        });
    }
});
