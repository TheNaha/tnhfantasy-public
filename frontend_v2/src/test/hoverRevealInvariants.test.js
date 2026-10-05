/**
 * A hover-reveal control that is `opacity-0` until hover is the right pattern on
 * a desktop and the wrong one on a touch device: there is no hover, so the
 * control is laid out, hit-testable, and invisible. Tapping it delivers the
 * event to a control nobody can see.
 *
 * `src/index.css` rescues this under `@media (hover: none)` by forcing
 * `opacity: 1`. That rescue is a hand-maintained list of class names, and a
 * named group (`group-hover/card`) was missing from it while two names no source
 * file has ever used (`chat-row`, `menu-item`) sat in the list looking
 * load-bearing. The measured consequence: the ControlNet delete button computed
 * to `opacity: 0; pointer-events: auto; visibility: visible` on any touch
 * device — invisible, and it deletes a ControlNet on tap.
 *
 * These tests assert the RULE — every named hover-reveal group in the tree must
 * appear in the rescue block, and the block must not carry names nothing uses —
 * so the list cannot silently fall behind the source again.
 *
 * Two of those rules were not running. The staleness regex asked for a bare `:`
 * where Tailwind's generated CSS has `\:`, so it matched nothing and
 * `chat-row`/`menu-item` survived in the block long after the last file stopped
 * using them; and the vocabulary was `group-hover/` only, so
 * `group-focus-within/menu` was invisible to the scan. Both are covered here,
 * and `chat-row`/`menu-item` have been removed from the block.
 */
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..');
const CSS_PATH = join(SRC, 'index.css');

const WALK_SKIP = new Set(['node_modules', 'dist', 'test', '__tests__', 'e2e']);

/** Every source file under src/, excluding tests and build output. */
function sourceFiles(dir = SRC, acc = []) {
    for (const entry of readdirSync(dir)) {
        if (WALK_SKIP.has(entry)) continue;
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) sourceFiles(full, acc);
        else if (/\.jsx?$/.test(entry)) acc.push(full);
    }
    return acc;
}

/**
 * Named reveal groups actually used by component source, keyed by variant.
 *
 * `group-hover/<name>` is a hover-reveal: on a touch device nothing fires it,
 * so it needs the `@media (hover: none)` rescue. `group-focus-within/<name>` is
 * a disclosure: focus is what opens it, and a tap on a trigger focuses it, so
 * it needs no rescue — and must NOT get one, because a rule that forced these
 * visible under `(hover: none)` would pin every menu open on a phone. It has its
 * own requirements instead, below.
 */
function namedRevealGroups() {
    const found = new Map();
    for (const file of sourceFiles()) {
        const text = readFileSync(file, 'utf8');
        for (const m of text.matchAll(/\b(group-(?:hover|focus-within))\/([a-z][a-z0-9-]*)/g)) {
            found.set(`${m[1]}/${m[2]}`, file);
        }
    }
    return found;
}

/** Just the `group-hover/` names, which are the ones the CSS block rescues. */
function namedHoverGroups() {
    return new Set([...namedRevealGroups().keys()].filter((k) => k.startsWith('group-hover/')).map((k) => k.slice('group-hover/'.length)));
}

/** The `@media (hover: none)` block's escaped selectors. */
function rescueSelectors() {
    const css = readFileSync(CSS_PATH, 'utf8');
    const start = css.indexOf('@media (hover: none)');
    expect(start, 'index.css has no `@media (hover: none)` block').toBeGreaterThan(-1);
    const open = css.indexOf('{', start);
    let depth = 0;
    let end = open;
    for (let i = open; i < css.length; i += 1) {
        if (css[i] === '{') depth += 1;
        else if (css[i] === '}') {
            depth -= 1;
            if (depth === 0) { end = i; break; }
        }
    }
    return css.slice(open, end);
}

