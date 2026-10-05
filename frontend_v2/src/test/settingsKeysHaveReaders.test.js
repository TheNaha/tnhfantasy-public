import { describe, it, expect, beforeEach } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import useSettingsStore from '../store/settingsStore';

/**
 * Every key in `DEFAULT_SETTINGS` has to be read by something.
 *
 * `models.autoRemoveDownloads` shipped as a labelled switch on the Models
 * section of Settings for the life of the feature. It persisted to
 * localStorage, it rendered "Enabled"/"Disabled", and nothing read it — not
 * the Settings page, not a hook, not the backend. It was the single literally
 * non-functional control in the codebase, and it survived four audits and a
 * green suite, because a test that asserts "the default is true" passes just
 * as happily against a key nothing consumes.
 *
 * So this asserts the *property* rather than the value: walk every leaf of the
 * default tree and require a reader somewhere outside the store and outside
 * this test. A key with no reader is a switch that lies.
 *
 * An exemption can hide a key from this sweep, so one needs a reason that
 * survives the next person asking "who reads this?", plus something checkable
 * behind it — see `EXEMPT_REQUIRES`. The list is currently empty: all 35 leaves,
 * including the three that once needed an exemption, have a reader the sweep can
 * find.
 */

/**
 * Leaves deliberately not read in the browser, with the reason.
 *
 * Empty, and it was not always. It held `ui.animationDuration`,
 * `ui.queryStaleTime` and `ui.queryCacheTime` on the grounds that App.jsx reads
 * them "via a destructured alias" — it does, but `App.jsx:251,289,292` read
 * `queryUiSettings.animationDuration` and friends, which is text this sweep
 * already finds, so the three entries were removing keys that had readers.
 *
 * It is kept as a mechanism, not as a list, because the loophole it was is real:
 * before the staleness case below, any key could be retired from the sweep by
 * adding a line here with an arbitrary string, and nothing verified that the key
 * still existed or that the reason was still true. `querySignalInvariants` has
 * had that half since it was written; this now does too.
 */
const EXEMPT = {};

/**
 * What each exemption depends on, so "still needed" is checkable rather than a
 * matter of opinion: the alias the reader uses, and the React Query option that
 * alias feeds. An entry with no requirement here cannot be verified and is
 * rejected.
 */
const EXEMPT_REQUIRES = {};

/**
 * Every reason an entry is not still needed.
 *
 * Shared by the sweep and the canary below, so the canary exercises the code
 * that runs against the real list rather than a paraphrase of it.
 */
function exemptionProblems(entries, requires) {
    const problems = [];
    for (const [key, why] of Object.entries(entries)) {
        if (!(key in leaves)) {
            problems.push(`${key}: no longer a leaf of DEFAULT_SETTINGS — delete the entry`);
            continue;
        }
        if (!/via a destructured alias/.test(why)) {
            problems.push(`${key}: the reason no longer says why — "${why}"`);
            continue;
        }
        const [alias, consumer] = requires[key] ?? [];
        if (!alias || !consumer) {
            problems.push(`${key}: no EXEMPT_REQUIRES entry — a key retired by an arbitrary string`);
            continue;
        }
        if (!alias.test(corpus)) {
            problems.push(`${key}: nothing in src/ mentions ${alias} any more — delete the entry`);
            continue;
        }
        if (!consumer.test(corpus)) {
            problems.push(`${key}: ${alias} is no longer used, because no ${consumer} — delete the entry`);
        }
    }
    return problems;
}

function collectLeaves(value, prefix = '', out = {}) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
        for (const [k, v] of Object.entries(value)) {
            collectLeaves(v, prefix ? `${prefix}.${k}` : k, out);
        }
    } else {
        out[prefix] = value;
    }
    return out;
}

/** Every non-test source file, as one searchable blob, keyed by path. */
function readSources(dir, files = []) {
    for (const entry of readdirSync(dir)) {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) {
            if (entry === 'test' || entry === 'node_modules') continue;
            readSources(full, files);
        } else if (/\.(js|jsx)$/.test(entry) && !/\.test\.jsx?$/.test(entry)) {
            files.push(full);
        }
    }
    return files;
}

