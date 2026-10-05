import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Backend timestamps have no timezone. `new Date("2026-03-04T09:00:00")` parses
 * that as *local* time, so in any timezone west of Greenwich it renders as the
 * previous day — a memory saved on the 4th shown as the 3rd, a chat's "updated"
 * line off by one, a deployment's "Last Deployed" off by one.
 *
 * `src/utils/dateTime.js` exists for exactly this: `parseGalleryDate` treats a
 * bare datetime as UTC, and `formatTimestamp` is the one call site that wants a
 * full date+time. Eight render sites called `toLocaleDateString()` /
 * `toLocaleString()` on a raw `new Date(...)` and bypassed it.
 *
 * Scanned rather than rendered, deliberately: the failure is a timezone, and a
 * test that renders it would pass or fail on the runner's TZ. A scan fails in
 * every timezone, and names the file.
 */

const SRC_DIR = join(process.cwd(), 'src');

/**
 * Direct `new Date(<something>)` → locale formatting.
 *
 * `new Date()` with no argument is deliberately NOT matched: it is "now", there
 * is no timezone to get wrong, and the export header in
 * `ChatWorkspaceContext` uses it legitimately. Matching it would have been a
 * false positive in the first hour.
 */
const BYPASS = /new\s+Date\((?![\s)]*\))[^)]*\)\s*\.\s*toLocale(?:Date|Time)?String\s*\(/;

function collect(dir = SRC_DIR, out = []) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
        if (entry.name.startsWith('.') || entry.name === 'node_modules') continue;
        const full = join(dir, entry.name);
        if (entry.isDirectory()) collect(full, out);
        else if (/\.(jsx|js)$/.test(entry.name) && !/\.test\./.test(entry.name)) out.push(full);
    }
    return out;
}

/** The files this rule was written for, so a rename cannot silently unpin it. */
const ROUTED = [
    ['pages/RoleplayWorkspace.jsx', 'parseGalleryDate'],
    ['components/story/StoryContextPanel.jsx', 'parseGalleryDate'],
    ['components/chat/MemoriesPanel.jsx', 'parseGalleryDate'],
    ['components/generator/PromptCard.jsx', 'parseGalleryDate'],
    ['components/providers/tabs/DeployTab.jsx', 'formatTimestamp'],
    ['components/providers/tabs/RuntimeTab.jsx', 'formatTimestamp'],
];

describe('backend timestamps go through the shared normaliser', () => {
    const files = collect();

    it('finds something to scan', () => {
        expect(files.length).toBeGreaterThan(100);
        expect(statSync(join(SRC_DIR, 'utils/dateTime.js')).isFile()).toBe(true);
    });

    it('no component formats a raw `new Date(...)` with toLocale*String', () => {
        const offenders = files
            .map((file) => [relative(SRC_DIR, file), readFileSync(file, 'utf8')])
            .filter(([, source]) => BYPASS.test(source))
            .map(([rel, source]) => {
                const line = source.split('\n').findIndex((l) => BYPASS.test(l)) + 1;
                return `${rel}:${line}`;
            });

        expect(
            offenders,
            `Direct date formatting bypassing utils/dateTime.js:\n${offenders.join('\n')}\n` +
            'Use parseGalleryDate(value).toLocaleDateString(…) for a bare datetime, ' +
            'or formatTimestamp(value) for a full date+time.'
        ).toEqual([]);
    });

    it('every site this rule was written for now imports the normaliser it needs', () => {
        for (const [rel, fn] of ROUTED) {
            const source = readFileSync(join(SRC_DIR, rel), 'utf8');
            expect(source, `${rel} does not import ${fn}`).toContain(`import { ${fn} } from`);
            expect(source, `${rel} imports ${fn} but does not call it`).toContain(`${fn}(`);
        }
    });

    it('GalleryDateRail formats its UTC day buckets explicitly, and must keep doing so', () => {
        // Reported as a bypass and refuted, so it is pinned rather than left to
        // the scan: `formatDay()` receives a `YYYY-MM-DD` *day bucket* built with
        // `Date.UTC`, and formats it with an explicit `timeZone: 'UTC'`.
        // Routing it through `parseGalleryDate` would append a Z to an
        // already-UTC instant and then render it in local time — reintroducing
        // the exact off-by-one this file exists to prevent, for every user west
        // of Greenwich.
        const source = readFileSync(join(SRC_DIR, 'components/dashboard/GalleryDateRail.jsx'), 'utf8');
        expect(source).toMatch(/Date\.UTC\(year, month - 1, date\)/);
        expect(source).toMatch(/timeZone: 'UTC'/);
        // And it must not start importing the normaliser either: `parseGalleryDate`
        // appends a `Z` to a string that is already an instant, then renders it
        // in local time. That is the bug, not the fix.
        expect(source, 'GalleryDateRail must not route UTC day buckets through parseGalleryDate').not.toContain(
            'parseGalleryDate'
        );
    });

    it('the scan ignores `new Date()` with no argument (canary must be able to fail)', () => {
        // "Now" has no timezone to get wrong. Matching it would flag the export
        // header in ChatWorkspaceContext for no reason.
        expect(BYPASS.test('`Exported:** ${new Date().toLocaleString()}`')).toBe(false);
        expect(BYPASS.test('new Date(value).toLocaleDateString()')).toBe(true);
    });

    it('flags a site that bypasses the normaliser again (canary must be able to fail)', () => {
        const bad = 'export const d = (v) => new Date(v).toLocaleDateString();';
        const good = "export const d = (v) => parseGalleryDate(v).toLocaleDateString();";
        expect(BYPASS.test(bad)).toBe(true);
        expect(BYPASS.test(good)).toBe(false);
    });
});

describe('parseGalleryDate is what the normaliser is for', () => {
    it('reads a bare backend datetime as UTC', async () => {
        const { parseGalleryDate } = await import('../utils/dateTime.js');
        // The bare string, exactly as the API returns it. Without the Z this
        // parses as local midnight, which is the previous day for every user
        // west of Greenwich.
        expect(parseGalleryDate('2026-03-04T09:00:00').toISOString()).toBe('2026-03-04T09:00:00.000Z');
        // A real offset is respected rather than overwritten.
        expect(parseGalleryDate('2026-03-04T09:00:00+02:00').toISOString()).toBe('2026-03-04T07:00:00.000Z');
    });
});