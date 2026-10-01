/**
 * A title you cannot read is a control you cannot use.
 *
 * Every earlier mobile pass measured *reachability* — overflow, tap-target size,
 * accessible name — and all of it came back clean. The remaining defect was
 * invisible to all three: titles were truncated to a stub.
 *
 *   /models/installed   "PonyV7_fp8_fp16_All_In_One_Safetensors"  296px -> 93px  (68% cut)
 *   /lorebooks          "Vel Varren World Book"                  171px -> 90px  (47% cut)
 *   /worlds             "Coherence smoke"                        139px -> 78px  (44% cut)
 *
 * Two causes, and both are silent — nothing errors, nothing overflows the
 * viewport, the layout is "valid":
 *
 *  1. A `truncate` (single-line ellipsis) title sharing a `flex justify-between`
 *     row with a `shrink-0` action group. The title yields; the actions keep
 *     their width.
 *  2. A `grid-cols-2` card grid on a 360px screen — 127px columns — where model
 *     filenames are single unbroken tokens, so `line-clamp-2` has nothing to
 *     break on and the clamp does nothing.
 *
 * A related defect in the same rows: `opacity-0 group-hover:opacity-100` on the
 * action group. There is no hover on a touch device, so those buttons were
 * permanently invisible while still occupying layout width. They are also the
 * only route into a world / lorebook / location — the card itself is not
 * clickable — so hiding them on mobile would remove the way in rather than tidy
 * the layout.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (p) => readFileSync(join(SRC, p), 'utf8');

/** The entity name is the only thing identifying the row. */
const NAME_ELEMENTS = [
    ['pages/Worlds.jsx', /<h3 className="font-semibold text-white ([^"]*)">\{world\.name\}/],
    ['pages/Lorebooks.jsx', /<h3 className="font-medium text-white ([^"]*)">\{lb\.name\}/],
    ['pages/Locations.jsx', /<h3 className="font-semibold text-white ([^"]*)">\{location\.name\}/],
];

describe('entity names are legible on a phone, not truncated to a stub', () => {
    for (const [file, pattern] of NAME_ELEMENTS) {
        it(`${file} — the name wraps, and only truncates from sm: up`, () => {
            const classes = read(file).match(pattern)?.[1] ?? '';
            expect(classes).toMatch(/line-clamp-2/);
            // Truncation stays on wide screens where the card can show it all;
            // what must not happen is truncating at phone width.
            expect(classes).toMatch(/sm:truncate/);
            // A bare `truncate` with no responsive partner is the defect.
            expect(classes.split(/\s+/)).not.toContain('truncate');
        });
    }

    it('the model grid is single-column at phone width', () => {
        // 360px / 2 = 127px cards; the name then had 93px for 296px of text.
        const src = read('components/model-manager/InstalledTab.jsx');
        const grids = src.match(/grid grid-cols-[^"]*gap-6/g) || [];
        expect(grids.length).toBeGreaterThan(0);
        for (const g of grids) {
            expect(g).toMatch(/grid-cols-1\b/);
            expect(g).not.toMatch(/grid-cols-1(?!\s)/);
        }
    });

    it('long model filenames can actually wrap', () => {
        // `line-clamp-2` alone does nothing to a token with no break
        // opportunity, which is what every model filename is.
        const src = read('components/model-manager/InstalledTab.jsx');
        const name = src.match(/<h3 className="([^"]*)"[^>]*title=\{file\.display_name/);
        expect(name?.[1]).toMatch(/line-clamp-2/);
        expect(name?.[1]).toMatch(/break-words/);
    });
});

describe('hover-revealed controls are reachable on touch', () => {
    // `group-hover:` compiles to `:hover`, which a touch device does not
    // produce reliably. A row that is invisible-but-present still takes width
    // from the title, and on these cards it is the only route to the entity.
    const cards = [
        'pages/Worlds.jsx',
        'pages/Lorebooks.jsx',
        'pages/Locations.jsx',
    ];

    for (const file of cards) {
        it(`${file} — action row is visible at phone width`, () => {
            const src = read(file);
            expect(src).toMatch(/opacity-100 sm:opacity-0 sm:group-hover:opacity-100/);
            // The plain hover-only form must not survive in these cards.
            expect(src).not.toMatch(/"[^"]*\bopacity-0 group-hover:opacity-100\b/);
        });
    }
});

describe('the known extent of the hover-only pattern is recorded, not grown', () => {
    it('no new file has introduced one since this audit', () => {
        // `group-hover:opacity-100` on its own is the remaining, unfixed half of
        // this class: 38 occurrences across 12 files at the time of writing,
        // mostly in panels and modals rather than list cards. If a count is
        // recorded here it must not silently grow — the fix is
        // `opacity-100 sm:opacity-0 sm:group-hover:opacity-100`, and this test
        // is the reminder that the class is not closed.
        const files = [
            'components/chat/ChatContextPanel.jsx',
            'components/story/StoryContextPanel.jsx',
            'components/dashboard/GroupedDashboardContent.jsx',
            'components/characters/CharacterCard.jsx',
            'components/story/StoryBeatsPanel.jsx',
        ];
        const total = files.reduce(
            (n, f) => n + (read(f).match(/group-hover:opacity-100/g) || []).length,
            0
        );
        expect(total).toBeGreaterThan(0);
        // Bump this only when the count is genuinely reduced, with the reason.
        expect(total).toBeLessThanOrEqual(15);
    });
});
