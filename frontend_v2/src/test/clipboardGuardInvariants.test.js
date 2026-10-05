import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';

/**
 * No source file may dereference `navigator.clipboard` directly.
 *
 * `navigator.clipboard` is `undefined` in a non-secure context. Measured on the
 * documented LAN host: `http://100.150.0.4:5174` reports
 * `{"secure":false,"clip":false}` while `http://localhost:5174` reports both
 * true — so every LAN and VPN user is on the broken side of that pair, and the
 * difference is invisible in a `localhost` test run.
 *
 * The failure mode is the reason this needs a rule rather than a habit. A
 * missing property throws a **synchronous** `TypeError`:
 *
 *     navigator.clipboard.writeText(x).then(ok).catch(fail)
 *                          ^ throws here; `.then`/`.catch` never attach
 *
 * The throw escapes the entire chain, so `.catch` is not a guard — it only
 * handles a promise that was never created. In `ExportModal.jsx` that throw
 * skipped the `onClose()` on the next line, stranding the modal on a
 * "link copied!" toast it had not earned with Publish still enabled, so the
 * next click published a second time.
 *
 * `utils/clipboard.js` guards the property and falls back to a textarea +
 * `execCommand`. This asserts that everything else goes through it.
 */

const SRC_DIR = join(process.cwd(), 'src');
const GUARD = join(SRC_DIR, 'utils', 'clipboard.js');

function collectSourceFiles(dir = SRC_DIR, out = []) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
        if (entry.name.startsWith('.') || entry.name === 'node_modules') continue;
        const full = join(dir, entry.name);
        if (entry.isDirectory()) collectSourceFiles(full, out);
        else if (/\.(jsx|js)$/.test(entry.name) && !/\.test\./.test(entry.name)) out.push(full);
    }
    return out;
}

const files = collectSourceFiles();

/** Comment text mentioning the API is fine; a dereference is not. */
const stripComments = (source) => source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');

describe('the clipboard guard is the only way to copy', () => {
    it('scanned a non-trivial number of files', () => {
        expect(files.length).toBeGreaterThan(100);
    });

    it('the guard itself is the one file allowed to touch navigator.clipboard', () => {
        const guard = stripComments(readFileSync(GUARD, 'utf8'));
        expect(guard).toContain('navigator.clipboard');
        // Both the property check and the method check: `navigator.clipboard`
        // alone is not enough, since `.writeText` is separately absent in
        // browsers that expose the object without the permission.
        expect(guard).toMatch(/navigator\.clipboard\s*&&\s*navigator\.clipboard\.writeText/);
        expect(guard).toContain('execCommand');
    });

    const offenders = files
        .filter((f) => f !== GUARD)
        .filter((f) => /navigator\s*\.\s*clipboard/.test(stripComments(readFileSync(f, 'utf8'))))
        .map((f) => relative(SRC_DIR, f));

    it('found no direct navigator.clipboard dereferences', () => {
        expect(offenders).toEqual([]);
    });

    it('catches a deliberately-introduced dereference (the canary must be able to fail)', () => {
        // The exact shape of the ExportModal defect, in isolation. If this
        // stops failing, the scan has gone blind the way a per-file review
        // goes blind.
        const offender = 'function publish(data) {\n  navigator.clipboard.writeText(data.url);\n}\n';
        expect(/navigator\s*\.\s*clipboard/.test(stripComments(offender))).toBe(true);
    });

    it('ignores a mention inside a comment, which is documentation not a call', () => {
        const documented = '/**\n * Do not use navigator.clipboard here — it is undefined on http.\n */\nexport const x = 1;\n';
        expect(/navigator\s*\.\s*clipboard/.test(stripComments(documented))).toBe(false);
    });
});