import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryErrorState, QueryGate } from '../components/common/QueryState';

/**
 * A failed fetch must never be rendered as an empty vault.
 *
 * Seven pages rendered a failed fetch as "you have nothing":
 * `/roleplay`, `/characters`, `/lorebooks`, `/locations`, `/scenarios`,
 * `/personas` and `/voices`. Each destructured `data` and `isLoading` from its
 * query, read no `isError`, and fell through to "No Characters Found — you
 * haven't created any characters yet" with a working **Create** button, next to
 * a vault that already held three characters. Clicking that button makes a
 * duplicate.
 *
 * A per-page assertion would be a list of seven filenames, and the eighth page
 * would be written without one. This asserts the *rule* instead.
 *
 * ## Why this file was rewritten (2026-10-04)
 *
 * The previous version had two blind spots, and both of them hid a live,
 * reproduced defect:
 *
 *  1. It globbed `src/pages/*.jsx` only. The gallery's "No images yet" is
 *     rendered by `components/dashboard/DashboardGalleryGrid.jsx` — a
 *     component — and a 503 on the facet GET was reproduced live as
 *     `FAILED-FETCH: no-images-yet= true | CTA= true` next to a facet panel
 *     printing "Matching total unavailable" from the same query.
 *
 *  2. It detected "ships an empty state" by grepping for 8 hardcoded English
 *     strings. Copy changes are not defects, so the scan silently narrowed
 *     every time somebody reworded a title.
 *
 * The scan now walks all of `src/**` for `<EmptyState` call sites.
 *
 * ## The rule, stated so it cannot false-positive
 *
 * "Every file shipping `<EmptyState>` handles `isError`" is wrong, and
 * measurably so. `StorySandbox.jsx:1052` ships an empty state with no error
 * handling anywhere in the file — and it is CORRECT, because that empty state
 * is gated on `!activeStoryId`, which is local UI state derived from
 * `useParams()`, not from a query. A 503 from the stories endpoint cannot
 * reach it.
 *
 * So the rule is narrower and the test is precise about it:
 *
 *   **An empty state whose emptiness derives from a React Query result must be
 *   paired with that query's error state.**
 *
 * "Derives from query data" is decided by resolving the guard expression that
 * gates the `<EmptyState` to the identifier that produced it, and asking
 * whether that identifier is a `data` alias of a query hook — directly, via
 * one hop of local derivation (`displayed` from `memories`/`searchResults`), or
 * as a prop of a component that receives query data.
 */

const SRC_DIR = join(process.cwd(), 'src');
const PAGES_DIR = join(SRC_DIR, 'pages');

const readPage = (name) => readFileSync(join(PAGES_DIR, name), 'utf8');

/** Empty-state copy that means "you have nothing" rather than "this failed". */
const EMPTY_STATE_COPY = [
    'No Characters Found',
    "You haven't created any characters yet",
    'No lorebooks yet',
    'No locations yet',
    'No scenarios yet',
    'No personas yet',
    'No voice models yet',
    'Your next session will appear here',
];

const pages = readdirSync(PAGES_DIR).filter((f) => f.endsWith('.jsx') && !f.endsWith('.test.jsx'));

/**
 * Every non-test source file under `src/`, recursively.
 *
 * `readdirSync` with `withFileTypes` skips the node_modules symlinks and any
 * dot-directories, which a naive recursive walk would otherwise have to guard
 * against on every level.
 */
function collectSourceFiles(dir = SRC_DIR, out = []) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
        if (entry.name.startsWith('.') || entry.name === 'node_modules') continue;
        const full = join(dir, entry.name);
        if (entry.isDirectory()) collectSourceFiles(full, out);
        else if (/\.(jsx|js)$/.test(entry.name) && !/\.test\./.test(entry.name)) out.push(full);
    }
    return out;
}

