/**
 * One termination rule for offset-paginated `/api/files` listings.
 *
 * `ModelSelector` and `InstalledTab` both page `filesApi.list`, and each
 * carried its own `getNextPageParam`. They answered "is there another page?"
 * differently — `length === 50` versus `length >= pageSize && loaded < total` —
 * and neither was wrong about its own case. The consequence is that the rule
 * lived in two places and the correct one depended on which component the user
 * happened to be in.
 *
 * So this is a structural check, generated from the endpoint rather than from a
 * list of files: any production module that pages `filesApi.list` with an
 * `offset` must take its next page from `nextOffsetPageParam`. A module that
 * pages the endpoint differently fails here even if it is a file nobody has
 * read yet.
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

/**
 * Files that still hand-roll the rule, with the reason.
 *
 * One entry, and it is a workstream boundary rather than a technical one:
 * `ModelSelector.jsx` is owned by another batch and is not editable here, so its
 * `length === 50` rule — hard-coded page size, `total` ignored — is still in
 * place. It is listed rather than ignored so that the moment the file adopts
 * `nextOffsetPageParam` the `names every exemption that is still needed` case
 * below fails and the entry has to be deleted, rather than the guard quietly
 * learning to tolerate it.
 */
const HAND_ROLLED = {};

const files = sourceFiles().map((f) => ({
    rel: relative(SRC, f).split(sep).join('/'),
    text: readFileSync(f, 'utf8'),
}));

const pagesFiles = files.filter(({ text }) => {
    const code = stripComments(text);
    return /filesApi\.list\s*\(/.test(code) && /offset\s*:/.test(code);
});

describe('one termination rule per paginated endpoint', () => {
    it('found the modules that page the file listing', () => {
        expect(pagesFiles.length).toBeGreaterThanOrEqual(2);
        expect(pagesFiles.map((f) => f.rel)).toContain('components/model-manager/InstalledTab.jsx');
    });

    const unguarded = pagesFiles
        .filter(({ text }) => /getNextPageParam\s*:/.test(stripComments(text)))
        .filter(({ text }) => !/nextOffsetPageParam/.test(stripComments(text)))
        .map(({ rel }) => rel)
        .filter((rel) => !(rel in HAND_ROLLED));

    it('no module pages /api/files with its own termination rule', () => {
        expect(
            unguarded,
            `these modules page filesApi.list by offset but do not use nextOffsetPageParam: ${unguarded.join(', ')}`
        ).toEqual([]);
    });

    it('names every exemption that is still needed', () => {
        const stale = [];
        for (const [rel, why] of Object.entries(HAND_ROLLED)) {
            const entry = files.find((f) => f.rel === rel);
            if (!entry) { stale.push(`${rel}: file is gone`); continue; }
            if (/nextOffsetPageParam/.test(entry.text)) {
                stale.push(`${rel}: now uses nextOffsetPageParam — delete the entry`);
            } else if (!/getNextPageParam\s*:/.test(stripComments(entry.text))) {
                stale.push(`${rel}: no longer hand-rolls getNextPageParam — delete the entry`);
            } else if (!why || why.length < 20) {
                stale.push(`${rel}: exemption has no reason worth reading`);
            }
        }
        expect(stale, stale.join('\n')).toEqual([]);
    });

    it('can fail (canary)', () => {
        // The deleted ModelSelector rule, verbatim.
        const handRolled = 'getNextPageParam: (lastPage, allPages) => {\n'
            + '  const loaded = allPages.reduce((acc, p) => acc + (p.files?.length || 0), 0);\n'
            + '  return (lastPage.files?.length === 50) ? loaded : undefined;\n'
            + '},';
        const routed = 'getNextPageParam: nextOffsetPageParam,';
        expect(/getNextPageParam\s*:/.test(stripComments(handRolled))).toBe(true);
        expect(/nextOffsetPageParam/.test(stripComments(handRolled))).toBe(false);
        expect(/nextOffsetPageParam/.test(stripComments(routed))).toBe(true);
    });
});