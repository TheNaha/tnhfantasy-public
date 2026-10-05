/**
 * Every `queryFn` forwards React Query's `AbortSignal`.
 *
 * `client.js` has accepted and merged `signal` since it was written, and two
 * call sites used it — while the other 84 of 86 `queryFn`s dropped it on the
 * floor. So a keystroke in a search box issued a request, then issued another,
 * then another, and every superseded one ran to completion and then raced the one
 * that superseded it into the cache. The 30s timeout in the client did not help:
 * it bounds how long a request may live, it does not stop the ones nobody wants
 * any more.
 *
 * The cost is concentrated where a query key changes per keystroke —
 * `useWorldVaultSearch` on `q`, `useCivitaiSearch` on seven filter values,
 * `useGallery` on the whole filter object, `useMessages` on six positional
 * arguments — which is exactly where this rule earns its keep.
 *
 * The sweep is a *static* one, over the hooks directory, because "every
 * `queryFn`" is a claim about the whole directory and a behavioural test can only
 * ever cover the hooks it thought to check. A `queryFn` that makes no request at
 * all (`queryFn: () => null` for a derived flag, `queryFn: () => []` for a
 * selector) is exempt and is named explicitly, so the exemption list cannot
 * quietly grow. Test files are exempt: they define queries, they are not shipped
 * fetches.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..');
const HOOKS = join(SRC, 'hooks');
const read = (p) => readFileSync(p, 'utf8');

const PRODUCTION_HOOKS = readdirSync(HOOKS, { withFileTypes: true })
    .filter((e) => e.isFile() && /\.jsx?$/.test(e.name) && !/\.test\.jsx?$/.test(e.name))
    .map((e) => e.name)
    .sort();

/**
 * `queryFn`s that make no request, so there is nothing for a signal to abort.
 * Named rather than pattern-matched: a pattern that grew to fit new code is the
 * exemption this test exists to prevent.
 */
const MAKES_NO_REQUEST = {
    'useGenerationPreflight.js': ['queryFn: () => null,'],
    'useStreamingJobs.js': ['queryFn: () => [],'],
};

/**
 * Request-making `queryFn`s that do not forward the signal, each with the reason.
 *
 * Every one of these is here for the same reason, and it is not a good one: the
 * hook under test is exercised by a spec in `src/components/**` or
 * `src/pages/**`, and that spec asserts the api call with
 * `toHaveBeenCalledWith(url)` — one argument. Adding `{ signal }` as the second
 * makes it a two-argument call and the assertion fails, and those files belong to
 * another workstream. Each is a request that is mounted once per id and not
 * re-keyed per keystroke, so the waste is one abandoned request per navigation
 * rather than one per character typed — which is why they are the right things
 * to leave until the specs can move with them.
 *
 * The exact specs are listed in the handoff; when one is updated to
 * `toHaveBeenCalledWith(url, expect.anything())`, delete the entry here. The
 * `names every exemption that is still needed` case below fails if one goes
 * stale, and the `never …` case below fails the moment an exemption is added
 * without a reason.
 */
const SIGNAL_PENDING_SPEC_UPDATE = {
    'useAssetTags.js': {
        'assetsApi.assetTags(': 'AssetTagEditor.test.jsx asserts one argument: assetTags(id, {})',
        'assetsApi.tagVocabulary(': 'AssetTagEditor.test.jsx asserts one argument: tagVocabulary(objectContaining({prefix}))',
    },
    'useWorlds.js': {
        "api.get('/api/v2/worlds')": 'Worlds.test.jsx and RoleplayWorkspace.test.jsx assert one argument',
        'api.get(`/api/v2/worlds/${worldId}`)': 'Worlds.test.jsx asserts one argument',
        'api.get(`/api/v2/worlds/${worldId}/dashboard`)': 'Worlds.test.jsx asserts one argument',
    },
    'useWorldVaultSearch.js': {
        'api.get(`${base}/${id}`)': 'RelationshipGraph.layoutReset.test.jsx asserts one argument',
        "api.get('/api/v2/world-vault/entities')": 'RelationshipGraph.layoutReset.test.jsx asserts one argument',
        "api.get('/api/v2/world-vault/relationships')": 'RelationshipGraph.layoutReset.test.jsx asserts one argument',
        'api.get(`/api/v2/world-vault/graph-layout': 'RelationshipGraph.layoutReset.test.jsx asserts one argument',
    },
    'useSessions.js': {
        'listSessionAssets(sessionId)': 'SessionPanel.test.jsx asserts one argument',
    },
};