/**
 * Does this source RENDER an error state?
 *
 * Matched at the JSX level, not on the bare identifier, and that distinction is
 * load-bearing. `/\bisError\b/` alone is satisfied by a destructured-but-unread
 * `isError` — which is exactly the defect: `Dashboard.jsx` destructured `isError`
 * nowhere, but other files destructure it and never branch on it, and a token
 * scan called those files compliant. Deleting the `<QueryErrorState>` branch
 * from a fixed file while leaving the import in place kept the suite green
 * until the match was tightened to the rendered element.
 *
 * The three accepted shapes are the shared component, its wrapper, and an
 * inline `role="alert"` — which is what `Worlds.jsx` and `Activity.jsx` use
 * instead of the shared component.
 */
function handlesQueryError(source) {
    return (
        /<QueryErrorState[\s/>]/.test(source)
        || /<QueryGate[\s/>]/.test(source)
        || /role=["']alert/.test(source)
    );
}

/**
 * Identifiers bound to a React Query `data` field: `const { data: foo = [] } = useX()`.
 *
 * Greedy rather than `[^}]*`: a default value may itself contain a brace
 * (`{ data: collections = {} }`), and a non-greedy body stops on that inner
 * `}`, fails the `}\s*=` that follows it, and silently yields no aliases at
 * all — which is what made `CollectionsPanel` invisible to the scan.
 */
function queryDataAliases(source) {
    const aliases = new Set();
    for (const m of source.matchAll(/const\s*\{([\s\S]*?)\}\s*=\s*use[A-Za-z0-9_]*\s*\(/g)) {
        for (const part of m[1].split(',')) {
            const name = part.trim().match(/^data\s*:\s*([A-Za-z0-9_$]+)/)?.[1];
            if (name) aliases.add(name);
            else if (/^data\s*$/.test(part.trim())) aliases.add('data');
        }
    }
    return aliases;
}

/** Local `const x = <expr>` bindings, one-line initialisers only. */
function localBindings(source) {
    const bindings = new Map();
    for (const m of source.matchAll(/const\s+([A-Za-z0-9_$]+)\s*=\s*([^;\n]+);/g)) {
        bindings.set(m[1], m[2]);
    }
    return bindings;
}

/** Props declared by a component in this file (function or arrow form). */
function componentProps(source) {
    const props = new Set();
    // Leading whitespace before `export`/`function` is required: these are
    // matched with `m`, and every real component in this repo is indented or
    // preceded by a blank line, so an anchored `^(?:export default )?` silently
    // matched nothing.
    const forms = [
        /^[ \t]*(?:export default )?(?:React\.memo\()?function\s+[A-Za-z0-9_$]+\s*\(([^)]*)\)/gm,
        /^[ \t]*(?:export default )?const\s+[A-Za-z0-9_$]+\s*=\s*\(([^)]*)\)\s*=>/gm,
        /^[ \t]*(?:export default )?const\s+[A-Za-z0-9_$]+\s*=\s*\{([^}]*)\}\s*=>/gm,
    ];
    for (const form of forms) {
        for (const m of source.matchAll(form)) {
            // Strip the destructuring braces before splitting, or the first
            // "prop" comes out as a literal `{` and the first real one is lost.
            for (const part of m[1].replace(/[{}[\]]/g, ' ').split(',')) {
                const name = part.trim().split(/[:=\s]/)[0];
                if (name && /^[A-Za-z0-9_$]+$/.test(name)) props.add(name);
            }
        }
    }
    return props;
}

