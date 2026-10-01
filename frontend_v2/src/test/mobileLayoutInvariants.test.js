/**
 * The overflow metric, stated once so it cannot be got wrong again.
 *
 * `document.documentElement.scrollWidth > window.innerWidth` CANNOT detect
 * horizontal overflow in this app. `components/Layout.jsx:218` puts
 * `overflow-x-hidden` on the app root, so the document element never scrolls
 * horizontally and the check is structurally always false — on every route, at
 * every width. It reports "no overflow" on `/gallery` while 1,836px of content
 * is clipped and 32 date-rail bars sit permanently outside the viewport.
 *
 * The metric that works is the scroll container's own
 * `scrollWidth - clientWidth`, plus whether the excess is *reachable*: content
 * inside an `overflow-x: auto|scroll` ancestor is fine, content inside an
 * `overflow-x: hidden` one is not, because nothing can scroll to it.
 *
 * These are unit tests over the CSS, not a browser run, so they hold in CI
 * without Playwright. They pin the two defects that were invisible to the wrong
 * metric: a tap-target floor that made a dense chart overflow, and a fixed
 * overlay that sat on top of the primary action.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
// Paths are relative to `src/`, not to this file's directory.
const SRC = join(here, '..');
const read = (p) => readFileSync(join(SRC, p), 'utf8');

describe('horizontal overflow cannot be measured on the document element', () => {
    it('the app root clips overflow-x, so scrollWidth on <html> is not a signal', () => {
        // This is the whole reason a previous audit reported "no horizontal
        // overflow on any route" while `/gallery` clipped 1,836px.
        const layout = read('components/Layout.jsx');
        const root = layout.match(/<div className="flex min-h-screen[^"]*"/);
        expect(root).toBeTruthy();
        expect(root[0]).toContain('overflow-x-hidden');
    });

    it('the full-bleed main no longer hides horizontal overflow', () => {
        // `overflow-hidden` on both axes clipped the story beats toolbar:
        // 220px and 6 controls (Narrate / Export / Publish / Add) outside the
        // viewport at 768x1024.
        const layout = read('components/Layout.jsx');
        expect(layout).not.toContain('"flex flex-col overflow-hidden"');
        expect(layout).toContain('overflow-y-auto overflow-x-auto');
    });
});

describe('the tap-target floor cannot be allowed to overflow a dense chart', () => {
    it('no-touch-padding stays a working opt-out', () => {
        // Re-imposing the 44px floor on `no-touch-padding` is what made the
        // 48-bar GalleryDateRail 48 x 44 = 2,112px wide inside a 360px rail.
        const css = read('index.css');
        const block = css.match(/button\.no-touch-padding,\s*\n\s*a\.no-touch-padding\s*\{[^}]*\}/);
        expect(block).toBeTruthy();
        expect(block[0]).toContain('min-height: auto');
        expect(block[0]).toContain('min-width: auto');
    });

    it('there is exactly one no-touch-padding opt-out rule', () => {
        // Two copies existed briefly; the duplicate made the later edits apply
        // to one copy while the other still floored the chart.
        const css = read('index.css');
        const matches = css.match(/button\.no-touch-padding/g) || [];
        // Two occurrences per rule: the selector and the `:not()` in the padding
        // rule. Anything more means a duplicate block crept back in.
        expect(matches.length).toBeLessThanOrEqual(3);
    });

    it('the date rail marks itself exempt and hittable', () => {
        const rail = read('components/dashboard/GalleryDateRail.jsx');
        expect(rail).toContain('no-touch-padding');
        expect(rail).toContain('chart-mark');
        // The rail scrolls rather than clipping, so all 48 bars stay reachable.
        expect(rail).toMatch(/date-rail-bars.*overflow-x-auto/);
    });

    it('chart-mark is specific enough to beat the opt-out rule', () => {
        // `button.no-touch-padding` is (0,1,1). A bare `.chart-mark` is (0,1,0)
        // and loses outright — measured `min-width: auto` on the bars and a
        // computed width of 4.97px.
        const css = read('index.css');
        expect(css).toMatch(/button\.chart-mark,\s*\n\s*a\.chart-mark\s*\{\s*\n\s*min-width: 0\.5rem;/);
    });
});

describe('a fixed overlay must not sit on the primary action', () => {
    it('the gallery FAB clears the mobile action bar', () => {
        // The bar is `fixed bottom-0` at z-30, 81px tall. The FAB was
        // `bottom-6` (24px) at z-40, i.e. inside it: measured over a 24x24
        // grid, 22% of the Generate button's area on /generate and 16% on
        // /img2img and /inpaint.
        const layout = read('components/generator/UnifiedGeneratorLayout.jsx');
        const fab = layout.match(/className="fixed bottom-\S+ right-6[^"]*"/);
        expect(fab).toBeTruthy();
        expect(fab[0]).not.toContain('bottom-6 ');
        expect(fab[0]).toContain('bottom-28');
    });
});

describe('flex rows that cannot fit must be allowed to shrink or wrap', () => {
    const cases = [
        ['components/generator/SamplingSettings.jsx', 'seed + two 48px dice overflowed 8px at 360px'],
        ['components/model-manager/DiscoverTab.jsx', 'the URL-import button was 11px outside the viewport'],
    ];
    for (const [file, why] of cases) {
        it(`${file} — ${why}`, () => {
            const src = read(file);
            // At least one shrinkable control per file, i.e. min-w-0 present.
            expect(src).toContain('min-w-0');
        });
    }

    it('Prompts action row wraps', () => {
        expect(read('pages/Prompts.jsx')).toMatch(/flex gap-2 flex-wrap/);
    });

    it('Statistics tab groups wrap at tablet width', () => {
        // Two `w-fit` groups of 4 buttons exceeded 768px, so "30D" and
        // "ALL TIME" were outside the viewport.
        expect(read('pages/Statistics.jsx')).toMatch(/sm:flex-row gap-3 flex-wrap/);
    });

    it('ProviderListItem keeps a name width and wraps its action row', () => {
        const src = read('components/providers/ProviderListItem.jsx');
        // `min-w-0` alone let the badge row take the whole card and the
        // provider name render at 0px from 640px up.
        expect(src).toContain('sm:min-w-[14rem]');
        expect(src).toMatch(/justify-end w-full sm:w-auto min-w-0 flex-wrap/);
    });

    it('SettingGroup two-column layout starts at lg, not md', () => {
        // A <select>'s automatic minimum is its longest option, so flex-shrink
        // cannot fit a 256px control in a 768px row.
        const src = read('pages/Settings.jsx');
        expect(src).toMatch(/flex flex-col lg:flex-row/);
    });
});