describe('hover-reveal rescue block', () => {
    const used = namedHoverGroups();
    const block = rescueSelectors();

    it('found the named groups it is meant to cover', () => {
        // A silently-empty scan would make every other test in this file pass.
        expect(used.size).toBeGreaterThan(0);
        expect([...used]).toContain('card');
    });

    it('covers every named hover-reveal group used in the tree', () => {
        const missing = [...used].filter(
            (name) => !block.includes(`group-hover\\/${name}\\:opacity-100`)
        );
        expect(
            missing,
            `these named hover-reveal groups are used in src/ but absent from the ` +
            `@media (hover: none) rescue block, so on a touch device they are ` +
            `invisible AND still hit-testable: ${missing.join(', ')}`
        ).toEqual([]);
    });

    it('carries no group name that nothing uses', () => {
        // Tailwind escapes the `/` and the `:` inside a generated class name, so
        // the shipped selector is `.group-hover\/card\:opacity-100`. The old
        // regex asked for a bare `:` where the CSS has `\:`, so it matched
        // nothing at all: `declared` was always `[]`, `stale` was always `[]`,
        // and this case was green by construction. Test 2 above already wrote
        // the escape correctly, which is why only half the guard was blind —
        // `chat-row` and `menu-item` sat in the block for months.
        const declared = [...block.matchAll(/group-hover\\\/([a-z][a-z0-9-]*)\\:opacity-100/g)]
            .map((m) => m[1]);
        expect(declared.length).toBeGreaterThan(0);
        const stale = [...new Set(declared)].filter((name) => !used.has(name));
        expect(
            stale,
            `the rescue block rescues group names no source file uses, so it ` +
            `reads as covering more than it does: ${stale.join(', ')}`
        ).toEqual([]);
    });

    it('names the two groups the stale-selector case used to miss', () => {
        // Pinned so the regression is legible: these are the two names that were
        // in the block while nothing used them, and the two that are genuinely
        // in use. If a group is renamed the list follows the source, and this
        // case fails until the CSS block is updated with it.
        const declared = [...block.matchAll(/group-hover\\\/([a-z][a-z0-9-]*)\\:opacity-100/g)]
            .map((m) => m[1]);
        expect(new Set(declared)).toEqual(used);
        expect([...used].sort()).toEqual(['card', 'message']);
    });

    it('a group-focus-within disclosure pairs opacity with visibility', () => {
        // The vocabulary now includes `group-focus-within/<name>`, which the old
        // `group-hover/`-only scan could not see at all. It cannot be rescued by
        // the CSS block — a rule forcing these visible under `(hover: none)`
        // would pin every menu open on a touch device — so the property it does
        // have to satisfy is that it is a disclosure rather than a permanent
        // hide: `invisible` and `:visible` travel together, which is what stops
        // a half-revealed menu from being laid out and hit-testable while
        // invisible on every platform.
        const focusNames = [...namedRevealGroups().keys()]
            .filter((k) => k.startsWith('group-focus-within/'));
        expect(focusNames.length).toBeGreaterThan(0);

        const offenders = [];
        for (const file of sourceFiles()) {
            const text = readFileSync(file, 'utf8');
            for (const attr of text.matchAll(/className\s*=\s*(?:"([^"]*)"|\{`([^`]*)`\}|\{'([^']*)'\})/g)) {
                const tokens = (attr[1] || attr[2] || attr[3] || '').split(/\s+/).filter(Boolean);
                const reveals = tokens
                    .map((t) => /^group-focus-within\/([a-z][a-z0-9-]*):(.+)$/.exec(t))
                    .filter(Boolean);
                if (reveals.length === 0) continue;
                for (const [, name, utility] of reveals) {
                    if (utility === 'opacity-100' && !tokens.includes(`group-focus-within/${name}:visible`)) {
                        offenders.push(`${file}: group-focus-within/${name} reveals opacity with no matching :visible`);
                    }
                    if (utility === 'visible' && !tokens.includes(`group-focus-within/${name}:opacity-100`)) {
                        offenders.push(`${file}: group-focus-within/${name} reveals visibility with no matching :opacity-100`);
                    }
                }
                if (!tokens.includes('invisible')) {
                    offenders.push(`${file}: a focus-within reveal with no 'invisible' to hide`);
                }
            }
        }
        expect(offenders, offenders.join('\n')).toEqual([]);
    });

    it('covers the bare (unnamed-group) form at every breakpoint used in the tree', () => {
        // Tailwind splits a className across whitespace, so `opacity-0` and
        // `group-hover:…` are separate tokens in the same attribute value. Read
        // each attribute value as a token list and pair them up.
        const prefixes = new Set();
        for (const file of sourceFiles()) {
            const text = readFileSync(file, 'utf8');
            for (const attr of text.matchAll(/className\s*=\s*(?:"([^"]*)"|\{`([^`]*)`\}|\{'([^']*)'\})/g)) {
                const tokens = (attr[1] || attr[2] || attr[3] || '').split(/\s+/).filter(Boolean);
                tokens.forEach((tok, i) => {
                    const m = /^(?:(sm|md|lg|xl):)?opacity-0$/.exec(tok);
                    if (!m) return;
                    if (!tokens.slice(i + 1).some((t) => /^(?:(?:sm|md|lg|xl):)?group-hover[:/]/.test(t))) return;
                    prefixes.add(m[1] || '(none)');
                });
            }
        }
        expect(prefixes.size).toBeGreaterThan(0);
        // Tailwind escapes the `:` inside a generated class name, so the CSS
        // selector for `sm:opacity-0 sm:group-hover:opacity-100` is written
        // `.sm\:opacity-0.sm\:group-hover\:opacity-100` — the variant prefix's
        // own colon is escaped too.
        const missing = [...prefixes].filter((p) => {
            if (p === '(none)') return !block.includes('.opacity-0.group-hover\\:opacity-100');
            const esc = `${p}\\:`;
            return !block.includes(`.${esc}opacity-0.${esc}group-hover\\:opacity-100`);
        });
        expect(
            missing,
            `these breakpoints hide a hover-reveal with no touch-device rescue: ${missing.join(', ')}`
        ).toEqual([]);
    });

    it('pins the ControlNet delete button as the regression this block exists for', () => {
        // Named explicitly so that deleting or renaming the group fails here
        // rather than silently re-hiding a destructive control on touch.
        const section = readFileSync(
            join(SRC, 'components/generator/ControlNetSection.jsx'),
            'utf8'
        );
        expect(section).toContain('group-hover/card:opacity-100');
        expect(section).toMatch(/removeControlNet/);
    });
});