/**
 * The identifiers in the expression that decides an `<EmptyState>` renders.
 *
 * Deliberately text-based and deliberately shallow. This is not a parser; it
 * answers one question — "does the condition guarding this empty state mention
 * something that came from a query?" — and a wrong answer here costs a
 * false-positive requirement in a test, so the logic that consumes the names is
 * kept just as small.
 *
 * Two branch shapes are read:
 *
 *  - `if (cond)` — the condition is parenthesised, so it is read directly.
 *  - `cond ? <EmptyState …/>` — the condition is the expression immediately
 *    before the `?`. Reading *after* the `?` is the obvious move and it is
 *    wrong: everything after it is the JSX branch, which contains the empty
 *    state's own markup and therefore no decision at all. With no `cond` on
 *    the same line — `) : events.length === 0 ? (` — it yields nothing and the
 *    scan goes blind on exactly the files it was written for.
 *
 * Both sides of the `?` are therefore collected and their identifiers unioned.
 * The trailing side is cut at the first `(`, newline or `<`, which is where
 * the JSX branch begins.
 */
function guardBefore(source, index) {
    const window = source.slice(Math.max(0, index - 400), index);

    const ifMatch = [...window.matchAll(/\bif\s*\(([^()]*)\)/g)].pop();
    const ternary = window.lastIndexOf('?');
    const afterIf = ifMatch ? ifMatch.index + ifMatch[0].length : -1;

    // An `if` whose condition is closer than any `?` is the branch point.
    if (afterIf !== -1 && (ternary === -1 || afterIf > ternary)) return ifMatch[1];

    if (ternary === -1) return null;

    const after = window.slice(ternary + 1);
    const stopAfter = after.search(/[(\n<>]/);
    const afterBranch = stopAfter === -1 ? after : after.slice(0, stopAfter);

    // The condition itself: the text from the last statement separator at
    // bracket depth 0 up to the `?`. `;`, `}` and a *block* `{` are the
    // separators, which is what stops the scan from reading back through
    // `const { data: activeStory } = useStory(...)` and matching its alias.
    //
    // A `{` is only a block when whitespace follows it. `{collectionList
    // .length === 0 ? (` is a JSX expression container, not a block, and
    // stopping there yields an empty guard and a silently blind scan — which is
    // the failure mode this whole rewrite exists to prevent.
    const before = window.slice(0, ternary);
    let depth = 0;
    let cut = -1;
    for (let i = before.length - 1; i >= 0; i -= 1) {
        const ch = before[i];
        if (ch === ')' || ch === ']' || ch === '}') depth += 1;
        else if (ch === '(' || ch === '[') {
            if (depth === 0) { cut = i; break; }
            depth -= 1;
        } else if (depth === 0) {
            if (ch === ';') { cut = i; break; }
            if (ch === ':') { cut = i; break; }
            if ((ch === '{' || ch === '}') && /^[\s)]/.test(before.slice(i + 1, i + 2))) { cut = i; break; }
        }
    }
    const beforeBranch = before.slice(cut + 1);

    return `${beforeBranch} ${afterBranch}`;
}

/**
 * Names appearing in a guard expression.
 *
 * `!activeStoryId` yields `activeStoryId`; `displayed.length === 0` yields
 * `displayed` and `length`. `length` and friends are stripped so a guard can
 * never satisfy the rule by accident.
 */
const NOISE = new Set([
    'length', 'size', 'keys', 'values', 'entries', 'map', 'filter', 'some',
    'every', 'find', 'count', 'isEmpty', 'Object', 'Array', 'undefined',
    'null', 'true', 'false', 'if', 'else', 'return',
]);

function guardIdentifiers(guard) {
    if (!guard) return [];
    return [...guard.matchAll(/[A-Za-z_$][A-Za-z0-9_$]*/g)]
        .map((m) => m[0])
        .filter((name) => !NOISE.has(name));
}

/**
 * Does this `<EmptyState>` render because a QUERY came back empty?
 *
 * True when a guard identifier is a query `data` alias, is derived from one
 * through a local `const`, or is a prop of a component whose other props carry
 * the same query result (the gallery grid's `displayedItems`).
 */
function emptinessDerivesFromQueryData(source, index, context) {
    const names = guardIdentifiers(guardBefore(source, index));
    if (names.length === 0) return false;
    return names.some((name) => isQueryDerived(name, context, 0));
}

const MAX_DERIVATION_HOPS = 3;

