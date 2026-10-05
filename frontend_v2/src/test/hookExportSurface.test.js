/**
 * Export hygiene for the directories this repo owns.
 *
 * A duplicate export under a shared name is not a tidiness problem — it is a
 * signature collision with no compiler support. `useTagVocabulary` existed
 * twice: `useGallery.js` exported `(prefix = '', options)` against
 * `useAssetTags.js`'s `({prefix, q, limit}, options)`, under two cache keys and
 * two api wrappers for one endpoint. Both call sites read
 * `import { useTagVocabulary }`, so nothing distinguished them, and handing a
 * bare string to the object signature destructured the string into `{0:'c',…}`,
 * left every option undefined, and quietly fetched the *unfiltered* vocabulary
 * with no error anywhere.
 *
 * The checks below are the three ways that happened, kept narrow enough to be
 * actionable. A wider rule would have flagged a dozen pre-existing pairings that
 * nobody has asked about, and a red suite nobody can clear stops being read.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..');
const HOOKS = join(SRC, 'hooks');
const STORE = join(SRC, 'store');
const API = join(SRC, 'api');

const productionFiles = (dir) => readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isFile() && /\.jsx?$/.test(e.name) && !/\.test\.jsx?$/.test(e.name))
    .map((e) => join(dir, e.name));

const HOOK_FILES = productionFiles(HOOKS);

/** `export function useThing(`, `export const useThing =`, … */
const EXPORTED_HOOK_NAME = /export\s+(?:async\s+)?function\s+(use[A-Z]\w*)|export\s+const\s+(use[A-Z]\w*)\s*=/g;