const SRC = join(process.cwd(), 'src');

/**
 * Comments do not count as readers.
 *
 * The first version of this test scanned the raw source and passed with the
 * dead key reinstated, because the comment left behind at the deletion site
 * still said `settings.autoRemoveDownloads`. A comment is the *most* likely
 * thing to mention a setting that nothing reads — it is written precisely to
 * explain that nothing reads it — so leaving them in makes the guard
 * decorative.
 *
 * A `//` inside a string literal (a URL) truncates the rest of that line, which
 * costs a little recall and cannot invent a false reader.
 */
const stripComments = (source) =>
    source.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:])\/\/.*$/gm, '$1');

const sourceFiles = readSources(SRC).filter(
    (f) => !f.endsWith('settingsStore.js') && !f.endsWith(join('test', 'settingsKeysHaveReaders.test.js'))
);
const corpus = sourceFiles.map((f) => stripComments(readFileSync(f, 'utf8'))).join('\n');
const DEFAULT_SETTINGS_REF = useSettingsStore.getState().settings;
const leaves = collectLeaves(DEFAULT_SETTINGS_REF);

describe('every settings key is read by something', () => {
    beforeEach(() => {
        // The store persists, so a previous test's mutations would leak in.
        useSettingsStore.setState({ settings: structuredClone(DEFAULT_SETTINGS_REF) });
    });

    it('read the source tree (guards against the walk matching nothing)', () => {
        expect(sourceFiles.length).toBeGreaterThan(100);
        expect(corpus.length).toBeGreaterThan(100_000);
    });

    it('has leaves to check', () => {
        expect(Object.keys(leaves).length).toBeGreaterThan(20);
    });

    const orphans = Object.keys(leaves).filter((key) => {
        if (EXEMPT[key]) return false;
        const leaf = key.split('.').pop();
        // A reader may name the leaf (`settings.gallery.itemsPerPage`) or the
        // section plus the leaf across a destructure (`itemsPerPage`). Both are
        // real reads; what must never happen is zero mentions outside the store.
        const sectionHits = new RegExp(`\\.${leaf}\\b`).test(corpus);
        const bareHits = new RegExp(`\\b${leaf}\\b`).test(corpus);
        return !(sectionHits || bareHits);
    });

    it('no key is declared and never read', () => {
        expect(orphans).toEqual([]);
    });

    it('names every exemption that is still needed', () => {
        expect(exemptionProblems(EXEMPT, EXEMPT_REQUIRES)).toEqual([]);
    });

    it('rejects each way an exemption could hide a dead key (canary)', () => {
        // Real leaf keys throughout, so each case is rejected for the reason it
        // is meant to model rather than by falling out of the "not a leaf" arm.
        expect(leaves['ui.animationDuration']).toBeDefined();

        // 1. An arbitrary reason and nothing to verify it against.
        expect(exemptionProblems(
            { 'ui.animationDuration': 'no reason at all' },
            EXEMPT_REQUIRES
        )).toEqual(['ui.animationDuration: the reason no longer says why — "no reason at all"']);

        // 2. The standard reason, but nothing that says it is still true.
        expect(exemptionProblems(
            { 'ui.animationDuration': 'read in App.jsx via a destructured alias' },
            EXEMPT_REQUIRES
        )).toEqual(['ui.animationDuration: no EXEMPT_REQUIRES entry — a key retired by an arbitrary string']);

        // 3. A requirement whose consumer no longer exists — the alias is still
        //    mentioned, but nothing is using it for the reason claimed.
        expect(exemptionProblems(
            { 'ui.animationDuration': 'read in App.jsx via a destructured alias' },
            { 'ui.animationDuration': [/animationDuration/, /noSuchReactQueryOption/] }
        )).toEqual(['ui.animationDuration: /animationDuration/ is no longer used, because no /noSuchReactQueryOption/ — delete the entry']);

        // 4. A key that is not a leaf of the settings tree any more.
        expect(exemptionProblems(
            { ui: 'read in App.jsx via a destructured alias' },
            { ui: [/queryUiSettings/, /staleTime/] }
        )).toEqual(['ui: no longer a leaf of DEFAULT_SETTINGS — delete the entry']);
    });
});