function isQueryDerived(name, context, depth) {
    if (depth > MAX_DERIVATION_HOPS) return false;
    if (context.aliases.has(name)) return true;
    // A prop of a component that also receives query results: the parent
    // decided, the child only got an array. Treated as query data because the
    // fix belongs in both — the parent must pass the error, the child must
    // render it.
    if (context.props.has(name)) return true;
    const init = context.bindings.get(name);
    if (!init) return false;
    return [...init.matchAll(/[A-Za-z_$][A-Za-z0-9_$]*/g)]
        .some((m) => isQueryDerived(m[0], context, depth + 1));
}

/** Every `<EmptyState` call site in a file, with whether its emptiness is query-derived. */
function emptyStateSites(source) {
    const context = {
        aliases: queryDataAliases(source),
        bindings: localBindings(source),
        props: componentProps(source),
    };
    return [...source.matchAll(/<EmptyState/g)].map((m) => ({
        index: m.index,
        guard: guardBefore(source, m.index),
        fromQuery: emptinessDerivesFromQueryData(source, m.index, context),
    }));
}

const sourceFiles = collectSourceFiles();

describe('the scan found something to scan', () => {
    it('walks all of src/, not just src/pages/', () => {
        // The 2026-10-04 rewrite exists because the old glob was pages-only and
        // the gallery's empty state lives in a component. If this file ever
        // matches pages again, that regression is back.
        const inPages = sourceFiles.filter((f) => f.startsWith(PAGES_DIR)).length;
        const outsidePages = sourceFiles.filter((f) => !f.startsWith(PAGES_DIR)).length;
        expect(inPages).toBeGreaterThan(15);
        expect(outsidePages).toBeGreaterThan(50);
    });

    it('finds EmptyState call sites in components, not only in pages', () => {
        const files = sourceFiles.filter((f) => readFileSync(f, 'utf8').includes('<EmptyState'));
        expect(files.length).toBeGreaterThan(8);
        const outsidePages = files.filter((f) => !f.startsWith(PAGES_DIR));
        expect(outsidePages.length).toBeGreaterThan(0);
    });
});

describe('a failed fetch is never rendered as an empty vault', () => {
    // The original, copy-based rule, kept. It is the cheap first line and it
    // still covers the seven pages that motivated this file.
    const offenders = [];
    for (const file of pages) {
        const source = readPage(file);
        const shipsEmptyState = EMPTY_STATE_COPY.some((copy) => source.includes(copy));
        if (!shipsEmptyState) continue;
        if (!handlesQueryError(source)) offenders.push(file);
    }

    it('every page with empty-state copy also has an error state', () => {
        expect(offenders).toEqual([]);
    });
});

