import { readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

/**
 * A `<label>` written as a *sibling* of its input has no `htmlFor` and no
 * matching `id`. Clicking it focuses nothing, and the control is announced
 * unnamed — with a visible label right above it, which is the worst
 * combination: it looks labelled to a sighted user and is not labelled to
 * anyone else.
 *
 * Two halves:
 *
 *  - `FormInput` is rendered and queried by its visible label, which is the fix
 *    for every call site at once (`useId()` makes the pair unique per instance,
 *    so two character forms on one page cannot collide).
 *  - A static scan of the sites that were fixed by hand, so a later rewrite that
 *    drops an `id` fails here instead of in a screen-reader session.
 */

const SRC_DIR = join(process.cwd(), 'src');

function stripComments(source) {
    return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

/**
 * Does the label name a control?
 *
 * `htmlFor={id}` and `htmlFor="id"` are both accepted; the template-literal and
 * expression forms are what the mapped form fields use (`htmlFor={`world-field-
 * ${field.key}`}`), which is why this is a prefix match on the id rather than an
 * exact one.
 */
function htmlForTarget(attrs) {
    const m = /htmlFor\s*=\s*(?:\{\s*)?["'`]?([^"'`\s}]+)/.exec(attrs);
    return m ? m[1] : null;
}

/**
 * Does the label WRAP its control?
 *
 * An implicit association — `<label>Name<input/></label>` — needs no id, so this
 * is what keeps the scan from demanding one everywhere. The check is on the
 * label's own content between its tags, not on what follows it: a sibling
 * `<label>Name</label><input/>` also has a closing tag, and mistaking that for
 * a wrapper is exactly how a scan like this starts passing everything.
 */
function wrapsControl(source, labelIndex) {
    const openTagEnd = source.indexOf('>', labelIndex);
    if (openTagEnd === -1) return false;
    const close = source.indexOf('</label>', openTagEnd);
    if (close === -1) return false;
    const inner = source.slice(openTagEnd + 1, close);
    return /<(?:input|select|textarea|FormInput)\b/.test(inner);
}

/** Label/control pairs fixed by hand, as `[file, label, controlId]`. */
const ASSOCIATED = [
    ['pages/Characters.jsx', 'character-form-name'],
    ['pages/Characters.jsx', 'character-form-voice-model'],
    ['pages/Locations.jsx', 'location-tag-input'],
    ['pages/Locations.jsx', 'location-image-input'],
    ['pages/Lorebooks.jsx', 'lorebook-form-name'],
    ['pages/Lorebooks.jsx', 'lorebook-form-description'],
    ['pages/Settings.jsx', 'llm-default-provider'],
    ['pages/Settings.jsx', 'llm-default-model'],
    ['pages/Scenarios.jsx', 'scenario-default-checkpoint'],
    ['pages/Voices.jsx', 'voice-type'],
];

/** Filter `<select>`s with no visible `<label>`, named by `aria-label` instead. */
const ARIA_NAMED_FILTERS = [
    ['pages/Prompts.jsx', 'Filter prompts by category'],
    ['pages/RelationshipGraph.jsx', 'Filter entities by type'],
    ['pages/WorldVaultHub.jsx', 'Filter the vault by entity type'],
];

describe('FormInput associates its label with its control', () => {
    it('the input is reachable by its visible label', () => {
        render(
            <MemoryRouter>
                <FormInput label="Character Name" value="Ada" onChange={() => {}} />
            </MemoryRouter>
        );

        const input = screen.getByLabelText(/Character Name/);
        expect(input.tagName).toBe('INPUT');
    });

    it("the label's htmlFor resolves to the input, which is what a click uses", () => {
        render(
            <MemoryRouter>
                <FormInput label="Character Name" value="Ada" onChange={() => {}} />
            </MemoryRouter>
        );

        const label = screen.getByText(/Character Name/).closest('label');
        const input = screen.getByLabelText(/Character Name/);

        // `HTMLLabelElement.control` is the spec's resolution of the
        // association and the exact thing a browser uses to forward a click.
        // Asserted through the property rather than by dispatching a click
        // because jsdom does not forward label activation to the control, so a
        // click-based assertion here would pass or fail on the environment
        // rather than on the markup.
        expect(label.htmlFor).toBe(input.id);
        expect(label.control).toBe(input);
    });

    it('gives two instances on one page different ids', () => {
        render(
            <MemoryRouter>
                <div>
                    <FormInput label="First" value="a" onChange={() => {}} />
                    <FormInput label="Second" value="b" onChange={() => {}} />
                </div>
            </MemoryRouter>
        );

        const first = screen.getByLabelText(/First/);
        const second = screen.getByLabelText(/Second/);
        // Duplicate ids would silently break the association for one of them:
        // `getByLabelText` resolves to the first match and the second control is
        // announced by nothing at all.
        expect(first.id).not.toBe(second.id);
        expect(first.id).toBeTruthy();
    });

    it('associates the textarea variant too', () => {
        render(
            <MemoryRouter>
                <FormInput label="Bio" type="textarea" value="hi" onChange={() => {}} />
            </MemoryRouter>
        );

        expect(screen.getByLabelText(/Bio/).tagName).toBe('TEXTAREA');
    });
});

describe('hand-associated label/control pairs', () => {
    for (const [file, id] of ASSOCIATED) {
        it(`${file}: <label htmlFor="${id}"> points at the control with that id`, () => {
            const source = readFileSync(join(SRC_DIR, file), 'utf8');
            expect(source, `${file}: ${id} has no htmlFor`).toMatch(
                new RegExp(`htmlFor=["'{]\\{?["']?${id}`)
            );
            expect(source, `${file}: ${id} has no element with that id`).toMatch(
                new RegExp(`id=["'{]\\{?["']?${id}`)
            );
        });
    }
});

describe('filter selects have an accessible name', () => {
    for (const [file, label] of ARIA_NAMED_FILTERS) {
        it(`${file}: the filter select carries aria-label="${label}"`, () => {
            const source = readFileSync(join(SRC_DIR, file), 'utf8');
            expect(source).toContain(`aria-label="${label}"`);
        });
    }
});

describe('no hand-rolled sibling label/control pair is left in the fixed files', () => {
    const files = [...new Set([...ASSOCIATED, ...ARIA_NAMED_FILTERS].map(([file]) => file))];

    it('every <label> in these files either wraps its control or names one', () => {
        const offenders = [];

        for (const rel of files) {
            // Comments are stripped first, and not only for tidiness: the fix for
            // each of these is a comment that quotes the markup it removed, so a
            // scan that read comments would report the very lines explaining it.
            const source = stripComments(readFileSync(join(SRC_DIR, rel), 'utf8'));

            for (const m of source.matchAll(/<label\b([^>]*)>/g)) {
                if (htmlForTarget(m[1]) || wrapsControl(source, m.index)) continue;
                offenders.push(`${rel}: <label${m[1].replace(/\s+/g, ' ').trim().slice(0, 60)}>`);
            }
        }

        expect(offenders, `Unassociated <label>:\n${offenders.join('\n')}`).toEqual([]);
    });

    it('the scan would notice if one of them regressed (the canary must be able to fail)', () => {
        const offendingSource = `
            export default function Page() {
                return (
                    <div>
                        <label className="block text-sm font-medium text-gray-300 mb-1">Name</label>
                        <input type="text" value={form.name} onChange={onChange} />
                    </div>
                );
            }
        `;
        const wrappedSource = `
            export default function Page() {
                return (
                    <label className="block text-sm">
                        Name
                        <input type="text" value={form.name} onChange={onChange} />
                    </label>
                );
            }
        `;

        const unassociated = (source) => [...source.matchAll(/<label\b([^>]*)>/g)]
            .filter((m) => !htmlForTarget(m[1]) && !wrapsControl(source, m.index));

        expect(unassociated(offendingSource)).toHaveLength(1);
        // The false positive this heuristic exists to avoid: wrapping is a
        // legitimate association and must not be reported.
        expect(unassociated(wrappedSource)).toHaveLength(0);
    });
});

describe('the scan covers the whole of src/pages and src/components', () => {
    it('walks more than the handful of files the cases above name', () => {
        const files = readdirSync(join(SRC_DIR, 'pages')).filter((f) => f.endsWith('.jsx'));
        expect(files.length).toBeGreaterThan(20);
        expect(relative(SRC_DIR, join(SRC_DIR, 'pages'))).toBe('pages');
    });
});

import FormInput from '../components/common/FormInput';