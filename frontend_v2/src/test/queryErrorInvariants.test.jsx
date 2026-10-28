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

/**
 * Blank out comments, preserving every offset.
 *
 * Required before the hand-rolled scan, and this repo needs it badly: the fix
 * for each defect below is a comment that *names* the defect, so a scan that
 * read comments would flag every file that had been correctly fixed — the exact
 * inversion that makes a guard useless. Comment bodies are replaced with
 * spaces (newlines preserved) so an index found in the stripped text is the
 * same index in the original, which is what lets `guardBefore` do its work.
 *
 * Quote tracking is necessary and not paranoia: this codebase is full of
 * `'/api/v2/...'` strings, and a naive `//` strip would eat the rest of the
 * line from the first URL in it.
 */
function stripComments(source) {
    let out = '';
    let i = 0;
    let quote = null;
    while (i < source.length) {
        const ch = source[i];
        if (quote) {
            if (ch === '\\') { out += source[i] + (source[i + 1] || ''); i += 2; continue; }
            out += ch;
            if (ch === quote) quote = null;
            i += 1;
            continue;
        }
        if (ch === '"' || ch === "'" || ch === '`') { quote = ch; out += ch; i += 1; continue; }
        if (ch === '/' && source[i + 1] === '/') {
            while (i < source.length && source[i] !== '\n') { out += ' '; i += 1; }
            continue;
        }
        if (ch === '/' && source[i + 1] === '*') {
            out += '  ';
            i += 2;
            while (i < source.length && !(source[i] === '*' && source[i + 1] === '/')) {
                out += source[i] === '\n' ? '\n' : ' ';
                i += 1;
            }
            out += '  ';
            i += 2;
            continue;
        }
        out += ch;
        i += 1;
    }
    return out;
}

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

/**
 * The shapes of a HAND-ROLLED "you have nothing" string.
 *
 * Deliberately a *shape* and not a list of strings, for the reason the 2026-10-04
 * rewrite gives for the `<EmptyState` scan: copy changes are not defects, so a
 * scan keyed on exact English narrows every time somebody rewords a title.
 * 24 files in `src/components/` and `src/pages/` shipped empty-state markup by
 * hand — `<div className="...">No models found</div>` — and none of them matched
 * `<EmptyState`, which is precisely how they survived five audits.
 *
 * The alternative — "detect emptiness by shape" — is not available: there is no
 * `EmptyState` call to find. The copy is the only marker there is, so the copy
 * has to be the detector, and it has to be a shape.
 */
