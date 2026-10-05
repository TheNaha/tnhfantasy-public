/**
 * One byte formatter, and no way to add a second one.
 *
 * Nine ad-hoc copies of the same arithmetic shipped, and they disagreed: the
 * same 2 GB checkpoint rendered as `2048 MB` in the installed-models table,
 * `2.00 GB` in the model detail modal, `2048MB` in the generator's checkpoint
 * dropdown and `2.0 GB` in the model picker. A fourth copy read `size_kb` from
 * the API and divided it by 1024 twice to reach "GB", which is right, and a
 * fifth read the same field as MB — so the identical field rendered as both,
 * in the same panel.
 *
 * The class is not the arithmetic, it is that each call site re-derived the
 * unit ladder from nothing. So this asserts the *class*: no line in production
 * source may round a number next to a byte-unit token, except the one module
 * that owns the ladder.
 *
 * Generated, not listed: the check is "a rounding call and a byte unit on the
 * same line", so a tenth copy fails whether it divides by 1024, by 1048576, or
 * uses `Math.round`. An explicit per-site exemption list would just be a
 * hand-maintained list that rots, which is the defect it is meant to catch.
 */
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..');
const WALK_SKIP = new Set(['node_modules', 'dist']);

function sourceFiles(dir = SRC, acc = []) {
    for (const entry of readdirSync(dir)) {
        if (WALK_SKIP.has(entry)) continue;
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) sourceFiles(full, acc);
        else if (/\.jsx?$/.test(entry) && !/\.test\.jsx?$/.test(entry)) acc.push(full);
    }
    return acc;
}

const stripComments = (source) => source
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');

/** The one file allowed to round next to a unit: it defines the ladder. */
const OWNS_THE_LADDER = 'bytes.js';

/** A rounding call, in any of the spellings that produce a display number. */
const ROUNDS = /\b(?:toFixed|toPrecision|toExponential)\s*\(|Math\.round\s*\(/;

/**
 * A byte unit as a standalone token, so `maxBytes` and `max_context_tokens`
 * do not match. `B` alone is included because whole bytes are printed with it.
 */
const BYTE_UNIT = /(^|[^\w])(?:B|KB|MB|GB|TB)($|[^\w])/;

function offendersIn(relPath, text) {
    const stripped = stripComments(text);
    const out = [];
    stripped.split('\n').forEach((line, index) => {
        if (!ROUNDS.test(line) || !BYTE_UNIT.test(line)) return;
        out.push(`${relPath}:${index + 1}  ${line.trim().slice(0, 120)}`);
    });
    return out;
}

describe('byte sizes are formatted in exactly one place', () => {
    const files = sourceFiles();

    it('read a non-trivial part of the tree', () => {
        expect(files.length).toBeGreaterThan(150);
    });

    it('the owning module still rounds and still declares the steps', () => {
        // Guards the allowlist below from becoming a blank cheque: if the
        // formatter is deleted or stops rounding, the exemption has to go too.
        const owner = join(SRC, 'utils', OWNS_THE_LADDER);
        expect(statSync(owner, { throwIfNoEntry: false }), `${OWNS_THE_LADDER} is missing`).toBeTruthy();
        const text = readFileSync(owner, 'utf8');
        expect(text).toMatch(ROUNDS);
        expect(text).toContain('export function formatBytes');
    });

    const offenders = files
        .map((f) => relative(SRC, f).split(sep).join('/'))
        .filter((rel) => rel !== `utils/${OWNS_THE_LADDER}`)
        .flatMap((rel) => offendersIn(rel, readFileSync(join(SRC, rel), 'utf8')));

    it('no production line rounds a number next to a byte unit', () => {
        expect(
            offenders,
            `these lines format bytes by hand — use formatBytes() from utils/${OWNS_THE_LADDER}:\n${offenders.join('\n')}`
        ).toEqual([]);
    });

    it('the scan can fail (canary)', () => {
        // The exact shape of the deleted ModelGridCard line.
        const reintroduced = 'const label = `${(file.size_kb / 1024 / 1024).toFixed(2)} GB`;';
        expect(offendersIn('canary.jsx', reintroduced)).toHaveLength(1);

        // And a copy that never mentions 1024, which the canary above would not
        // catch if the rule were `1024 && toFixed`.
        const literalDivisor = "const s = `${(file.size / 1048576).toFixed(2)} MB`;";
        expect(offendersIn('canary.jsx', literalDivisor)).toHaveLength(1);
    });

    it('does not flag rounding that is not a byte size', () => {
        const innocent = [
            'onChange(Number(val.toFixed(2)));',
            'const pct = ((top.count / total) * 100).toFixed(1);',
            '`${(activeChat.max_context_tokens / 1024).toFixed(0)}k tokens`',
            '`${(words / 1000).toFixed(1)}k words`',
            'const maxBytes = 50 * 1024 * 1024;',
        ];
        expect(innocent.flatMap((line) => offendersIn('innocent.jsx', line))).toEqual([]);
    });

    it('reads a real call site through the same path (the scan is wired up)', () => {
        const lightbox = readFileSync(join(SRC, 'components/dashboard/ImageLightbox.jsx'), 'utf8');
        expect(offendersIn('ImageLightbox.jsx', lightbox)).toEqual([]);
        expect(lightbox).toContain('formatBytes');
    });
});