/**
 * `ChatWorkspaceContext` publishes one memoised object holding every value the
 * chat workspace needs. Two defects lived in its dependency array:
 *
 *   1. `selectChat` was a key in the context value with NO entry in the
 *      dependency array. It happened to be safe only because
 *      `useCallback([activeChatId, navigate])` means its identity moves exactly
 *      when `activeChatId` moves, and `activeChatId` *is* a dependency — so the
 *      missing dep was masked. The moment `selectChat` gained a dependency of its
 *      own, consumers would have kept a stale closure.
 *
 *   2. `useChatWorkspaceData.js` carried a comment saying `worlds` was
 *      "deliberately NOT in the contextValue memo". It was in both the key list
 *      and the dependency array, and `ChatContextPanel` genuinely reads it (it
 *      feeds `NewChatModal`'s world picker). The false comment was the defect: it
 *      invited the next reader to "restore" the exclusion by deleting a
 *      dependency the panel needs.
 *
 * This asserts the rule — the dependency array and the published keys are the
 * same set — by parsing the file rather than trusting either list, so the next
 * key added on one side and forgotten on the other fails here.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..');
const CONTEXT = join(SRC, 'contexts', 'ChatWorkspaceContext.jsx');
const DATA_HOOK = join(SRC, 'hooks', 'useChatWorkspaceData.js');

const source = readFileSync(CONTEXT, 'utf8');

const MEMO_START = 'const contextValue = useMemo(() => ({';
const memoAt = source.indexOf(MEMO_START);
const depsOpen = source.indexOf('}), [', memoAt);
const keySrc = source.slice(memoAt + MEMO_START.length, depsOpen);
const depsClose = source.indexOf(']', depsOpen);
const depSrc = source.slice(depsOpen + 4, depsClose + 1);

/** `CHAT_PAGE_SIZE, MAX_MESSAGE_PAGES, ...` — entries are one-per-line here. */
const parseList = (text) =>
    text
        .split(/[,\n]/)
        .map((s) => s.trim())
        .filter((s) => s && /^[A-Za-z_$][\w$]*$/.test(s));

const keys = parseList(keySrc);
const deps = parseList(depSrc);

/**
 * Module constants that legitimately appear in the published value but are
 * immutable for the lifetime of the module, so they cannot go stale and do not
 * need to be dependencies.
 */
const CONSTANTS = new Set(['CHAT_PAGE_SIZE', 'MAX_MESSAGE_PAGES', 'MESSAGE_PAGE_SIZE']);

describe('ChatWorkspaceContext memo dependency hygiene', () => {
    it('parsed both lists and they are non-trivial', () => {
        expect(keys.length).toBeGreaterThan(50);
        expect(deps.length).toBeGreaterThan(50);
    });

    it('publishes no duplicate keys', () => {
        const dupes = keys.filter((k, i) => keys.indexOf(k) !== i);
        expect(dupes, `duplicate context keys: ${[...new Set(dupes)].join(', ')}`).toEqual([]);
    });

    it('has no duplicate dependencies', () => {
        const dupes = deps.filter((d, i) => deps.indexOf(d) !== i);
        expect(dupes, `duplicate dependencies: ${[...new Set(dupes)].join(', ')}`).toEqual([]);
    });

    it('every published key is a dependency, so the memo can never serve a stale one', () => {
        const missing = [...new Set(keys)].filter((k) => !CONSTANTS.has(k) && !deps.includes(k));
        expect(
            missing,
            `these are published on the context value but absent from the ` +
            `useMemo dependency array: ${missing.join(', ')}`
        ).toEqual([]);
    });

    it('has no dependency that is not published, which is dead weight in the array', () => {
        const extra = [...new Set(deps)].filter((d) => !keys.includes(d));
        expect(
            extra,
            `these are dependencies but not published keys, so changing them ` +
            `recomputes and republishes the whole context for nothing: ${extra.join(', ')}`
        ).toEqual([]);
    });

    it('does not claim in a comment to exclude a value it actually publishes', () => {
        // The specific false claim that shipped: "Deliberately NOT in the
        // contextValue memo" next to a value that was in it.
        const hook = readFileSync(DATA_HOOK, 'utf8');
        const claimsExcluded = [...hook.matchAll(/(\w+)\s+is deliberately NOT in the|(\w+) is deliberately NOT in the/gi)];
        expect(
            claimsExcluded.map((m) => m[1] || m[2]).filter((name) => keys.includes(name)),
            'a comment claims a published context value is excluded from the memo'
        ).toEqual([]);
        // And the broader shape of the lie.
        expect(hook).not.toMatch(/deliberately NOT in the\s*\n?\s*contextValue memo/i);
    });
});