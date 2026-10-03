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
 * Known exemptions are listed with the reason they are not defects. Anything
 * added to that list needs a reason that survives the next person asking
 * "who reads this?".
 */

/** Leaves deliberately not read in the browser, with the reason. */
const EXEMPT = {
    // Read by App.jsx destructured into the React Query defaults:
    //   ui.animationDuration / ui.queryStaleTime / ui.queryCacheTime
    'ui.animationDuration': 'read in App.jsx via a destructured alias',
    'ui.queryStaleTime': 'read in App.jsx via a destructured alias',
    'ui.queryCacheTime': 'read in App.jsx via a destructured alias',
};

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
});