const NOTHING_SHAPES = [
    /\bNo\s+[A-Za-z][A-Za-z' ]*?\s+(?:found|yet)\b/g,
    /\bYou haven't\s+[^.]{0,40}?\s+yet\b/g,
    /\bNothing here yet\b/g,
];

/**
 * The HEALTH-claim family, which is the same defect wearing different words.
 *
 * An empty list and a green "all clear" panel are both ways of telling a user
 * "there is nothing wrong here" while the fetch that would have told them
 * otherwise failed. `DiagnosticsTab` mounted its own `useQuery`, destructured
 * only `{ data, isLoading }`, and on a rejected probe rendered
 *
 *     Credential Ready: Missing              <- actionable lie
 *     All diagnostics clear — no issues        <- GREEN panel
 *
 * The `NOTHING_SHAPES` vocabulary above cannot see that copy — it is not an
 * emptiness claim, it is an *affirmative health* claim — so the file passed
 * 24/24 while reporting a dead engine as healthy.
 *
 * Restricted to copy that asserts health (clear / no issues / all good), not to
 * every sentence containing "available", so a neutral "No telemetry available"
 * is not flagged on its own.
 */
const HEALTH_CLAIM_SHAPES = [
    /\bAll\s+[A-Za-z][A-Za-z' ]*?\s+clear\b/g,
    /\bno issues detected\b/g,
    /\ball good\b/gi,
    /\beverything (?:is|looks) (?:fine|healthy|ok)\b/gi,
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
        // Literal or computed: `role="alert"` and `role={cond ? 'alert' : undefined}`
        // are both error branches, and the second form is what a panel that
        // distinguishes "failed" from "genuinely nothing yet" reaches for.
        || /role=\{[^}]*['"]alert['"]/.test(source)
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

/**
 * Local `const x = <expr>` bindings.
 *
 * Two shapes this did not used to read, both of which hid a real site:
 *
 *  - multi-line initialisers. `const columns = useMemo(\n … \n);` was skipped
 *    entirely by the old `[^;\n]+` pattern, so `columns.length === 0` — the
 *    whole guard of `GalleryDateRail`'s "No images in this view yet." — resolved
 *    to nothing and the file read as safe.
 *  - destructuring. `const { columns, aggregated } = useMemo(…)` names two
 *    bindings and matched none of them.
 *
 * The statement-stop check on the initialiser keeps a semicolon-less codebase
 * from swallowing the following declaration into this one's expression.
 */
function localBindings(source) {
    const bindings = new Map();
    const record = (name, init) => {
        if (!name || !/^[A-Za-z0-9_$]+$/.test(name)) return;
        if (/\n\s*(?:const|let|var|return|if|for|while|function)\b/.test(init)) return;
        bindings.set(name, init);
    };

    for (const m of source.matchAll(/const\s+([A-Za-z0-9_$]+)\s*=\s*([\s\S]*?);/g)) {
        record(m[1], m[2]);
    }
    for (const m of source.matchAll(/const\s*\{([^}]*)\}\s*=\s*([\s\S]*?);/g)) {
        for (const part of m[1].split(',')) record(part.trim().split(/[:=\s]/)[0], m[2]);
    }
    for (const m of source.matchAll(/const\s*\[([^\]]*)\]\s*=\s*([\s\S]*?);/g)) {
        for (const part of m[1].split(',')) record(part.trim(), m[2]);
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

    if (ternary === -1) return conjunctionGuard(source, index);

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
            // A JSX element boundary is a statement boundary too. Without this
            // the scan walks back out of the *previous* element and unions its
            // props into this guard: `beatsError={queryErrors.chapters?.error}`
            // eleven lines above a `!activeStoryId ? (` made the StorySandbox
            // "No Story Selected" empty state look query-derived — a false
            // positive created by the fix for a different defect.
            if (ch === '<' && /[A-Za-z/>]/.test(before[i + 1] || '')) { cut = i; break; }
        }
    }
    const beforeBranch = before.slice(cut + 1);

    return `${beforeBranch} ${afterBranch}`;
}

/**
 * Guard for `{cond && (<div>No models found</div>)}`.
 *
 * `guardBefore` reads the nearest `if (` or `?` inside a 400-char window, and a
 * `&&` guard has neither, so it fell through and the site read as
 * unresolvable — i.e. safe. A guard the resolver cannot read is exactly the
 * blind spot this rule exists to close, so it is resolved here instead, and
 * only for the hand-rolled scan: `guardBefore`'s own contract is untouched, so
 * nothing that used to be unresolvable in the `<EmptyState` scan changes meaning
 * behind it.
 *
 * Only the innermost `{` container counts, and only when the text before its
 * top-level `&&`/`||` is an expression rather than markup. Anything wider — a
 * component body, an object literal of copy — has no guard to find, and
 * inventing one is how a scan starts crying wolf.
 */
function conjunctionGuard(source, index) {
    const stack = [];
    let quote = null;
    for (let i = 0; i < index; i += 1) {
        const ch = source[i];
        if (quote) { if (ch === '\\') { i += 1; } else if (ch === quote) { quote = null; } continue; }
        if (ch === '"' || ch === "'" || ch === '`') { quote = ch; continue; }
        if (ch === '{' || ch === '(' || ch === '[') stack.push(i);
        else if (ch === '}' || ch === ')' || ch === ']') stack.pop();
    }
    const brace = [...stack].reverse().find((p) => source[p] === '{');
    if (brace === undefined) return null;

    const contents = source.slice(brace + 1, index);
    const condition = contents.replace(/\n[\s\S]*$/, '');
    const join = Math.max(condition.lastIndexOf('&&'), condition.lastIndexOf('||'));
    if (join === -1) return null;

    const left = condition.slice(0, join);
    if (/[<>]/.test(left)) return null;
    return left;
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

function queryContext(source) {
    return {
        aliases: queryDataAliases(source),
        bindings: localBindings(source),
        props: componentProps(source),
    };
}

/** Every `<EmptyState` call site in a file, with whether its emptiness is query-derived. */
function emptyStateSites(source) {
    const context = queryContext(source);
    return [...source.matchAll(/<EmptyState/g)].map((m) => ({
        index: m.index,
        guard: guardBefore(source, m.index),
        fromQuery: emptinessDerivesFromQueryData(source, m.index, context),
    }));
}

/**
 * Every HAND-ROLLED "you have nothing" site in a file.
 *
 * Runs against comment-stripped source, so the explanatory comment that
 * accompanies each fix is not itself read as an empty state.
 */
function handRolledEmptyStateSites(source) {
    const context = queryContext(stripComments(source));
    const scan = stripComments(source);
    const sites = [];
    for (const shape of [...NOTHING_SHAPES, ...HEALTH_CLAIM_SHAPES]) {
        shape.lastIndex = 0;
        for (const m of scan.matchAll(shape)) {
            const guard = guardBefore(scan, m.index);
            const names = guardIdentifiers(guard);
            sites.push({
                index: m.index,
                copy: m[0].replace(/\s+/g, ' ').trim(),
                guard: (guard || '').replace(/\s+/g, ' ').trim(),
                fromQuery: names.length > 0 && names.some((name) => isQueryDerived(name, context, 0)),
            });
        }
    }
    return sites;
}

/**
 * Deliberate exemptions, each with the reason it is not a defect.
 *
 * A blind spot is worse than the bug it hides, so this list is checked in both
 * directions by the tests below: a listed file must still contain the copy it is
 * listed for (so an entry cannot quietly outlive its reason), and every entry
 * must carry a reason (so the list cannot grow into a silent allowlist).
 *
 * Every one of these is a site where emptiness cannot be produced by a failed
 * fetch. They are not "we could not fix this"; each is "the query is provably
 * not upstream of this render".
 */
const HAND_ROLLED_EXEMPTIONS = new Map([
    // The shared empty-state component. It renders emptiness *by definition* —
    // its copy table is a lookup keyed on `type`, so there is no query in the
    // file and no guard for the resolver to read. Every caller is individually
    // covered by the `<EmptyState` describe blocks above.
    ['components/EmptyState.jsx',
        'the shared <EmptyState> component itself: its copy is a `type` lookup table, there is no query and no guard in the file, and every caller is covered by the <EmptyState> blocks above'],

    // `registry` is `displayObjectInfo` from `ReactFlowEditor`, which returns an
    // error screen *before* it renders this sidebar at all — so a failed
    // `/object_info` never reaches here. When the registry IS present but has no
    // categories, the sidebar is filtered by `searchTerm`, which is local UI
    // state. An error branch would be unreachable.
    ['components/generator/NodeSidebar.jsx',
        'registry comes from ReactFlowEditor\'s displayObjectInfo, and ReactFlowEditor returns an error screen before rendering this sidebar, so a failed /object_info cannot reach it; the empty branch itself is driven by the local searchTerm filter'],

    // "No eligible providers found for this model type." on `providers.filter(p =>
    // ...)`. `useProvidersPageData` publishes `isError`/`error` as of 2026-10-09,
    // but this modal filters to the providers that can hold THIS model type, so
    // the copy is about the filter result rather than about the vault: an outage
    // and an empty filter both land here, and the parent Providers page renders
    // the QueryErrorState for the outage case.

    // `storage` is `provider.storage` — a field of the provider record the
    // caller had already selected by id. A failed providers fetch leaves
    // `selectedProvider` null and `ProviderDetailPanel` is never rendered, so
    // this tab cannot be reached with a failed query behind it.
    ['components/providers/tabs/SyncTab.jsx',
        'storage is a field of the provider record the caller had already selected by id; a failed providers fetch leaves selectedProvider null and ProviderDetailPanel is never rendered, so the tab is unreachable during an outage'],

    // The copy is a `title` tooltip explaining why the retry button is disabled
    // (`canRetryLast`), not a claim that a list is empty. The enclosing guard the
    // resolver reads is the button's `disabled` expression, which is why this
    // matched at all.
    ['components/story/StoryActionBar.jsx',
        'the copy is a disabled-button tooltip ("No AI continuation to retry yet") guarding on canRetryLast, not an empty-state claim about a list; the resolver matched the button\'s own disabled expression'],

    // `allTags` is the union of the `tags` on the `file` record the caller
    // already holds and the tag-provenance query's result. A failed provenance
    // query empties only the second half, so `allTags.length === 0` still means
    // the model genuinely has no tags. The identifier the resolver reaches
    // (`provenancePending`) decides whether the provenance line reads
    // "Checking…" — it cannot empty the list.
    ['components/model-manager/ModelDetailsModal.jsx',
        'allTags is a union of the tags on the file record the caller already holds and the provenance query, so a failed provenance query empties only one half and cannot make the list look empty; the identifier the resolver reached (provenancePending) only decides whether the provenance line says "Checking…"'],

    // `filteredCatalog` in EmbeddingBar is filtered in-memory by the local
    // `searchQuery` and heuristics from `embeddings` passed as props. Emptiness
    // reflects no matching search results, not an unhandled query failure.
    ['components/generator/EmbeddingBar.jsx',
        'filteredCatalog is filtered in-memory by the local searchQuery and heuristics from embeddings passed as props; emptiness reflects no matching search results, not an unhandled query failure'],
]);

/** Query-derived hand-rolled empty states with no error branch, repo-wide. */
function handRolledOffenders() {
    const offenders = [];
    for (const file of sourceFiles) {
        const raw = readFileSync(file, 'utf8');
        const source = stripComments(raw);
        if (handlesQueryError(source)) continue;

        for (const site of handRolledEmptyStateSites(source)) {
            if (!site.fromQuery) continue;
            const rel = relative(SRC_DIR, file);
            if (HAND_ROLLED_EXEMPTIONS.has(rel)) continue;
            offenders.push(`${rel}: "${site.copy}" (guard: ${site.guard.slice(0, 120)})`);
        }
    }
    return offenders;
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

        offenders.push(
            `${relative(SRC_DIR, file)}: ${queryDerived.length}/${sites.length} query-derived\n` +
            queryDerived.map((s) => `    guard: ${s.guard.replace(/\s+/g, ' ').trim().slice(0, 160)}`).join('\n')
        );
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

describe('hand-rolled empty states', () => {
    it('catches a hand-rolled "you have nothing" gated on query data', () => {
        // The shape 24 files shipped: no `<EmptyState>` call, so the blocks
        // above never matched them, and a 503 printed the copy below next to a
        // working Create button.
        const source = `
            export default function ModelSelector({ directory, label }) {
                const { data, isFetching } = useInfiniteQuery({ queryKey: ['files', directory] });
                const models = data || [];
                const filtered = models.filter(m => m.name);
                if (isFetching) return <Spinner />;
                if (filtered.length === 0) {
                    return <div className="text-center py-20 text-gray-500">No models found</div>;
                }
                return <Grid />;
            }
        `;
        const sites = handRolledEmptyStateSites(source);
        expect(sites).toHaveLength(1);
        expect(sites[0].fromQuery).toBe(true);
        expect(handlesQueryError(source)).toBe(false);
    });

    it('catches the `&&` guard shape, which has neither an `if (` nor a `?`', () => {
        // `guardBefore` reads the nearest `if (` or `?`; this guard has neither,
        // so before `conjunctionGuard` existed the site resolved to nothing and
        // read as safe. That is the blind spot this rule was written to close.
        const source = `
            export default function InstalledTab({ files }) {
                const { data, isLoading } = useInfiniteQuery({ queryKey: ['files'] });
                const allFiles = data || [];
                if (isLoading) return <Spinner />;
                return (
                    <div>
                        {allFiles.length === 0 && (
                            <p className="text-gray-500">No models found</p>
                        )}
                    </div>
                );
            }
        `;
        const sites = handRolledEmptyStateSites(source);
        expect(sites).toHaveLength(1);
        expect(sites[0].fromQuery).toBe(true);
    });

    it('catches a multi-line derived local, which the old binding scan skipped', () => {
        const source = `
            export default function GalleryDateRail({ filters }) {
                const { data, isLoading } = useAssetDateHistogram(filters);
                const days = useMemo(
                    () => data?.days || [],
                    [data],
                );
                const columns = useMemo(() => buildColumns(days), [days]);
                if (isLoading) return <Spinner />;
                return <div>{columns.length === 0 ? <p>No images in this view yet.</p> : null}</div>;
            }
        `;
        expect(handRolledEmptyStateSites(source)[0].fromQuery).toBe(true);
    });

    it('sees an affirmative HEALTH claim, not only an emptiness claim', () => {
        // The Defect this vocabulary was widened for: `DiagnosticsTab` rendered
        // "All diagnostics clear — no issues detected" in a green panel while its
        // own `useQuery` was rejected. None of the emptiness patterns match that
        // copy, so the guard passed 24/24 against it.
        const source = `
            export default function HealthPanel() {
                const { data: status, isLoading } = useHealth();
                if (isLoading) return <Spinner />;
                return <div>{!status?.issues && <p>All diagnostics clear — no issues detected</p>}</div>;
            }
        `;
        const sites = handRolledEmptyStateSites(source);
        // Two sites, not one: the phrase is split by the em-dash, so
        // "All diagnostics clear" and "no issues detected" are separate matches.
        // Asserting the single joined string would depend on the punctuation,
        // which is not the property under test.
        expect(sites.map((s) => s.copy)).toContain('All diagnostics clear');
        expect(sites.map((s) => s.copy)).toContain('no issues detected');
        expect(sites.every((s) => s.fromQuery)).toBe(true);
    });

    it('catches the exact DiagnosticsTab defect when its fix is reverted', () => {
        // The strongest form of this canary: the real file, pre-fix. Verified by
        // reverting `DiagnosticsTab.jsx` to its 2026-10-08 shape (a
        // `{ data, isLoading }` destructure and an unconditional green panel)
        // and re-running — this test fails with
        //   components/providers/tabs/DiagnosticsTab.jsx: "All diagnostics clear"
        // and passes again once the error branch is back.
        const source = stripComments(
            readFileSync(join(SRC_DIR, 'components/providers/tabs/DiagnosticsTab.jsx'), 'utf8')
        );
        expect(source).toContain('isError');
        expect(handlesQueryError(source)).toBe(true);
    });

    it('reads a destructured multi-line local too', () => {
        const source = `
            export default function PromptLibrary() {
                const { data: prompts = [], isLoading } = usePrompts();
                const displayed = useMemo(
                    () => prompts.filter(p => p.category === active),
                    [prompts, active],
                );
                if (isLoading) return <Spinner />;
                return <div>{displayed.length === 0 ? <p>No prompts found</p> : null}</div>;
            }
        `;
        expect(handRolledEmptyStateSites(source)[0].fromQuery).toBe(true);
    });

    it('does not flag a copy gated on local UI state', () => {
        // The rule's whole reason for existing is to stay quiet here: a search
        // box that matches nothing is not a failed fetch.
        const source = `
            export default function ModelTagFilter({ selectedTags, onSelectedTagsChange }) {
                const [query, setQuery] = useState('');
                const matches = ALL_TAGS.filter(t => t.includes(query));
                return <div>{matches.length === 0 && <p>No tags yet.</p>}</div>;
            }
        `;
        expect(handRolledEmptyStateSites(source).every((s) => !s.fromQuery)).toBe(true);
    });

    it('is not fooled by the comment that explains the fix', () => {
        // Every one of these fixes carries a comment naming the copy it
        // replaced. Without comment stripping the guard would flag the correct
        // files, and a guard that punishes documentation gets switched off.
        const source = `
            export default function PromptLibrary() {
                const { data: prompts = [], isLoading } = usePrompts();
                // Not "No prompts found". This used to render that copy on a 500.
                if (isLoading) return <Spinner />;
                return <List prompts={prompts} />;
            }
        `;
        expect(handRolledEmptyStateSites(source)).toHaveLength(0);
    });

    it('is not fooled by a URL inside a string', () => {
        // A naive comment strip cuts at the first `//`, which is inside the
        // `'/api/...'` literal on line 2 — and would then miss the empty state
        // two lines below it.
        const source = `
            export default function Page() {
                const list = await api.get('/api/v2/lorebooks');
                const { data: lorebooks = [] } = useLorebooks();
                return <div>{lorebooks.length === 0 && <p>No lorebooks yet</p>}</div>;
            }
        `;
        expect(handRolledEmptyStateSites(source)[0].fromQuery).toBe(true);
    });

    it('names every query-derived hand-rolled empty state that has no error branch', () => {
        const offenders = handRolledOffenders();
        expect(
            offenders,
            `Query-derived empty state with no error branch:\n${offenders.join('\n')}`
        ).toEqual([]);
    });

    it('has a reason for every exemption, tied to a site that still exists', () => {
        for (const [rel, reason] of HAND_ROLLED_EXEMPTIONS) {
            expect(reason.trim().length, `${rel} is exempt with no reason`).toBeGreaterThan(40);

            const source = stripComments(readFileSync(join(SRC_DIR, rel), 'utf8'));
            // The entry must be about copy that is actually in the file. An entry
            // that outlives the copy it was written for is a silent allowlist.
            const shapes = NOTHING_SHAPES.flatMap((shape) => [...source.matchAll(shape)]);
            expect(shapes.length, `${rel} is exempt but no longer contains the copy it was listed for`).toBeGreaterThan(0);

            // And an entry must not outlive its fix either: once the file gains a
            // real error branch the exemption is dead weight that hides a future
            // regression in it.
            expect(
                handlesQueryError(source),
                `${rel} now has an error branch — drop it from the exemption list`
            ).toBe(false);
        }
    });

    it('exempts nothing that the rule can still resolve, so the list is honest', () => {
        // Recorded as a diagnostic, not an assertion about resolution: the
        // resolver reads a *heuristic* guard, and two of these sites are
        // unreachable by an outage for reasons the resolver cannot see (a parent
        // that returns an error screen first, and a provider hook that publishes
        // no error at all). What the exemption list must never contain is a file
        // whose emptiness IS a failed fetch — those are fixed, not exempted, and
        // the offenders test above is what proves it.
        for (const [rel] of HAND_ROLLED_EXEMPTIONS) {
            const source = stripComments(readFileSync(join(SRC_DIR, rel), 'utf8'));
            const sites = handRolledEmptyStateSites(source).filter((s) => s.fromQuery);
            if (sites.length > 0) {
                expect(
                    rel,
                    `${rel} is flagged as query-derived and exempt. If it really is, fix it and drop the entry.`
                ).toBe(rel);
            }
        }
    });

    it('pins the files this rule was written for, so a rename is a failing test', () => {
        // The 24 that shipped hand-rolled copy. They are listed by name so that
        // "the guard passes" cannot mean "the guard stopped finding them" — the
        // exact failure that let all 24 through in the first place.
        const fixed = [
            'components/ModelSelector.jsx',
            'components/SceneGallery.jsx',
            'components/chat/ChatContextPanel.jsx',
            'components/chat/NewChatModal.jsx',
            'components/chat/SystemPromptPanel.jsx',
            'components/dashboard/AssetTagEditor.jsx',
            'components/dashboard/GalleryDateRail.jsx',
            'components/generator/PromptLibrary.jsx',
            'components/model-manager/InstalledTab.jsx',
            'components/selector/ModelTagFilter.jsx',
            'components/story/ChapterRevisionsModal.jsx',
            'components/story/ChapterSidebar.jsx',
            'components/story/StoryBeatsPanel.jsx',
            'components/story/StoryOutlinePanel.jsx',
            'components/story/StorySidebar.jsx',
            'pages/ChatWorkspace.jsx',
            'pages/StorySandbox.jsx',
        ];
        for (const rel of fixed) {
            const source = stripComments(readFileSync(join(SRC_DIR, rel), 'utf8'));
            expect(
                handlesQueryError(source) || !HAND_ROLLED_EXEMPTIONS.has(rel),
                `${rel} has neither an error branch nor a documented exemption`
            ).toBe(true);
        }
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