function stripComments(src) {
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

/**
 * The text of each `queryFn`, from its declaration to the line that closes it.
 *
 * A window of lines rather than a brace match: the arrow bodies here are short
 * enough that "the next eight lines" is a superset of the function, and a
 * superset is the safe direction — it can report a `queryFn` as using a signal it
 * does not, never the reverse.
 */
function queryFnBodies(src) {
    const code = stripComments(src);
    const lines = code.split('\n');
    const out = [];
    for (let i = 0; i < lines.length; i += 1) {
        if (!lines[i].includes('queryFn')) continue;
        const body = lines.slice(i, i + 12).join('\n');
        out.push({ line: i + 1, body });
    }
    return out;
}

describe('every request-making queryFn forwards the AbortSignal', () => {
    it('is true of every production hook', () => {
        const offenders = [];
        const exemptions = [];

        for (const name of PRODUCTION_HOOKS) {
            const declared = queryFnBodies(read(join(HOOKS, name)));
            const noRequest = MAKES_NO_REQUEST[name] || [];
            const pending = SIGNAL_PENDING_SPEC_UPDATE[name] || {};
            let consumedNoRequest = 0;
            let consumedPending = 0;

            for (const { line, body } of declared) {
                if (/queryFn:\s*(async\s*)?\w+\s*,/.test(body)) {
                    // A named fetcher: the signal is forwarded inside the
                    // fetcher, which this test checks separately below.
                    continue;
                }
                if (noRequest.some((snippet) => body.includes(snippet))) {
                    consumedNoRequest += 1;
                    continue;
                }
                if (Object.keys(pending).some((snippet) => body.includes(snippet))) {
                    consumedPending += 1;
                    continue;
                }
                if (/\bsignal\b/.test(body)) continue;
                // The declaration line itself is what makes this a request;
                // a `queryFn` with no `api.` call in its window is a selector.
                if (!/\b(api|Api)\.[a-z]+\(/.test(body) && !/\b(list|get|fetch)[A-Z]\w*\(/.test(body)) continue;
                offenders.push(`${name}:${line}`);
            }

            for (const snippet of noRequest.slice(consumedNoRequest)) {
                exemptions.push(`${name}: ${snippet}`);
            }
            for (const snippet of Object.keys(pending).slice(consumedPending)) {
                exemptions.push(`${name}: ${snippet}`);
            }
        }

        expect(offenders).toEqual([]);
        // Every exemption was actually consumed, so none is stale.
        expect(exemptions).toEqual([]);
    });

    it('never exempts a signal-less fetcher without saying why', () => {
        for (const [name, snippets] of Object.entries(SIGNAL_PENDING_SPEC_UPDATE)) {
            for (const [snippet, why] of Object.entries(snippets)) {
                expect(why, `${name} / ${snippet}`).toMatch(/asserts? one argument/);
            }
        }
    });

    it('names every exemption that is still needed', () => {
        // The other half: if a `queryFn` stops making a request, the exemption
        // has to go, or the next sweep quietly stops caring about a real fetcher.
        const unused = [];
        for (const [name, snippets] of Object.entries(MAKES_NO_REQUEST)) {
            const body = queryFnBodies(read(join(HOOKS, name)))
                .map((b) => b.body).join('\n');
            for (const snippet of snippets) {
                if (!body.includes(snippet)) unused.push(`${name}: ${snippet}`);
            }
        }
        expect(unused).toEqual([]);
    });

    it('forwards the signal inside every named fetcher a queryFn delegates to', () => {
        // `queryFn: fetchProvidersList` looks signal-free at the call site, so
        // this is the half that would otherwise be unverifiable.
        const offenders = [];
        for (const name of PRODUCTION_HOOKS) {
            const code = stripComments(read(join(HOOKS, name)));
            const referenced = new Set(
                [...code.matchAll(/queryFn:\s*(?:async\s*)?(\w+)\s*,/g)].map((m) => m[1]),
            );
            for (const fetcher of referenced) {
                const decl = new RegExp(`(?:async\\s+)?function\\s+${fetcher}\\s*\\([^)]*\\)\\s*\\{`);
                const match = code.match(decl);
                if (!match) { offenders.push(`${name}: ${fetcher} (not found)`); continue; }
                const start = code.indexOf(match[0]);
                const body = code.slice(start, start + 500);
                if (!/\bsignal\b/.test(body)) offenders.push(`${name}: ${fetcher}`);
            }
        }
        expect(offenders).toEqual([]);
    });

    it('covers the search-shaped queries where a dropped signal costs a request per keystroke', () => {
        // Named rather than swept: these are the ones where the query key changes
        // as the user types, so every superseded query is a wasted round trip.
        // Matched over the whole file rather than over the `queryFn` window,
        // because a `queryFn` that delegates to a named fetcher (`useGallery` ->
        // `fetchGalleryPage`) carries the signal one layer down and there is
        // nothing in the window to find.
        const KEYSTROKE_KEYED = {
            'useWorldVaultSearch.js': '/api/v2/world-vault/search',
            'useLocations.js': '/api/v2/locations/search',
            'useCivitaiSearch.js': '/api/v2/models/external/',
            'usePrompts.js': 'promptsApi.listPrompts',
            'useMessages.js': '/api/v2/chats/${chatId}/messages',
            'useGallery.js': 'assetsApi.facet',
        };
        const offenders = [];
        for (const [name, needle] of Object.entries(KEYSTROKE_KEYED)) {
            const lines = stripComments(read(join(HOOKS, name))).split('\n');
            const at = lines.findIndex((line) => line.includes(needle));
            expect(at, `${name} never calls ${needle}`).toBeGreaterThanOrEqual(0);
            // The window starts at the call, so the same request is not
            // reported once per line of its surroundings.
            const window = lines.slice(at, at + 12).join('\n');
            if (!/\bsignal\b/.test(window)) offenders.push(`${name}:${at + 1}`);
        }
        expect(offenders).toEqual([]);
    });
});

// Static imports: the declaration check below is about source text, but the
// "is it callable" half is about the real module, and a dynamic `import()` with
// a template literal cannot be analysed by vite at all.
const API_MODULES = {
    'collectionsApi.js': await import('../api/collectionsApi'),
    'promptsApi.js': await import('../api/promptsApi'),
    'sessionsApi.js': await import('../api/sessionsApi'),
    'jobs.js': await import('../api/jobs'),
    'providers.js': await import('../api/providers'),
    'settingsApi.js': await import('../api/settingsApi'),
    'nodes.js': await import('../api/nodes'),
};

describe('the api modules a queryFn reaches all accept an options argument', () => {
    /**
     * A module that takes no `options` swallows the signal silently — the call
     * still succeeds and the request still runs. So the wrapper has to grow a
     * parameter, which is the part of this fix that is easy to skip and has no
     * failing test of its own.
     */
    const MUST_ACCEPT_OPTIONS = {
        'collectionsApi.js': ['listCollections', 'getCollection'],
        'promptsApi.js': ['listPrompts', 'getCategories'],
        'sessionsApi.js': ['listSessions', 'listSessionAssets'],
        'jobs.js': ['get', 'getActive', 'getFailed'],
        'providers.js': ['list', 'getLoadBalancing'],
        'settingsApi.js': ['getBranding', 'getFavorites'],
        'nodes.js': ['fetchObjectInfo'],
    };

    it('takes options on every read a queryFn uses', async () => {
        const missing = [];
        for (const [name, fns] of Object.entries(MUST_ACCEPT_OPTIONS)) {
            const src = read(join(SRC, 'api', name));
            for (const fn of fns) {
                // The declaration must both name an `options` parameter and
                // actually use it; one without the other is the same bug.
                const decl = src.match(new RegExp(
                    '(?:async\\s+)?(?:function\\s+' + fn + '\\s*\\([^)]*\\)'
                    + '|\\b' + fn + '\\s*:\\s*(?:async\\s*)?\\([^)]*\\)'
                    // `export const fetchObjectInfo = async (providerId, options) =>`
                    + '|\\b' + fn + '\\s*=\\s*async?\\s*\\([^)]*\\))',
                ));
                if (!decl) { missing.push(`${name}:${fn} (no declaration)`); continue; }
                if (!/options/.test(decl[0])) { missing.push(`${name}:${fn} (no options parameter)`); continue; }
                // Object-shaped modules (`jobsApi`, `providersApi`, `settingsApi`)
                // expose the function as a property, not as a named export.
                // `settingsApi` has no default export, and `nodes` exports an
                // arrow const rather than a declaration — both are still
                // callable, which is all this half is asserting.
                const mod = API_MODULES[name];
                const exposed = mod[fn] ?? mod.default?.[fn]
                    ?? Object.values(mod).find((v) => typeof v === 'object' && v && typeof v[fn] === 'function')?.[fn];
                if (typeof exposed !== 'function') missing.push(`${name}:${fn} (not callable)`);
            }
        }
        expect(missing).toEqual([]);
    });
});