/**
 * The `world_vault` query-key namespace is written in exactly one place.
 *
 * `constants/queryKeys.js` exports `buildQueryKey()` and the `QUERY_KEYS`
 * namespace table, and they are imported by 26 files — the most-shared key
 * factory in the app. And yet 30 sites across 15 files hand-wrote
 * `['world_vault', 'chats']` instead of calling it, so the factory could not be
 * renamed, versioned or re-pointed in one place: every one of those sites was a
 * private copy of the same contract, and the copies were already drifting
 * (`useChats.js` built the chat root by hand while the very next line of the
 * same file built the system-prompt key through the factory).
 *
 * Two failure modes are pinned here:
 *
 *   1. A hand-written `['world_vault', …]` literal in production code. Every
 *      such site is a second source of truth for a namespace that already has a
 *      factory.
 *   2. A `QUERY_KEYS` member that no query actually hangs off. `buildQueryKey`
 *      unconditionally prepends `['world_vault', …]`, so a member for something
 *      the vault does not own can only build a key that matches nothing — and
 *      `GALLERY`/`PROVIDERS`/`SETTINGS`/`STATISTICS` were named exactly like real
 *      *non*-vault namespaces (`['gallery',…]`, `['providers-page','providers']`,
 *      `['settings_config']`, `['statistics','detailed',…]`), so a reader who
 *      reached for the factory to "find the gallery key" got a silent no-op.
 *
 * The byte-equivalence half matters as much as the no-literal half: a key that
 * changes *shape* silently unpairs every reader from its writer, and react-query
 * answers a mismatched key by refetching nothing. So the last block also asserts
 * that the factory produces the exact array each converted site used to write.
 *
 * Test files are exempt from (1) on purpose: they are supposed to name the wire
 * shape, and a test that re-derived its expectation from the factory would pass
 * against any shape at all. That is why the expectations here are literals.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';

const here = dirname(fileURLToPath(import.meta.url));
const SRC = join(here, '..');
const read = (p) => readFileSync(join(SRC, p), 'utf8');

/** Every .js/.jsx under `src/`, so a new file cannot opt out by being new. */
function walk(dir) {
    const out = [];
    for (const entry of readdirSync(join(SRC, dir), { withFileTypes: true })) {
        const rel = `${dir}/${entry.name}`;
        if (entry.isDirectory()) out.push(...walk(rel));
        else if (/\.jsx?$/.test(entry.name)) out.push(rel);
    }
    return out;
}

const isTestFile = (rel) => /\.test\.jsx?$/.test(rel);

