import { describe, expect, it } from 'vitest';

import {
    buildSessionGroupedEntries,
    getSessionName,
    getSessionSortDates,
    toSessionItem,
    UNTITLED_SESSION_NAME,
} from './dashboardItems';

function makeSession(overrides = {}) {
    return {
        id: 's1',
        name: 'Autumn portraits',
        description: null,
        signature: 'ckpt:sd@2026-09-27T14:32',
        auto_detected: true,
        locked: false,
        workspace: 'main',
        start_at: '2026-09-27T14:00:00Z',
        end_at: '2026-09-27T14:40:00Z',
        image_count: 6,
        thumbnail: 'main/2026/09/27/a.png',
        created_at: '2026-09-27T14:00:00Z',
        updated_at: '2026-09-27T14:40:00Z',
        deleted_at: null,
        ...overrides,
    };
}

describe('getSessionName', () => {
    it('falls back to "Untitled session" for auto-detected rows with no name', () => {
        expect(getSessionName({ name: null })).toBe(UNTITLED_SESSION_NAME);
        expect(getSessionName({ name: '   ' })).toBe(UNTITLED_SESSION_NAME);
        expect(getSessionName({})).toBe(UNTITLED_SESSION_NAME);
    });

    it('trims a real name', () => {
        expect(getSessionName({ name: '  Winter run  ' })).toBe('Winter run');
    });
});

describe('getSessionSortDates', () => {
    // Sessions are ordered by their IMAGES: newest by the session's last image,
    // oldest by its first. This replaced a preference for `updated_at`, which
    // is a bookkeeping column — a library written in one transaction gives every
    // session the same value, so the sort silently did nothing.
    it('reads the generation window, not the bookkeeping column', () => {
        const session = makeSession();
        // `updated_at` is deliberately the most recent instant on the row, and
        // is still ignored: the images are what the sort means.
        expect(session.updated_at).toBe('2026-09-27T14:40:00Z');
        expect(getSessionSortDates(session)).toEqual({
            newest: Date.parse('2026-09-27T14:40:00Z'),
            oldest: Date.parse('2026-09-27T14:00:00Z'),
        });
    });

    it('falls back to the start when the session never ended', () => {
        const { end_at, ...open } = makeSession();
        expect(end_at).toBeDefined();
        const dates = getSessionSortDates(open);
        expect(dates.newest).toBe(Date.parse('2026-09-27T14:00:00Z'));
        expect(dates.oldest).toBe(Date.parse('2026-09-27T14:00:00Z'));
    });

    it('returns 0 rather than NaN for an empty row', () => {
        expect(getSessionSortDates({})).toEqual({ newest: 0, oldest: 0 });
        expect(getSessionSortDates(null)).toEqual({ newest: 0, oldest: 0 });
    });
});

describe('toSessionItem', () => {
    it('produces one unit keyed like an imageGroup and carries the row fields', () => {
        const item = toSessionItem(makeSession());

        expect(item.type).toBe('session');
        expect(item.id).toBe('session-s1');
        expect(item.sessionId).toBe('s1');
        expect(item.name).toBe('Autumn portraits');
        expect(item.imageCount).toBe(6);
        expect(item.autoDetected).toBe(true);
        expect(item.locked).toBe(false);
        expect(item.thumbnail).toBe('main/2026/09/27/a.png');
        expect(item.startAt).toBe('2026-09-27T14:00:00Z');
        expect(item.endAt).toBe('2026-09-27T14:40:00Z');
    });

    it('does not fetch members, so a list of sessions stays one request', () => {
        expect(toSessionItem(makeSession())).not.toHaveProperty('assets');
    });
});