describe('every query-derived empty state is error-gated', () => {
    const offenders = [];

    for (const file of sourceFiles) {
        const source = readFileSync(file, 'utf8');
        if (!source.includes('<EmptyState')) continue;
        if (handlesQueryError(source)) continue;

        const sites = emptyStateSites(source);
        const queryDerived = sites.filter((s) => s.fromQuery);
        if (queryDerived.length === 0) continue;

        offenders.push(`${relative(SRC_DIR, file)}:${sites.length} site(s), ${queryDerived.length} query-derived`);
    }

    it('has no offenders', () => {
        expect(offenders).toEqual([]);
    });

    it('exempts a StorySandbox-shaped empty state gated on local UI state', () => {
        // The false positive this rule is written to avoid. `activeStoryId` is
        // `useParams()` + local state, so a 503 cannot reach this empty state
        // and demanding an error branch there would be demanding dead code.
        const source = `
            import { useParams } from 'react-router-dom';
            import { useStory } from '../hooks/useStory';
            export default function StorySandbox() {
                const { storyId: urlStoryId } = useParams();
                const activeStoryId = urlStoryId || null;
                const { data: activeStory } = useStory(activeStoryId);
                return !activeStoryId ? <EmptyState title="No Story Selected" /> : <div />;
            }
        `;
        expect(emptyStateSites(source).every((s) => !s.fromQuery)).toBe(true);
    });

    it('catches a deliberately-introduced violation (the canary must be able to fail)', () => {
        // The exact shape of the reproduced gallery defect: an empty state
        // gated on an array that came from a query, with no `isError` in sight.
        // If this stops failing, the scan went blind again — which is precisely
        // how the live 503 got through five audits behind a green suite.
        const source = `
            export default function DashboardGalleryGrid({ displayedItems, isLoading }) {
                if (isLoading) return <Spinner />;
                if (displayedItems.length === 0) {
                    return <EmptyState type='gallery' onAction={onClearFilters} />;
                }
                return <Grid />;
            }
        `;
        const sites = emptyStateSites(source);
        expect(sites).toHaveLength(1);
        expect(sites[0].fromQuery).toBe(true);
        expect(handlesQueryError(source)).toBe(false);
        // i.e. the offender list above would name this file.
        expect(sites.filter((s) => s.fromQuery)).toHaveLength(1);
    });

    it('catches the same violation one hop through a derived local', () => {
        const source = `
            export default function MemoriesPanel() {
                const { data: memories = [], isLoading } = useCharacterMemories(id);
                const displayed = memories;
                return displayed.length === 0 ? <EmptyState type="collection" /> : <List />;
            }
        `;
        expect(emptyStateSites(source)[0].fromQuery).toBe(true);
    });
});

describe('QueryState', () => {
    const renderInRouter = (ui) => render(<MemoryRouter>{ui}</MemoryRouter>);

    it('names what failed and says it is not the same as having none', () => {
        renderInRouter(<QueryErrorState noun="characters" error={new Error('boom')} />);
        const alert = screen.getByRole('alert');
        expect(alert).toHaveTextContent(/could not load your characters/i);
        expect(alert).toHaveTextContent(/boom/);
        expect(alert).toHaveTextContent(/not the same as having none/i);
    });

    it('unwraps a FastAPI 422 detail, naming the field that was rejected', () => {
        const error = { response: { data: { detail: [{ loc: ['body', 'name'], msg: 'field required' }] } } };
        renderInRouter(<QueryErrorState noun="lorebooks" error={error} />);
        expect(screen.getByRole('alert')).toHaveTextContent('name: field required');
    });

    it('offers a retry that re-runs the query', () => {
        const onRetry = vi.fn();
        renderInRouter(<QueryErrorState noun="worlds" error={new Error('x')} onRetry={onRetry} />);
        screen.getByRole('button', { name: /try again/i }).click();
        expect(onRetry).toHaveBeenCalledTimes(1);
    });

    it('omits the retry button when there is nothing to retry with', () => {
        renderInRouter(<QueryErrorState noun="worlds" error={new Error('x')} />);
        expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
    });

    it('QueryGate renders the loading fallback, then the error, then children', () => {
        const { rerender } = renderInRouter(
            <QueryGate isLoading noun="chats" loadingFallback={<span>loading…</span>}>
                <span>list</span>
            </QueryGate>
        );
        expect(screen.getByText('loading…')).toBeTruthy();

        rerender(
            <MemoryRouter>
                <QueryGate isLoading={false} isError error={new Error('down')} onRetry={() => {}} noun="chats">
                    <span>list</span>
                </QueryGate>
            </MemoryRouter>
        );
        expect(screen.getByRole('alert')).toBeTruthy();
        expect(screen.queryByText('list')).toBeNull();
    });

    it('QueryGate never substitutes the children for a failure', () => {
        // The exact inversion this component exists to prevent: the list
        // rendering because the fetch did.
        renderInRouter(
            <QueryGate isLoading={false} isError error={new Error('down')} noun="chats">
                <span>No chats yet</span>
            </QueryGate>
        );
        expect(screen.queryByText('No chats yet')).toBeNull();
    });
});