import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (p) => readFileSync(join(SRC, p), 'utf8');

/**
 * The gallery list must start at the top of its own container, and the container
 * must be tall enough to hold its last item.
 *
 * Both of these were broken by supplying `scrollMargin` to the virtualizer, and
 * both were reported as UI symptoms rather than as a virtualizer bug: "a big gap
 * between Filters and the image gallery" and "the infinite scroll just ends, the
 * last image got cropped".
 *
 * `scrollMargin` tells `@tanstack/react-virtual` where the list begins inside its
 * scroll element, and it *adds* that offset to `virtualItem.start`. The gallery
 * list sits 630px into its scroller (header, toolbar, date rail, filter panel), so
 * supplying it made index 0 render at `translateY(630px)` inside a container that
 * was already correctly positioned — a 630px gap between the filters and the first
 * image — and put the last item 630px past the container's bottom edge, which is
 * `overflow: hidden`, so it was clipped and unreachable.
 *
 * The comment that introduced it was right about half of it and drew the wrong
 * conclusion: `virtualItem.start` is container-relative and must not be *adjusted*
 * by hand, which is true, but passing `scrollMargin` is not the way to adjust it —
 * the library does that itself, and the container was already in the right place.
 */
describe('the gallery virtualizer must not displace its own list', () => {
    it('does not supply scrollMargin', () => {
        // Matched on the *option*, not the word: this file's comment explains at
        // length why it is not supplied, and a bare substring test flagged the
        // explanation.
        const src = read('hooks/useScrollRoot.js');
        expect(src).not.toMatch(/scrollMargin\s*[:,}]/);
        expect(src).not.toMatch(/\{[^}]*scrollMargin/);
    });

    it('does not pass it through in the options object', () => {
        const src = read('hooks/useScrollRoot.js');
        // The option must be absent from what actually reaches useVirtualizer,
        // not merely absent from a comment.
        const call = src.slice(src.indexOf('useVirtualizer('));
        expect(call).not.toMatch(/scrollMargin/);
    });

    it('records why, so it is not "corrected" a third time', () => {
        // This has now been tried and reverted once. Without the reason recorded
        // in the file, the next reader sees an unexplained `scrollMargin` on a
        // list that visibly sits below 600px of chrome and concludes it is
        // missing again.
        const src = read('hooks/useScrollRoot.js');
        expect(src).toMatch(/deliberately not accepted/);
    });
});

describe('the gallery container must be able to hold its last item', () => {
    it('a collapsed session estimate matches the rendered item', () => {
        // The other half of "infinite scroll jumps": every virtual item renders
        // with `paddingBottom: 2rem` and `estimateSize` must include it, or the
        // container is short by 13px per row and the list shrinks under the
        // scroll position. This one is load-bearing and independent of
        // `scrollMargin`.
        const src = read('components/dashboard/GroupedDashboardContent.jsx');
        expect(src).toMatch(/const SESSION_ITEM_PADDING = 32;/);
        expect(src).toMatch(
            /const SESSION_HEADER_HEIGHT = SESSION_CARD_HEIGHT \+ SESSION_ITEM_PADDING;/
        );
        expect(src).not.toMatch(/const SESSION_HEADER_HEIGHT = 148;/);
    });

    it('grid and list thumbnails reserve their real box', () => {
        // `aspectRatio="auto"` reserves nothing, so each thumbnail was a flat
        // `h-32` until it decoded and then snapped to its natural height, moving
        // everything below it.
        const src = read('components/dashboard/GroupedDashboardContent.jsx');
        expect(src).toMatch(/aspectRatio=\{aspectRatioFor\(/);
        expect(src).not.toMatch(/^\s*aspectRatio="auto"\s*$/m);
    });
});