describe('buildSessionGroupedEntries', () => {
    // These vary their IMAGE WINDOW, which is what the ordering reads. They used
    // to vary only `updated_at`, at which point all three tied on the new key and
    // the expectations below were decided by the id tiebreak rather than by any
    // sort — which is how a sort that does nothing can pass a test suite.
    const older = makeSession({
        id: 'old', name: 'Older',
        start_at: '2026-09-20T09:00:00Z', end_at: '2026-09-20T10:00:00Z',
        updated_at: '2026-09-27T18:00:00Z',
    });
    const newer = makeSession({
        id: 'new', name: 'Newer',
        start_at: '2026-09-27T17:00:00Z', end_at: '2026-09-27T18:00:00Z',
        updated_at: '2026-09-20T10:00:00Z',
    });
    const middle = makeSession({
        id: 'mid', name: 'Middle',
        start_at: '2026-09-25T09:00:00Z', end_at: '2026-09-25T10:00:00Z',
        updated_at: '2026-09-22T10:00:00Z',
    });

    it('emits one entry per session instead of a date bucket', () => {
        const entries = buildSessionGroupedEntries([older, newer, middle]);

        expect(entries).toHaveLength(3);
        entries.forEach(([key, items]) => {
            expect(items).toHaveLength(1);
            expect(items[0].type).toBe('session');
            expect(key).toBe(`session-${items[0].sessionId}`);
        });
    });

    it('newest first means the session containing the newest image leads', () => {
        // A session that started long ago but is still producing is what you are
        // looking for when you sort by newest — so it leads on its LAST image,
        // not on when its row was last written.
        const stillGoing = makeSession({
            id: 'tricky',
            name: 'Long stretch',
            start_at: '2026-09-01T00:00:00Z',
            end_at: '2026-09-28T23:00:00Z',
        });

        const entries = buildSessionGroupedEntries([older, stillGoing, newer]);
        expect(entries.map(([, items]) => items[0].sessionId)).toEqual(['tricky', 'new', 'old']);
    });

    it('oldest first means the session containing the oldest image leads', () => {
        // The mirror of the above, and the reason both directions are computed
        // rather than one with a sign flipped: a long-running session has a
        // different oldest and newest, and only the requested one decides.
        const stillGoing = makeSession({
            id: 'tricky',
            name: 'Long stretch',
            start_at: '2026-08-01T00:00:00Z',
            end_at: '2026-09-28T23:00:00Z',
        });

        const entries = buildSessionGroupedEntries(
            [older, stillGoing, newer],
            { sort: 'date_asc' },
        );
        expect(entries.map(([, items]) => items[0].sessionId)).toEqual(['tricky', 'old', 'new']);
    });

    it('honours date_asc', () => {
        const entries = buildSessionGroupedEntries([older, newer, middle], { sort: 'date_asc' });
        expect(entries.map(([, items]) => items[0].sessionId)).toEqual(['old', 'mid', 'new']);
    });

    it('breaks ties on id so the order is stable across refetches', () => {
        const stamp = '2026-09-27T10:00:00Z';
        const b = makeSession({ id: 'b', updated_at: stamp });
        const a = makeSession({ id: 'a', updated_at: stamp });

        const first = buildSessionGroupedEntries([b, a]).map(([, items]) => items[0].sessionId);
        const second = buildSessionGroupedEntries([a, b]).map(([, items]) => items[0].sessionId);

        expect(first).toEqual(second);
    });

    it('skips rows with no id and tolerates an empty list', () => {
        expect(buildSessionGroupedEntries([])).toEqual([]);
        expect(buildSessionGroupedEntries(undefined)).toEqual([]);
        expect(buildSessionGroupedEntries([makeSession(), { name: 'orphan' }])).toHaveLength(1);
    });
});

describe('the degenerate-timestamp case', () => {
    // A library created or re-indexed in one transaction gives every session the
    // SAME `updated_at`, to the microsecond. That is not hypothetical: in a
    // 1,411-session library every row carried `2026-09-27T07:46:12.265488Z`.
    // Sorting on `updated_at` alone then falls through to the id tiebreak, and
    // reversing the direction changes nothing — a control that moves and an
    // order that does not.
    const sameInstant = '2026-09-27T07:46:12.265488Z';
    const sessions = [
        { id: 'b', name: 'beta', updated_at: sameInstant, start_at: '2026-03-05T10:00:00Z' },
        { id: 'a', name: 'alpha', updated_at: sameInstant, start_at: '2026-01-03T10:00:00Z' },
        { id: 'c', name: 'gamma', updated_at: sameInstant, start_at: '2026-04-23T10:00:00Z' },
    ];

    it('breaks the tie on when the images were generated', () => {
        const desc = buildSessionGroupedEntries(sessions, { sort: 'date_desc' })
            .map(([, items]) => items[0].sessionId);
        const asc = buildSessionGroupedEntries(sessions, { sort: 'date_asc' })
            .map(([, items]) => items[0].sessionId);

        expect(desc).toEqual(['c', 'b', 'a']);
        expect(asc).toEqual(['a', 'b', 'c']);
    });

    it('orders by the images even when the bookkeeping column disagrees', () => {
        // `a` was curated most recently but its images are older. It used to win
        // on that, which is the behaviour this replaced: the ordering is now
        // about generations, and `updated_at` cannot move it.
        const touched = [
            { id: 'a', name: 'alpha', updated_at: '2026-09-01T00:00:00Z', start_at: '2026-01-03T10:00:00Z' },
            { id: 'b', name: 'beta', updated_at: '2026-01-01T00:00:00Z', start_at: '2026-08-09T10:00:00Z' },
        ];
        const order = buildSessionGroupedEntries(touched, { sort: 'date_desc' })
            .map(([, items]) => items[0].sessionId);
        expect(order).toEqual(['b', 'a']);
    });
});
