import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (p) => readFileSync(join(SRC, p), 'utf8');

/**
 * The gallery's list was changing length under the scroll position.
 *
 * Two independent causes, both found by walking a full scroll and reading
 * `scrollHeight` at each step rather than by looking at the page.
 *
 * `scrollHeight` is the length of the list. If it changes while the user is
 * sitting still, everything below the viewport moves relative to everything
 * above it, which is felt as a jump. Measured before the fixes: 15380 -> 15198
 * across 2000px of scrolling in session view, and 2386 -> 4134 in grid view.
 * After: 14210 at every scroll depth.
 */
describe('the gallery list length must not change while scrolling', () => {
    it('a collapsed session item is estimated at its real height', () => {
        // Every virtual item is rendered with `paddingBottom: 2rem`, and the
        // estimate has to include it. It did not: a collapsed session item
        // measured 135px (103px card + 32px padding) against an estimate of
        // 148px, so each row was 13px too tall and the list shrank by 13px per
        // row as they were measured.
        const src = read('components/dashboard/GroupedDashboardContent.jsx');
        expect(src).toMatch(/const SESSION_ITEM_PADDING = 32;/);
        expect(src).toMatch(/const SESSION_HEADER_HEIGHT = SESSION_CARD_HEIGHT \+ SESSION_ITEM_PADDING;/);
        // The old single constant is what drifted from the markup.
        expect(src).not.toMatch(/const SESSION_HEADER_HEIGHT = 148;/);
    });

    it('grid and list thumbnails reserve their real box', () => {
        // `aspectRatio="auto"` is the one ProgressiveImage setting that reserves
        // no space: a flat `h-32` until the bytes land, then a snap to the
        // image's natural height. Since a whole day is a single virtual item, the
        // shifts compounded — one day group went 1676px -> 3296px as its second
        // page loaded.
        const src = read('components/dashboard/GroupedDashboardContent.jsx');
        const callSites = src.match(/aspectRatio=\{[^}]*\}/g) || [];
        expect(callSites.some((c) => c.includes('aspectRatioFor'))).toBe(true);
        // No literal `auto` may survive in a className position.
        expect(src).not.toMatch(/^\s*aspectRatio="auto"\s*$/m);
    });

    it('the aspect ratio comes from the asset, not a guess', () => {
        // The assets carry width/height at the top level and under `metadata`.
        // Using them both reserves the box and stops the grid cropping: with a
        // real ratio `ProgressiveImage` fills with `object-cover`, and there is
        // nothing left to crop.
        const src = read('components/dashboard/GroupedDashboardContent.jsx');
        expect(src).toMatch(/function aspectRatioFor\(item\)/);
        expect(src).toMatch(/item\?\.width/);
        expect(src).toMatch(/item\?\.metadata\?\.width/);
        expect(src).toMatch(/LIBRARY_DEFAULT_ASPECT/);
    });
});

describe('a completed image job must refresh the library it appears in', () => {
    it('job.completed invalidates the gallery', () => {
        // The handler updated the job caches, invalidated the queue and fired a
        // toast — and never touched `['gallery']`, so the grid the user is
        // looking at stayed exactly as it was. The new image only appeared on a
        // tab refocus or a websocket reconnect, which is why it read as "needs a
        // refresh" rather than as a consistent bug.
        const src = read('hooks/useJobsRealtime.jsx');
        const termination = src.slice(src.indexOf('handleTermination'));
        expect(termination).toMatch(/type === 'completed' && isImageJob/);
        expect(termination).toMatch(/invalidateIfMounted\(\['gallery'\]\)/);
        // Counts move with every new asset too.
        expect(termination).toMatch(/invalidateIfMounted\(\['collections'\]\)/);
    });

    it('the job card is live, not polled', () => {
        // Worth pinning because the gallery's staleness made this look like
        // polling. It is not: both job queries poll *only* when the socket is
        // down, and there is a watchdog for the case where the socket claims to
        // be connected but events stop arriving.
        const active = read('hooks/useActiveJobs.js');
        expect(active).toMatch(/refetchInterval:[\s\S]{0,200}!wsConnected/);

        const status = read('hooks/useJobStatus.js');
        expect(status).toMatch(/if \(!jobId \|\| wsConnected\) return false;/);

        const realtime = read('hooks/useJobsRealtime.jsx');
        expect(realtime).toMatch(/requestReplay/);
        expect(realtime).toMatch(/watchdog/);
    });
});

describe('the favourite control on a session card', () => {
    it('is one control, not a star and a button in the same corner', () => {
        // A favourited card rendered a bare `<Star size={20}>` at `top-3 right-3`
        // *and* the `<button>` holding a 16px star at the same `top-3 right-3`:
        // two stars, two sizes, one corner. The button already fills its own star
        // when favourited, so the indicator was pure duplication.
        const src = read('components/dashboard/GroupedDashboardContent.jsx');
        const cornerStars = src.match(/absolute top-3 right-3/g) || [];
        expect(cornerStars).toHaveLength(1);
        expect(src).not.toMatch(/<Star\s+size=\{20\}\s+fill="currentColor"/);
    });

    it('is reachable on a touch device', () => {
        // `opacity-0 group-hover:opacity-100` means the control does not exist
        // where there is no hover: on a phone the favourite button was absent,
        // and a favourited card showed a star that did nothing when tapped.
        const src = read('components/dashboard/GroupedDashboardContent.jsx');
        const labelAt = src.indexOf("'Add to favorites'");
        expect(labelAt).toBeGreaterThan(-1);
        // The className precedes the aria-label on this button, so read backwards
        // from the label rather than forwards.
        const button = src.slice(Math.max(0, labelAt - 1200), labelAt + 400);
        expect(button).toMatch(/opacity-100 sm:opacity-0 sm:group-hover:opacity-100/);
        // Fixed box so it matches the selection chip opposite it.
        expect(button).toMatch(/h-8 w-8/);
        // The old hover-only form must not survive. Matched as a whole class
        // list, not as a bare `opacity-0` — the responsive form contains
        // `sm:opacity-0`, which a substring test would flag.
        expect(button).not.toMatch(/opacity-0 group-hover:opacity-100 transition-all/);
    });
});
