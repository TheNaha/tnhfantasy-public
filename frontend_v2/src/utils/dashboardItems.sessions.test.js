import { describe, expect, it } from 'vitest';

import {
    buildSessionGroupedEntries,
    getSessionName,
    getSessionSortDate,
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

describe('getSessionSortDate', () => {
    it('prefers updated_at', () => {
        expect(getSessionSortDate(makeSession())).toBe(Date.parse('2026-09-27T14:40:00Z'));
    });

    it('falls back to start_at when updated_at is missing', () => {
        const { updated_at, ...withoutUpdate } = makeSession();
        expect(updated_at).toBeDefined();
        expect(getSessionSortDate(withoutUpdate)).toBe(Date.parse('2026-09-27T14:00:00Z'));
    });

    it('returns 0 rather than NaN for an empty row', () => {
        expect(getSessionSortDate({})).toBe(0);
        expect(getSessionSortDate(null)).toBe(0);
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
    const older = makeSession({ id: 'old', name: 'Older', updated_at: '2026-09-20T10:00:00Z' });
    const newer = makeSession({ id: 'new', name: 'Newer', updated_at: '2026-09-27T18:00:00Z' });
    const middle = makeSession({ id: 'mid', name: 'Middle', updated_at: '2026-09-25T10:00:00Z' });

    it('emits one entry per session instead of a date bucket', () => {
        const entries = buildSessionGroupedEntries([older, newer, middle]);

        expect(entries).toHaveLength(3);
        entries.forEach(([key, items]) => {
            expect(items).toHaveLength(1);
            expect(items[0].type).toBe('session');
            expect(key).toBe(`session-${items[0].sessionId}`);
        });
    });

    it('orders by updated_at desc, not by the session start', () => {
        const tricky = makeSession({
            id: 'tricky',
            name: 'Long stretch',
            start_at: '2026-09-01T00:00:00Z',
            updated_at: '2026-09-27T23:00:00Z',
        });

        const entries = buildSessionGroupedEntries([older, tricky, newer]);

        expect(entries.map(([, items]) => items[0].sessionId)).toEqual(['tricky', 'new', 'old']);
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

    it('still lets a recently curated session win', () => {
        const touched = [
            { id: 'a', name: 'alpha', updated_at: '2026-09-01T00:00:00Z', start_at: '2026-01-03T10:00:00Z' },
            { id: 'b', name: 'beta', updated_at: '2026-01-01T00:00:00Z', start_at: '2026-08-09T10:00:00Z' },
        ];
        const order = buildSessionGroupedEntries(touched, { sort: 'date_desc' })
            .map(([, items]) => items[0].sessionId);
        // `a` is older but was curated most recently, and that still wins.
        expect(order).toEqual(['a', 'b']);
    });
});
