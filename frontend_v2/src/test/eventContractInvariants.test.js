/**
 * The backend publishes a typed event vocabulary (`backend_v2/core/events.py`)
 * and the frontend mirrors it (`frontend_v2/src/api/websocket.js`). Three
 * defects lived in the gap between them, all found by the same three questions:
 *
 *   1. `reconciliation.failed` was emitted by the backend and listed in
 *      `TERMINAL_EVENT_TYPES`, but had NO frontend constant and NO subscriber.
 *      A worker failure left the provider card reading "reconciling" with no
 *      toast and no error while the database already held the failed status —
 *      the UI and the DB disagreed until a manual refetch. Its sibling
 *      `provider.deploy_failed` was handled, so this was an oversight.
 *
 *   2. `model.sync_progress` had a producer (`provider_sync.py` emits it on every
 *      `status == "downloading"` push) and a frontend constant, but no
 *      subscriber — so every download heartbeat was published to nobody.
 *
 *   3. The whole `download.*` family — four members plus the `emit_download_event`
 *      helper — had ZERO producers in production code and ZERO subscribers in
 *      the frontend, while the frontend mirrored all four constants. A contract
 *      on both sides, implemented by neither, which reads to the next person as
 *      "push-based download progress is already wired". It has been removed from
 *      both sides; model-download status is polled.
 *
 * These tests assert the three RULES, so the class cannot recur:
 *   - every backend `EventType` has a frontend constant with the same wire value
 *   - every backend `EventType` has at least one producer in production code
 *   - every backend `EventType` has at least one frontend subscriber
 */
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, '..');
// HERE is `frontend_v2/src/test`, so the backend is three levels up.
const BACKEND = join(HERE, '..', '..', '..', 'backend_v2');

const read = (p) => readFileSync(p, 'utf8');

const WALK_SKIP = new Set(['node_modules', 'dist', '__pycache__', 'e2e']);

/** Tests define contracts; they are not the code that implements them. */
const IS_TEST_FILE = /\.test\.jsx?$/;

function walk(dir, skip = new Set(), acc = []) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
        if (skip.has(entry.name)) continue;
        const full = join(dir, entry.name);
        if (entry.isDirectory()) walk(full, skip, acc);
        else if (/\.(py|jsx?)$/.test(entry.name) && !IS_TEST_FILE.test(entry.name)) acc.push(full);
    }
    return acc;
}

/**
 * `{ MEMBER: 'wire.value' }` from an enum body.
 *
 * The type annotation is optional because `JOB_CREATED: str = "job.created"` is
 * the same Enum member as `JOB_CREATED = "job.created"` — the first version of
 * this regex demanded the bare form, so a member written either way vanished
 * from the vocabulary and every check downstream quietly stopped seeing it. It
 * also accepts either quote style.
 */
