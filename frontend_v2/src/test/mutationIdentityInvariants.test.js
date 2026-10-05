/**
 * No dependency array may hold a whole `useMutation` result.
 *
 * React Query v5 returns a fresh result object from `useMutation` on every
 * render — `{ mutate, mutateAsync, isPending, error, data, … }`, rebuilt each
 * time — so `[someMutation]` in a dependency array is a promise that the memo or
 * callback around it never holds. Seven action callbacks in `useJobRecovery`
 * were built that way, which meant every consumer of that hook rebuilt them all
 * on every render, and a consumer that passes one into an effect or a memoised
 * child re-runs on every render forever.
 *
 * The fix is to destructure (`const { mutateAsync } = mutation`) and depend on
 * that, which `useFavorites.js:41` already documents. This asserts the shape
 * rather than the fix, so it also catches `useState`-with-a-query-object and
 * any future hook that returns a fresh literal.
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

/** Index just past the bracket/paren/brace that opens at `open`. */
function closing(text, open) {
    const pairs = { '(': ')', '{': '}', '[': ']' };
    const close = pairs[text[open]];
    let depth = 0;
    let quote = null;
    for (let i = open; i < text.length; i += 1) {
        const ch = text[i];
        if (quote) {
            if (ch === quote && text[i - 1] !== '\\') quote = null;
            continue;
        }
        if (ch === '"' || ch === "'" || ch === '`') { quote = ch; continue; }
        if (ch === '(' || ch === '{' || ch === '[') depth += 1;
        else if (ch === ')' || ch === '}' || ch === ']') {
            depth -= 1;
            if (depth === 0) return { index: i, close };
        }
    }
    return null;
}

/** The trailing dependency array of a hook call, e.g. `useCallback(fn, [a])`. */
function dependencyArray(call) {
    let quote = null;
    let depth = 0;
    let found = null;
    for (let i = 0; i < call.length; i += 1) {
        const ch = call[i];
        if (quote) {
            if (ch === quote && call[i - 1] !== '\\') quote = null;
            continue;
        }
        if (ch === '"' || ch === "'" || ch === '`') { quote = ch; continue; }
        if (ch === '(' || ch === '{') depth += 1;
        else if (ch === ')' || ch === '}') depth -= 1;
        else if (ch === '[' && depth === 0) {
            const end = closing(call, i);
            if (end) { found = call.slice(i + 1, end.index); i = end.index; }
        }
    }
    return found;
}

/** `const x = useMutation(`, and the destructuring that replaces depending on it. */
function mutationResultBindings(code) {
    const whole = new Set();
    for (const m of code.matchAll(/(?:const|let|var)\s+(\{[^}]*\}|[\w$]+)\s*(?::[^=]*?)?=\s*useMutation\s*(?:<[\s\S]*?>)?\(/g)) {
        if (!m[1].startsWith('{')) whole.add(m[1]);
    }
    const destructured = new Set();
    for (const m of code.matchAll(/(?:const|let|var)\s*\{([^}]*)\}\s*=\s*[\w$]+/g)) {
        for (const part of m[1].split(',')) {
            const alias = part.split(':').pop().trim();
            if (alias) destructured.add(alias);
        }
    }
    return { whole, destructured };
}

const HOOKS = /\buse(?:Callback|Memo|Effect)\s*\(/g;

function offendersIn(relPath, code) {
    const { whole } = mutationResultBindings(code);
    if (whole.size === 0) return [];
    const out = [];
    for (const m of code.matchAll(HOOKS)) {
        const hook = m[0].includes('Callback') ? 'useCallback'
            : m[0].includes('Memo') ? 'useMemo' : 'useEffect';
        const open = m.index + m[0].length - 1;
        const end = closing(code, open);
        if (!end) continue;
        const deps = dependencyArray(code.slice(open + 1, end.index));
        if (deps === null) continue;
        for (const name of whole) {
            const used = new RegExp(`(^|[^\\w.$])${name.replace(/\$/g, '\\$')}\\s*($|[,)\\]])`).test(deps);
            if (!used) continue;
            const line = code.slice(0, m.index).split('\n').length;
            out.push(`${relPath}:${line}  ${hook} depends on the whole mutation result '${name}'`);
        }
    }
    return out;
}

const files = sourceFiles().map((f) => ({
    rel: relative(SRC, f).split(sep).join('/'),
    code: stripComments(readFileSync(f, 'utf8')),
}));

describe('dependency arrays hold no whole mutation result', () => {
    it('found the production sources and the ones that build mutations', () => {
        expect(files.length).toBeGreaterThan(150);
        const withMutations = files.filter((f) => mutationResultBindings(f.code).whole.size > 0);
        expect(withMutations.length).toBeGreaterThan(3);
    });

    it('the destructuring pattern the fix depends on is still in use', () => {
        const { destructured } = mutationResultBindings(
            stripComments(readFileSync(join(SRC, 'hooks/useFavorites.js'), 'utf8'))
        );
        expect([...destructured]).toContain('mutate');
    });

    const offenders = files.flatMap(({ rel, code }) => offendersIn(rel, code));

    it('no memo, callback or effect depends on a whole mutation result', () => {
        expect(
            offenders,
            `depend on a fresh-per-render mutation object — destructure mutate/mutateAsync instead:\n${offenders.join('\n')}`
        ).toEqual([]);
    });

    it('useJobRecovery — the seven that shipped this way — is clean', () => {
        const { rel, code } = files.find((f) => f.rel === 'hooks/useJobRecovery.js');
        expect(rel).toBe('hooks/useJobRecovery.js');
        expect(offendersIn(rel, code)).toEqual([]);
        expect(code).toMatch(/const \{ mutateAsync: retryAsync \} = retryMutation;/);
    });

    it('can fail (canary)', () => {
        // The pre-fix shape, in isolation.
        const before = `
            const retryMutation = useMutation({ mutationFn: retry });
            const retryJob = useCallback((id) => retryMutation.mutateAsync(id), [retryMutation]);
        `;
        const after = `
            const retryMutation = useMutation({ mutationFn: retry });
            const { mutateAsync: retryAsync } = retryMutation;
            const retryJob = useCallback((id) => retryAsync(id), [retryAsync]);
        `;
        expect(offendersIn('canary.js', stripComments(before))).toHaveLength(1);
        expect(offendersIn('canary.js', stripComments(after))).toEqual([]);
    });
});