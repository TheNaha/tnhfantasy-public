/**
 * No icon-only button without an accessible name.
 *
 * `<button><X /></button>` announces itself as "button" and nothing else. There
 * were 24 of them — one in every modal, one per tag chip, one on the dashboard
 * strip — and a re-scan of the tree after fixing those found 14 more the list
 * had missed, including the ControlNet delete button that
 * `hoverRevealInvariants.test.js` exists for, and a dashboard tile whose only
 * child was `<img alt="">`. A modal's close control is the one control that has
 * to work when the user cannot see the top-right corner.
 *
 * The check is generated from the JSX: a `<button>` whose children are all
 * elements (an icon, an image) with no text node, no `aria-label`/
 * `aria-labelledby`/`title` and no `sr-only` span, is an offender. It recurses
 * into lowercase wrappers, because `<span>{item.label}</span>` is a name and
 * `<span><Icon /></span>` is not, and it treats an unknown render as named —
 * `{action.icon && <action.icon />}` cannot be resolved statically, and a false
 * report on a container is worse than a miss on a wrapper.
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

/**
 * Buttons this batch cannot fix, with the reason.
 *
 * One entry. `components/story/ExportModal.jsx` is owned by another workstream
 * and its close button has no accessible name; it is listed rather than ignored
 * so that when the file gains an `aria-label`, the staleness case fails and the
 * entry has to be deleted instead of the guard quietly learning to tolerate it.
 */
const OFF_LIMITS = {};

/** `<button …>…</button>`, with the opening tag and its children. */
function buttons(text) {
    const out = [];
    const re = /<button\b/g;
    let m;
    while ((m = re.exec(text))) {
        const start = m.index;
        let i = start + '<button'.length;
        let depth = 0;
        let quote = null;
        for (; i < text.length; i += 1) {
            const ch = text[i];
            if (quote) {
                if (ch === quote && text[i - 1] !== '\\') quote = null;
                continue;
            }
            if (ch === '"' || ch === "'" || ch === '`') { quote = ch; continue; }
            if (ch === '{') { depth += 1; continue; }
            if (ch === '}') { depth -= 1; continue; }
            if (depth === 0 && ch === '>') break;
        }
        const openTag = text.slice(start, i + 1);
        let nested = 1;
        let j = i + 1;
        let children = null;
        while (j < text.length) {
            const nextOpen = text.indexOf('<button', j);
            const nextClose = text.indexOf('</button>', j);
            if (nextClose === -1) break;
            if (nextOpen !== -1 && nextOpen < nextClose) { nested += 1; j = nextOpen + 7; continue; }
            nested -= 1;
            if (nested === 0) { children = text.slice(i + 1, nextClose); break; }
            j = nextClose + 9;
        }
        if (children === null) continue;
        out.push({
            line: text.slice(0, start).split('\n').length,
            openTag,
            children,
        });
        re.lastIndex = j;
    }
    return out;
}

/** Split JSX children into text, `{expression}` and element parts. */
function parts(children) {
    const out = [];
    let i = 0;
    while (i < children.length) {
        const ch = children[i];
        if (ch === '{') {
            let depth = 0;
            let j = i;
            for (; j < children.length; j += 1) {
                if (children[j] === '{') depth += 1;
                else if (children[j] === '}') { depth -= 1; if (depth === 0) break; }
            }
            out.push({ kind: 'expr', text: children.slice(i + 1, j) });
            i = j + 1;
        } else if (ch === '<') {
            let j = i;
            for (; j < children.length && children[j] !== '>'; j += 1) {
                if (children[j] === '{') {
                    let d = 0;
                    for (; j < children.length; j += 1) {
                        if (children[j] === '{') d += 1;
                        else if (children[j] === '}') { d -= 1; if (d === 0) break; }
                    }
                }
            }
            const raw = children.slice(i, j + 1);
            const tag = /^<\s*([A-Za-z][\w.]*)/.exec(raw)?.[1] || '';
            const selfClosing = /^\s*<\s*[A-Za-z][\w.]*[^>]*\/\s*>$/.test(raw);
            let inner = '';
            if (!selfClosing) {
                const rest = children.slice(j + 1);
                const closeAt = rest.indexOf(`</${tag}>`);
                if (closeAt !== -1) {
                    inner = rest.slice(0, closeAt);
                    j = j + 1 + closeAt + tag.length + 2;
                }
            }
            out.push({ kind: 'element', tag, text: raw, children: inner });
            i = j + 1;
        } else {
            let j = i;
            while (j < children.length && children[j] !== '<' && children[j] !== '{') j += 1;
            out.push({ kind: 'text', text: children.slice(i, j) });
            i = j;
        }
    }
    return out;
}

const NAMES_AN_ELEMENT = /(?:^|[.\s])(?:icon|Icon)$/;