/** `api.get(`${BASE}/tags`, …)` — method plus path template. */
const API_CALL = /api\.(get|post|put|patch|delete)\(`\$\{[A-Z_]+\}(\/[^`]*)`/g;

describe('a hook name is declared in exactly one file', () => {
    it('holds across the whole hooks directory', () => {
        const declarations = new Map();
        for (const file of HOOK_FILES) {
            const src = readFileSync(file, 'utf8');
            for (const m of src.matchAll(EXPORTED_HOOK_NAME)) {
                const name = m[1] || m[2];
                if (!declarations.has(name)) declarations.set(name, []);
                declarations.get(name).push(file.split('/').pop());
            }
        }
        const duplicated = [...declarations.entries()]
            .filter(([, files]) => files.length > 1)
            .map(([name, files]) => `${name} in ${files.join(', ')}`);
        expect(duplicated).toEqual([]);
    });

    it('names the survivor, so the deletion cannot be silently reverted', () => {
        // `useTagVocabulary` is the one real case this file exists for. It is
        // asserted by name rather than by count so that adding a *second*
        // implementation of something else cannot make this pass for the wrong
        // reason.
        const owners = HOOK_FILES
            .filter((f) => /export\s+function\s+useTagVocabulary\b/.test(readFileSync(f, 'utf8')))
            .map((f) => f.split('/').pop());
        expect(owners).toEqual(['useAssetTags.js']);
    });
});

describe('no api module declares two wrappers for one method and path', () => {
    it('holds inside every api module', () => {
        // Two wrappers for one endpoint drift silently, because both keep
        // working: `assetsApi.tags` and `assetsApi.tagVocabulary` were both
        // `GET ${API_V2_BASE}/tags`, and they disagreed about how to strip empty
        // params — `assetsApi.tags` kept `0` and `false`, which its param filter
        // dropped.
        //
        // Keyed on the method as well as the path, because `GET`/`PUT`/`DELETE`
        // on one path is three endpoints that are supposed to sit together.
        const duplicates = [];
        for (const file of productionFiles(API)) {
            const src = readFileSync(file, 'utf8');
            const seen = new Map();
            for (const m of src.matchAll(API_CALL)) {
                const key = `${m[1].toUpperCase()} ${m[2]}`;
                seen.set(key, (seen.get(key) || 0) + 1);
            }
            for (const [key, n] of seen) {
                if (n > 1) duplicates.push(`${file.split('/').pop()}: ${key} x${n}`);
            }
        }
        expect(duplicates).toEqual([]);
    });
});

describe('useDebounce has one export name', () => {
    // Named rather than swept: thirteen hooks in this directory pair a named
    // export with a default, and turning that into a rule would be a migration
    // nobody asked for. What must not come back is a second way to spell this
    // one function, because its two spellings had different import conventions.
    it('has a named export', () => {
        expect(readFileSync(join(HOOKS, 'useDebounce.js'), 'utf8'))
            .toMatch(/export\s+function\s+useDebounce\b/);
    });

    it('has no default export', () => {
        // This used to assert the *transitional* state — a default alias kept
        // alive for `DiscoverTab.jsx`, the last default-import site. That site is
        // now a named import, so the alias is gone and the rule has flipped: a
        // second spelling of this function is now the failure, because its two
        // spellings had different import conventions and nothing but the import
        // line distinguished them.
        const debounce = readFileSync(join(HOOKS, 'useDebounce.js'), 'utf8');
        expect(debounce, 'one spelling of useDebounce, named').not.toMatch(/^export default useDebounce;/m);
    });

    it('is imported by name by every caller, including DiscoverTab', () => {
        const offenders = [];
        for (const file of productionFiles(HOOKS)) {
            const src = readFileSync(file, 'utf8');
            if (/^import useDebounce from/m.test(src)) offenders.push(file.split('/').pop());
        }
        expect(offenders).toEqual([]);

        const discoverTab = readFileSync(join(SRC, 'components/model-manager/DiscoverTab.jsx'), 'utf8');
        expect(discoverTab).toMatch(/^import \{ useDebounce \} from/m);
        expect(discoverTab).not.toMatch(/^import useDebounce from/m);
    });
});

describe('the generator store has no dead members', () => {
    /*
     * `lastAppliedModelType` was written on every auto-apply and read by nobody,
     * and it was `persist`ed — so it went to localStorage on every checkpoint
     * change, for a value no code could observe. `setControlnets`, `clearMask`
     * and `applyModelSettings` had no references at all, production or test.
     *
     * Stated rather than derived: a sweep that counted references would happily
     * accept a member used exactly once, in its own test, which is precisely the
     * shape `applyModelSettings` had.
     */
    const REMOVED = [
        'lastAppliedModelType',
        'setControlnets',
        'clearMask',
        'applyModelSettings',
    ];

    it('names no removed member anywhere in the store', () => {
        const src = readFileSync(join(STORE, 'generatorStore.js'), 'utf8');
        expect(REMOVED.filter((name) => new RegExp(`\\b${name}\\b`).test(src))).toEqual([]);
    });

    it('and none of them is referenced anywhere else under src', () => {
        const offenders = [];
        const walk = (dir) => {
            for (const entry of readdirSync(join(SRC, dir), { withFileTypes: true })) {
                const rel = `${dir}/${entry.name}`;
                if (entry.isDirectory()) {
                    walk(rel);
                } else if (/\.jsx?$/.test(entry.name) && !rel.endsWith('generatorStore.test.js')) {
                    const src = readFileSync(join(SRC, rel), 'utf8');
                    for (const name of REMOVED) {
                        if (new RegExp(`\\b${name}\\b`).test(src)) offenders.push(`${rel}: ${name}`);
                    }
                }
            }
        };
        for (const dir of ['hooks', 'store', 'utils', 'api', 'constants']) walk(dir);
        expect(offenders).toEqual([]);
    });

    it('keeps the auto-apply toggle and its setter, which are live', () => {
        // Deliberately adjacent to the removals above and deliberately not one of
        // them: another workstream is building a UI toggle for this pair, and the
        // table it feeds is the only thing that applies them.
        const src = readFileSync(join(STORE, 'generatorStore.js'), 'utf8');
        expect(src).toMatch(/autoApplyModelSettings:\s*true/);
        expect(src).toMatch(/setAutoApplyModelSettings:/);
        expect(src).toMatch(/const BASE_MODEL_SETTINGS = \{/);
    });
});