import { describe, it, expect } from 'vitest';
import { nextOffsetPageParam } from './pagination';

const page = (files, total) => ({ files: Array.from({ length: files }, (_, i) => ({ name: `m${i}` })), total });

describe('nextOffsetPageParam', () => {
    it('stops once every row the server counted has been loaded', () => {
        const first = page(2, 2);
        expect(nextOffsetPageParam(first, [first], 2)).toBeUndefined();
    });

    it('stops one page early when the last page is exactly full', () => {
        const p1 = page(2, 4);
        const p2 = page(2, 4);
        expect(nextOffsetPageParam(p1, [p1], 2)).toBe(2);
        expect(nextOffsetPageParam(p2, [p1, p2], 2)).toBeUndefined();
    });

    it('asks for the next offset when the server trimmed a short page', () => {
        // 3 rows for `limit: 5` while `total` says 5 more exist: the old
        // InstalledTab rule stopped here and silently dropped rows.
        const p1 = page(3, 8);
        expect(nextOffsetPageParam(p1, [p1], 5)).toBe(3);
    });

    it('stops on the empty page rather than guessing a short page was the last', () => {
        const p1 = page(3, 8);
        const p2 = page(0, 8);
        expect(nextOffsetPageParam(p2, [p1, p2], 5)).toBeUndefined();
    });

    it('keeps walking when the server sends no total at all', () => {
        // What ModelSelector's `=== 50` did, minus the hard-coded page size.
        const p1 = { files: [{ name: 'a' }] };
        expect(nextOffsetPageParam(p1, [p1])).toBe(1);
        expect(nextOffsetPageParam({ files: [] }, [p1, { files: [] }])).toBeUndefined();
    });

    it('treats a zero or missing total as unknown, not as "nothing left"', () => {
        const p1 = page(2, 0);
        expect(nextOffsetPageParam(p1, [p1])).toBe(2);
        expect(nextOffsetPageParam({ files: [{ name: 'a' }] }, [[]])).toBe(1);
    });

    it('advances the cursor even when the page history does not add up', () => {
        // A `loaded` smaller than the rows just received would re-request the
        // offset it is already at, and the list would never grow.
        expect(nextOffsetPageParam({ files: [{ name: 'a' }, { name: 'b' }] }, [[]])).toBe(2);
    });

    it('never returns a zero offset, which would refetch the first page forever', () => {
        expect(nextOffsetPageParam({ files: null, total: 10 }, [{ files: null }])).toBeUndefined();
        expect(nextOffsetPageParam(undefined, undefined)).toBeUndefined();
    });

    it('does not loop when every page comes back short', () => {
        // A server that returns one row per page while `total` says 999: each
        // step advances the cursor by one, and the walk ends on the empty page.
        const server = (offset) => page(offset < 3 ? 1 : 0, 999);
        const seenOffsets = [];
        const pages = [];
        let offset = 0;
        for (let i = 0; i < 10; i += 1) {
            const next = nextOffsetPageParam(server(offset), [...pages, server(offset)]);
            if (next === undefined) break;
            expect(next).toBeGreaterThan(offset);
            pages.push(server(offset));
            seenOffsets.push(next);
            offset = next;
        }
        expect(seenOffsets).toEqual([1, 2, 3]);
    });
});