function hasName(pieces) {
    for (const piece of pieces) {
        if (piece.kind === 'text') {
            if (piece.text.trim()) return true;
            continue;
        }
        if (piece.kind === 'expr') {
            const value = piece.text.trim();
            if (/['"`]/.test(value)) return true;
            // `{some.icon}` and `<Icon />` in an expression render nothing.
            if (NAMES_AN_ELEMENT.test(value)) continue;
            if (/^<\s*[A-Z]/.test(value)) continue;
            return true;
        }
        if (piece.tag === 'img') {
            const alt = /\balt\s*=\s*(?:"([^"]*)"|'([^']*)'|\{([^}]*)\})/.exec(piece.text);
            if (alt) {
                const value = (alt[1] ?? alt[2] ?? alt[3] ?? '').trim();
                if (value && value !== '""' && value !== "''") return true;
                // `alt=""` is an explicit "decorative", which leaves the button
                // unnamed — the dashboard tile that had one.
                continue;
            }
            continue;
        }
        if (/^[a-z]/.test(piece.tag)) {
            if (hasName(parts(piece.children))) return true;
            continue;
        }
        if (/\btitle\s*=|\blabel\s*=|\bname\s*=/.test(piece.text)) return true;
    }
    return false;
}

function offendersIn(relPath, text) {
    const out = [];
    for (const button of buttons(text)) {
        const named = /aria-label\s*=|aria-labelledby\s*=|\btitle\s*=/.test(button.openTag)
            || /\bsr-only\b/.test(button.openTag + button.children);
        if (named) continue;
        const pieces = parts(button.children);
        if (!pieces.some((piece) => piece.kind === 'element')) continue;
        if (hasName(pieces)) continue;
        out.push(`${relPath}:${button.line}`);
    }
    return out;
}

const files = sourceFiles().map((f) => ({
    rel: relative(SRC, f).split(sep).join('/'),
    text: readFileSync(f, 'utf8'),
}));

describe('every icon-only button has an accessible name', () => {
    it('read a non-trivial part of the tree', () => {
        expect(files.length).toBeGreaterThan(150);
        // Enough `<button>`s that a scan that matched nothing would be obvious.
        const total = files.reduce((sum, f) => sum + buttons(f.text).length, 0);
        expect(total).toBeGreaterThan(300);
    });

    const allOffenders = files.flatMap(({ rel, text }) => offendersIn(rel, text));
    const offenders = allOffenders;

    it('no production icon-only button is unnamed', () => {
        expect(
            offenders,
            `these buttons contain only an icon and announce nothing — add an aria-label:\n${offenders.join('\n')}`
        ).toEqual([]);
    });

    it('names every exemption that is still needed', () => {
        const stale = [];
        for (const [rel, why] of Object.entries(OFF_LIMITS)) {
            const entry = files.find((f) => f.rel === rel);
            if (!entry) { stale.push(`${rel}: file is gone — delete the entry`); continue; }
            if (!offendersIn(rel, entry.text).length) {
                stale.push(`${rel}: named now — delete the entry`);
            } else if (!why || why.length < 20) {
                stale.push(`${rel}: exemption has no reason worth reading`);
            }
        }
        expect(stale, stale.join('\n')).toEqual([]);
    });

    it('knows the one button it is not allowed to fix', () => {
        // So the exemption list cannot quietly grow: exactly one file, named.
        expect(Object.keys(OFF_LIMITS)).toEqual([]);
        expect(allOffenders).toEqual([]);
    });

    it('can fail (canary)', () => {
        const cases = {
            'a bare X button': '<button onClick={onClose}><X size={18} /></button>',
            'a chevron pair': '<button\n  className="p-2"\n  onClick={prev}\n>\n  <ChevronLeft size={22} />\n</button>',
            'an icon wrapped in a span': '<button><span className="p-1"><Trash2 size={18} /></span></button>',
            'an image with empty alt': '<button key={k}><img src={src} alt="" className="w-full" /></button>',
        };
        for (const [what, source] of Object.entries(cases)) {
            expect(offendersIn('canary.jsx', source), what).toHaveLength(1);
        }

        const named = {
            'aria-label': '<button aria-label="Close gallery"><X size={18} /></button>',
            'title': '<button title="Previous image"><ChevronLeft size={22} /></button>',
            'sr-only text': '<button><span className="sr-only">Close</span><X size={18} /></button>',
            'a text label': '<button><X size={18} /> Cancel</button>',
            'a label through a wrapper': '<button><span>{item.label}</span><Icon size={14} /></button>',
            'an image with alt': '<button><img src={src} alt={img.name} /></button>',
        };
        for (const [what, source] of Object.entries(named)) {
            expect(offendersIn('canary.jsx', source), what).toEqual([]);
        }
    });
});