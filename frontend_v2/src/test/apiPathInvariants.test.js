import { readdirSync, readFileSync } from 'fs';
import { join, relative } from 'path';
import { describe, it, expect } from 'vitest';

/**
 * No client path may need a redirect to resolve.
 *
 * Three backend routes are declared with a trailing slash — `@router.get("/")`
 * and friends — so their canonical path is `/a/b/`. Asking for `/a/b` does not
 * 404: FastAPI answers `307 Temporary Redirect` and re-issues the request. Every
 * such call costs an extra round trip and a redirect body to parse and discard,
 * silently, on a path nobody is looking at.
 *
 * Two of the three were being called the wrong way, live:
 *
 *   `GET  /api/v2/providers` — app-wide. The layout status dot mounts
 *        `useProvidersPageData`, so this was two extra round trips on *every
 *        page navigation* in the product.
 *   `GET/PUT/DELETE /api/v2/world-vault/graph-layout` — every World Vault page.
 *
 * A 307 is invisible in every other check here: the request succeeds, the tests
 * that assert on the resolved body pass, and nothing logs. So this reads the
 * literal path strings out of the source and compares them with the shape the
 * backend actually serves.
 *
 * The backend's canonical set is small and stable (three paths), so it is stated
 * here rather than imported — this test runs without importing the app.
 */

// `process.cwd()`, not `import.meta.url`: vitest runs with the project root
// as cwd, and the existing sibling guard (`queryErrorInvariants.test.jsx`) does
// the same. Deriving from the module URL breaks under the jsdom environment
// transform.
const SRC_DIR = join(process.cwd(), 'src');

/** Paths the backend serves WITH a trailing slash. Keep in step with openapi. */
const CANONICAL_TRAILING_SLASH = [
    '/api/v2/providers/',
    '/api/v2/models/',
    '/api/v2/world-vault/graph-layout/',
];

function collectSourceFiles(dir = SRC_DIR, out = []) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
        if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
        const full = join(dir, entry.name);
        if (entry.isDirectory()) collectSourceFiles(full, out);
        else if (/\.(js|jsx)$/.test(entry.name) && !/\.test\.jsx?$/.test(entry.name)) {
            out.push(full);
        }
    }
    return out;
}

const sourceFiles = collectSourceFiles();

/** Every literal `/api/...` string in the source, with its file and line. */
function literalApiPaths() {
    const found = [];
    for (const file of sourceFiles) {
        const source = readFileSync(file, 'utf8');
        const lines = source.split('\n');
        lines.forEach((line, index) => {
            // Only literal strings. A `${BASE}/thing` template is resolved by the
            // constants below; this rule is about the hand-written paths, which
            // is where both offenders were.
            for (const m of line.matchAll(/['"`](\/api\/[A-Za-z0-9_\-/.]*)['"`]/g)) {
                found.push({ path: m[1], file: relative(SRC_DIR, file), line: index + 1 });
            }
        });
    }
    return found;
}

describe('the scan found the paths it is meant to check', () => {
    it('walks src/ and finds plenty of literal API paths', () => {
        expect(sourceFiles.length).toBeGreaterThan(100);
        expect(literalApiPaths().length).toBeGreaterThan(50);
    });

    it('knows about the three trailing-slash routes', () => {
        expect(CANONICAL_TRAILING_SLASH.length).toBeGreaterThan(0);
    });
});

describe('no literal client path is missing a trailing slash the server requires', () => {
    const offenders = [];
    for (const { path, file, line } of literalApiPaths()) {
        if (path.length > 1 && path.endsWith('/')) continue;
        // Exact match only. All three canonical routes are leaves — none has a
        // sub-path — so `/api/v2/models/autopopulate-all` is NOT served with a
        // slash, and a `startsWith` test here produced ten false offenders on
        // the first run.
        const withSlash = `${path}/`;
        if (CANONICAL_TRAILING_SLASH.includes(withSlash)) {
            offenders.push(`${file}:${line} '${path}' → server serves '${withSlash}'`);
        }
    }

    it('has no offenders', () => {
        expect(offenders).toEqual([]);
    });
});

describe('the two paths that were measured redirecting', () => {
    // Named explicitly so a regression names itself. Both were confirmed
    // against the running stack: `GET /api/v2/providers` answered `307` with
    // `Location: /api/v2/providers/`.

    it('the provider collection is requested with its slash', async () => {
        const { COLLECTION_PATH } = await import('../api/providers.js');
        expect(COLLECTION_PATH).toBe('/api/v2/providers/');
    });
});