function parseEnumMembers(body) {
    return Object.fromEntries(
        [...body.matchAll(/^\s*([A-Z_][A-Z0-9_]*)\s*(?::\s*[\w[\].]+\s*)?=\s*(['"])([^'"]+)\2/gm)]
            .map((m) => [m[1], m[3]])
    );
}

/** `{ MEMBER: 'wire.value' }` from the backend enum. */
function backendEventTypes() {
    const text = read(join(BACKEND, 'core', 'events.py'));
    return parseEnumMembers(enumBody(text, 'class EventType'));
}

/** `{ MEMBER: 'wire.value' }` from the frontend map. */
function frontendEventTypes() {
    const text = read(join(SRC, 'api', 'websocket.js'));
    const start = text.indexOf('export const EventTypes = {');
    const body = text.slice(start, text.indexOf('\n};', start));
    return Object.fromEntries(
        [...body.matchAll(/^\s*([A-Z_][A-Z0-9_]*)\s*:\s*(['"])([^'"]+)\2/gm)].map((m) => [m[1], m[3]])
    );
}

/**
 * The body of the class/const that starts at `declaration`, up to the next
 * line in column 0.
 */
function enumBody(text, declaration) {
    const lines = text.split('\n');
    const start = lines.findIndex((line) => line.trimStart().startsWith(declaration));
    if (start === -1) return '';
    for (let i = start + 1; i < lines.length; i += 1) {
        if (lines[i].trim() && !/^\s/.test(lines[i])) return lines.slice(start + 1, i).join('\n');
    }
    return lines.slice(start + 1).join('\n');
}

/**
 * `core/events.py` with the enum declaration cut out of it.
 *
 * Without this, the producer check matched every member against its own
 * definition line — `JOB_CREATED = "job.created"` contains `"job.created"` — so
 * all 23 members "had a producer" because the file that defines them counted as
 * one, and a member with no producer anywhere could never be reported. The two
 * `emit_*` helpers in that file are real producers and stay: only the
 * declaration block is removed.
 */
function producerSource(file) {
    const text = readFileSync(file, 'utf8');
    if (!file.endsWith(join('core', 'events.py'))) return text;
    return withoutEnumDeclaration(text);
}

/** The text of `core/events.py` minus its `class EventType` body. */
function withoutEnumDeclaration(text) {
    const lines = text.split('\n');
    const start = lines.findIndex((line) => line.trimStart().startsWith('class EventType'));
    if (start === -1) return text;
    let end = lines.length;
    for (let i = start + 1; i < lines.length; i += 1) {
        if (lines[i].trim() && !/^\s/.test(lines[i])) { end = i; break; }
    }
    return [...lines.slice(0, start + 1), ...lines.slice(end)].join('\n');
}

/**
 * Every production file whose text matches ANY of `patterns`.
 *
 * Call sites reference the constant (`EventType.JOB_CREATED`,
 * `ws.EventTypes.JOB_CREATED`) far more often than the wire value, and a few
 * legacy sites use the raw string, so both spellings count.
 */
function filesMatching(patterns, roots) {
    const hits = [];
    for (const [dir, skip] of roots) {
        if (!statSync(dir, { throwIfNoEntry: false })) continue;
        for (const file of walk(dir, skip)) {
            const text = producerSource(file);
            if (patterns.some((p) => text.includes(p))) hits.push(file);
        }
    }
    return hits;
}

const backendTypes = backendEventTypes();
const frontendTypes = frontendEventTypes();

const PY_SKIP = new Set(['node_modules', '__pycache__', '.venv', 'data', 'tests']);

const BACKEND_PROD_ROOTS = [
    [join(BACKEND, 'api'), PY_SKIP],
    [join(BACKEND, 'services'), PY_SKIP],
    [join(BACKEND, 'infrastructure'), PY_SKIP],
    [join(BACKEND, 'core'), PY_SKIP],
];
// `test` and `e2e` are skipped so a test asserting "X subscribes" cannot satisfy
// the production check; walking all of `src/` (rather than a directory list) is
// what catches a top-level subscriber such as `src/App.jsx`, which is where the
// global model-sync toasts live.
const FRONTEND_PROD_ROOTS = [
    [SRC, new Set(['node_modules', 'dist', '__pycache__', 'test', 'tests', 'e2e'])],
];

describe('backend/frontend event contract', () => {
    it('parsed a non-trivial vocabulary on both sides', () => {
        expect(Object.keys(backendTypes).length).toBeGreaterThan(15);
        expect(Object.keys(frontendTypes).length).toBeGreaterThan(15);
        // Equal on both sides is the property that makes the two directions
        // below mean something: a partial parse passes `> 15` on both sides
        // while quietly dropping the member it could not read.
        expect(Object.keys(backendTypes).sort()).toEqual(Object.keys(frontendTypes).sort());
    });

    it('reads a member written with a type annotation or either quote style', () => {
        // The canary for the parse itself: `JOB_CREATED: str = "job.created"` and
        // `JOB_CREATED = 'job.created'` are the same member as the shipped
        // `JOB_CREATED = "job.created"`, and the old regexes read only the last.
        expect(parseEnumMembers('    JOB_CREATED = "job.created"')).toEqual({ JOB_CREATED: 'job.created' });
        expect(parseEnumMembers('    JOB_CREATED: str = "job.created"')).toEqual({ JOB_CREATED: 'job.created' });
        expect(parseEnumMembers("    JOB_CREATED = 'job.created'")).toEqual({ JOB_CREATED: 'job.created' });
        expect(parseEnumMembers('    JOB_CREATED: str = \'job.created\'')).toEqual({ JOB_CREATED: 'job.created' });
        expect(parseEnumMembers('    TERMINAL_EVENT_TYPES = {')).toEqual({});
    });

    it('a member with no producer is reported, even though its own definition line exists', () => {
        // The producer search used to match `JOB_CREATED = "job.created"`
        // against the string `"job.created"` in the very same line, so the file
        // that defines a member counted as its producer and a dead member could
        // never be reported.
        const eventsPy = read(join(BACKEND, 'core', 'events.py'));
        const withoutDeclaration = producerSource(join(BACKEND, 'core', 'events.py'));
        expect(eventsPy).toContain('JOB_CREATED = "job.created"');
        expect(withoutDeclaration).not.toContain('JOB_CREATED');
        // The helpers in the same file are still producers — only the class body
        // is cut out.
        expect(withoutDeclaration).toContain('EventType.PROVIDER_STATS_UPDATE');
    });

    it('stops matching a member against its own declaration (canary)', () => {
        const deadMember = [
            'class EventType:',
            '    GHOST_EVENT = "ghost.event"',
            '',
            '',
            'async def emit_something_else():',
            '    await event_bus.publish(EventType.JOB_CREATED)',
        ].join('\n');

        // What the old scan did: the declaration line contains the wire value.
        expect(deadMember).toContain('"ghost.event"');

        // What the fixed scan does: the declaration is gone, so `ghost.event` is
        // no longer "found" and the member is reported as having no producer.
        const cut = withoutEnumDeclaration(deadMember);
        expect(cut).not.toContain('ghost.event');
        expect(cut).toContain('EventType.JOB_CREATED');
    });

    it('excludes test files from the production subscriber search', () => {
        // 141 co-located `*.test.js(x)` files sit beside the components they
        // test, and `walk()` only skipped directories named `test`, so every one
        // of them counted as a production subscriber: a test that asserts
        // "X subscribes" satisfied the production check by itself.
        const coLocated = [];
        const collect = (dir) => {
            for (const entry of readdirSync(dir, { withFileTypes: true })) {
                if (['node_modules', 'dist', 'test'].includes(entry.name)) continue;
                const full = join(dir, entry.name);
                if (entry.isDirectory()) collect(full);
                else if (IS_TEST_FILE.test(entry.name)) coLocated.push(full);
            }
        };
        collect(SRC);
        expect(coLocated.length).toBeGreaterThan(50);

        const walked = walk(SRC, new Set(['node_modules', 'dist', 'test']));
        expect(walked.filter((f) => IS_TEST_FILE.test(f))).toEqual([]);
        expect(walked.filter((f) => f.includes(join('src', 'test')))).toEqual([]);
    });

    it('every backend EventType has a frontend constant carrying the same wire value', () => {
        const problems = [];
        for (const [member, wire] of Object.entries(backendTypes)) {
            const fe = frontendTypes[member];
            if (fe === undefined) problems.push(`${member} ("${wire}") has no frontend constant`);
            else if (fe !== wire) problems.push(`${member}: backend "${wire}" vs frontend "${fe}"`);
        }
        // And the reverse: a frontend constant the backend cannot emit is a
        // subscription that can never fire.
        for (const [member, wire] of Object.entries(frontendTypes)) {
            if (!backendTypes[member]) problems.push(`frontend ${member} ("${wire}") is not an EventType`);
        }
        expect(problems, problems.join('\n')).toEqual([]);
    });

    it('every backend EventType is emitted somewhere in production code', () => {
        // `core/events.py` counts for the two members its `emit_*` helpers
        // publish — but its enum declaration block does not, which is why
        // `producerSource` cuts that block out. Tests and data do not count.
        const dead = [];
        for (const [member, wire] of Object.entries(backendTypes)) {
            const emitted = filesMatching(
                [`EventType.${member}`, `'${wire}'`, `"${wire}"`],
                BACKEND_PROD_ROOTS
            );
            if (emitted.length === 0) dead.push(`${member} ("${wire}") has no producer`);
        }
        expect(dead, dead.join('\n')).toEqual([]);
    });

    it('every backend EventType has at least one frontend subscriber', () => {
        const ignored = [];
        for (const [member, wire] of Object.entries(backendTypes)) {
            // `api/websocket.js` holds the map itself, which is not a subscriber.
            const subscribers = filesMatching(
                [`EventTypes.${member}`, `'${wire}'`, `"${wire}"`],
                FRONTEND_PROD_ROOTS
            ).filter((f) => !f.endsWith(join('api', 'websocket.js')));
            if (subscribers.length === 0) {
                ignored.push(`${member} ("${wire}") is emitted but nothing subscribes to it`);
            }
        }
        expect(ignored, ignored.join('\n')).toEqual([]);
    });

    it('the removed download.* family is gone from both sides', () => {
        // Named explicitly so that re-adding a producer-less `download.*` member
        // fails here with a reason rather than looking like a new feature.
        for (const member of ['DOWNLOAD_STARTED', 'DOWNLOAD_PROGRESS', 'DOWNLOAD_COMPLETED', 'DOWNLOAD_FAILED']) {
            expect(backendTypes[member], `${member} is back in the backend enum`).toBeUndefined();
            expect(frontendTypes[member], `${member} is back in the frontend map`).toBeUndefined();
        }
        const eventsPy = read(join(BACKEND, 'core', 'events.py'));
        expect(eventsPy).not.toContain('def emit_download_event');
    });
});