const PRODUCTION_FILES = walk('.')
    .map((rel) => rel.replace(/^\.\//, ''))
    .filter((rel) => !isTestFile(rel))
    .sort();

/**
 * Blank out comments, preserving newlines and therefore line numbers, so a
 * reported `file:line` still points at the offending source line.
 *
 * A `//` inside a string literal (`'http://…'`) also blanks the rest of that
 * line. That direction of error is safe for this rule — it can only hide a
 * literal that shares a line with a URL, never invent one — and the app's
 * production `api/` modules use relative paths throughout.
 */
export function stripComments(src) {
    let out = '';
    let i = 0;
    while (i < src.length) {
        const ch = src[i];
        if (ch === '/' && src[i + 1] === '/') {
            const nl = src.indexOf('\n', i);
            const end = nl === -1 ? src.length : nl;
            out += ' '.repeat(end - i);
            i = end;
        } else if (ch === '/' && src[i + 1] === '*') {
            const close = src.indexOf('*/', i + 2);
            const end = close === -1 ? src.length : close + 2;
            out += src.slice(i, end).replace(/[^\n]/g, ' ');
            i = end;
        } else {
            out += ch;
            i += 1;
        }
    }
    return out;
}

/** A `['world_vault'` (or `"world_vault"`) written as the first key element. */
const HAND_WRITTEN_NAMESPACE = /\[\s*(['"`])world_vault\1\s*,/g;

/** 1-based line numbers of hand-written namespace literals in `text`. */
function sitesIn(text) {
    const src = stripComments(text);
    const out = [];
    let m;
    HAND_WRITTEN_NAMESPACE.lastIndex = 0;
    while ((m = HAND_WRITTEN_NAMESPACE.exec(src)) !== null) {
        out.push(src.slice(0, m.index).split('\n').length);
    }
    return out;
}

function sitesInFile(rel) {
    return sitesIn(read(rel));
}

/**
 * Production sites that still hand-write the namespace, named one by one.
 *
 * Empty in the directories this workstream owns (`hooks/`, `api/`,
 * `constants/`, `utils/`, `store/`) except for the one frozen file below. The
 * rest are owned by the components/pages workstream; each is a to-do with its
 * line pinned, so the entries cannot quietly go stale — the second test below
 * fails the moment a reported file is converted, forcing the entry out.
 *
 * The components/pages workstream has now converted every entry here that is not
 * the frozen one, which is why the table is down to a single row. The
 * byte-equivalence half of that work is pinned by the `CASES` table below.
 */
const REPORTED_OUTSTANDING = {
    'hooks/useChatStreaming.js': [231, 242, 243, 245],
};

const OWNED_DIRECTORIES = ['api', 'constants', 'hooks', 'store', 'utils'];

/** An owned directory does not mean an ownable file. */
const OWNED_DIRECTORY_EXCEPTIONS = {
    'hooks/useChatStreaming.js': 'mid-change in another workstream',
};

describe("no production file hand-writes the 'world_vault' namespace", () => {
    it('finds nothing in any directory this workstream owns', () => {
        const found = [];
        for (const rel of PRODUCTION_FILES) {
            const top = rel.split('/')[0];
            if (!OWNED_DIRECTORIES.includes(top)) continue;
            if (rel in OWNED_DIRECTORY_EXCEPTIONS) continue;
            for (const line of sitesInFile(rel)) found.push(`${rel}:${line}`);
        }
        expect(found).toEqual([]);
    });

    it('leaves every remaining literal a named to-do, with its line pinned', () => {
        const found = [];
        for (const rel of PRODUCTION_FILES) {
            for (const line of sitesInFile(rel)) found.push(`${rel}:${line}`);
        }
        const expected = Object.entries(REPORTED_OUTSTANDING)
            .flatMap(([rel, lines]) => lines.map((line) => `${rel}:${line}`))
            .sort();
        expect(found.sort()).toEqual(expected);
    });

    it('has not lost track of a site that was fixed — the exception list is exact', () => {
        for (const [rel, expectedLines] of Object.entries(REPORTED_OUTSTANDING)) {
            expect(sitesInFile(rel), `${rel} changed; update REPORTED_OUTSTANDING`).toEqual(expectedLines);
        }
        const outstanding = {};
        for (const rel of PRODUCTION_FILES) {
            const sites = sitesInFile(rel);
            if (sites.length > 0) outstanding[rel] = sites;
        }
        expect(Object.keys(outstanding).sort()).toEqual(Object.keys(REPORTED_OUTSTANDING).sort());
        // Every exception names a real file, so a typo cannot be a silent pass.
        for (const rel of Object.keys(REPORTED_OUTSTANDING)) {
            expect(PRODUCTION_FILES).toContain(rel);
        }
    });

    it('detects a hand-written literal, so the sweep is not vacuously green', () => {
        // Reverting any one conversion puts a literal back in a file this work
        // stream owns, and the first test names it. This pins that the matcher
        // itself still fires on a snippet shaped exactly like those violations,
        // so the first test cannot pass because the pattern stopped matching.
        expect(sitesIn("const k = ['world_vault', 'chats'];")).toEqual([1]);
        expect(sitesIn("const k = [\n  'world_vault',\n  'chats',\n];")).toEqual([1]);
        expect(sitesIn("// ['world_vault', 'chats'] in prose\nconst k = 1;")).toEqual([]);
        expect(sitesIn("/* ['world_vault','chats'] */ const k = 1;")).toEqual([]);
        expect(sitesIn("const k = ['gallery', 'dates'];")).toEqual([]);
    });
});

describe('every QUERY_KEYS member names a query that really lives under world_vault', () => {
    /**
     * Names that are *not* World Vault namespaces, mapped to the real namespace
     * their queries use instead. A name from this table must never appear as a
     * `QUERY_KEYS` member, because `buildQueryKey` would prefix it with
     * `world_vault` and produce a key that prefix-matches nothing.
     */
    const NON_VAULT_NAMESPACES = {
        GALLERY: 'gallery',
        PROVIDERS: 'providers-page',
        SETTINGS: 'settings_config',
        STATISTICS: 'statistics',
    };

    it('names no member that collides with a non-vault namespace', () => {
        expect(Object.keys(NON_VAULT_NAMESPACES).filter((name) => name in QUERY_KEYS)).toEqual([]);
    });

    it('cannot build a key that could be mistaken for a non-vault key', () => {
        for (const [name, value] of Object.entries(QUERY_KEYS)) {
            const built = buildQueryKey(value);
            expect(built[0], name).toBe('world_vault');
            expect(NON_VAULT_NAMESPACES, name).not.toHaveProperty(value);
        }
    });

    it('keeps the namespace names distinct, so a rename cannot hit two at once', () => {
        const { WORLD_VAULT, ...namespaces } = QUERY_KEYS;
        const values = Object.values(namespaces);
        expect(new Set(values).size).toBe(values.length);
    });
});

describe('buildQueryKey is byte-identical to every literal it replaced', () => {
    // Each expectation below is the array the converted site used to hand-write.
    // If `buildQueryKey` or a `QUERY_KEYS` value changes shape, one of these
    // goes red — which is the only thing standing between a rename and a silent
    // unpairing of every reader from its writer.
    const CASES = [
        // useChats.js:16 CHATS_ROOT_KEY and the keys derived from it
        [['world_vault', 'chats'], buildQueryKey(QUERY_KEYS.CHATS)],
        [['world_vault', 'chats', 'list'], [...buildQueryKey(QUERY_KEYS.CHATS), 'list']],
        [['world_vault', 'chats', 'c1'], buildQueryKey(QUERY_KEYS.CHATS, 'c1')],
        [['world_vault', 'chats', 'c1', 'system-prompt'], buildQueryKey(QUERY_KEYS.CHATS, 'c1', 'system-prompt')],
        [['world_vault', 'chats', 'c1', 'jobs'], buildQueryKey(QUERY_KEYS.CHATS, 'c1', 'jobs')],
        [['world_vault', 'chats', 'c1', 'images'], buildQueryKey(QUERY_KEYS.CHATS, 'c1', 'images')],
        [['world_vault', 'chats', 'list', 'search', 'q'], buildQueryKey(QUERY_KEYS.CHATS, 'list', 'search', 'q')],
        // useChats.js:202/231/235, and useMessages.js:8 query keys
        [['world_vault', 'messages', 'c1'], buildQueryKey(QUERY_KEYS.MESSAGES, 'c1')],
        [['world_vault', 'messages', 'c1', 100, 0, 'active', '', 'asc'],
            buildQueryKey(QUERY_KEYS.MESSAGES, 'c1', 100, 0, 'active', '', 'asc')],
        // useMessages.js:74/91/107
        [['world_vault', 'chats', 'c1'], buildQueryKey(QUERY_KEYS.CHATS, 'c1')],
        // useStoryStreaming.js:84-112
        [['world_vault', 'characters'], buildQueryKey(QUERY_KEYS.CHARACTERS)],
        [['world_vault', 'lorebooks'], buildQueryKey(QUERY_KEYS.LOREBOOKS)],
        [['world_vault', 'locations'], buildQueryKey(QUERY_KEYS.LOCATIONS)],
        [['world_vault', 'stories', 's1'], buildQueryKey(QUERY_KEYS.STORIES, 's1')],
        [['world_vault', 'stories', 's1', 'chapters'], buildQueryKey(QUERY_KEYS.STORIES, 's1', 'chapters')],
        [['world_vault', 'stories', 's1', 'images'], buildQueryKey(QUERY_KEYS.STORIES, 's1', 'images')],
        // useCollections.js:25
        [['world_vault', 'characters'], buildQueryKey(QUERY_KEYS.CHARACTERS)],
        // ChatWorkspaceContext.jsx:543 — the messages list for one chat, which is
        // a prefix of every paginated messages key `useMessages.js` writes.
        [['world_vault', 'messages', 'c1'], buildQueryKey(QUERY_KEYS.MESSAGES, 'c1')],
        // StorySandbox.jsx:528/564 (the retry + restore snapshots) and
        // 627/650/669/726/750 (the six beat/chapter mutations)
        [['world_vault', 'stories', 's1', 'chapters'], buildQueryKey(QUERY_KEYS.STORIES, 's1', 'chapters')],
        // Voices.jsx:51 — the whole voices list, after a preview job finished
        [['world_vault', 'voices'], buildQueryKey(QUERY_KEYS.VOICES)],
        // LorebookModal.jsx:48 and LocationModal.jsx:46 / Locations.jsx:160
        [['world_vault', 'lorebooks'], buildQueryKey(QUERY_KEYS.LOREBOOKS)],
        [['world_vault', 'locations'], buildQueryKey(QUERY_KEYS.LOCATIONS)],
    ];

    it.each(CASES)('builds %j unchanged', (literal, built) => {
        expect(built).toEqual(literal);
    });

    it('keeps the prefix first, so prefix invalidations still reach every key', () => {
        // The reason order matters and not only contents: these keys are all
        // *reached* by a shorter prefix — `['world_vault','chats']` reaching the
        // jobs query, `['world_vault']` reaching the whole vault.
        for (const name of Object.keys(QUERY_KEYS)) {
            if (name === 'WORLD_VAULT') continue;
            const built = buildQueryKey(QUERY_KEYS[name], 'x');
            expect(built).toEqual(['world_vault', QUERY_KEYS[name], 'x']);
        }
    });
});