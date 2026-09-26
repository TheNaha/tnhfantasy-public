/**
 * The app had 325 arbitrary font sizes and ~475 hardcoded colour literals, and no
 * token layer at all — `index.css` had no `@theme` block, so every colour was a
 * stock Tailwind default picked per component. The greys drifted subtly between
 * the chat panel, the gallery toolbar and the dashboard cards, and 270 elements
 * rendered below 11px.
 *
 * `index.css` now defines the scale. This test is the guard so it stays true:
 * a legibility floor that is only a convention is not a floor.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';

const SRC = join(process.cwd(), 'src');

function walk(dir, out = []) {
    for (const entry of readdirSync(dir)) {
        if (entry === 'node_modules' || entry === '__pycache__') continue;
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) walk(full, out);
        else if (['.js', '.jsx', '.css'].includes(extname(full))) out.push(full);
    }
    return out;
}

const FILES = walk(SRC);
const CSS = readFileSync(join(SRC, 'index.css'), 'utf8');

describe('design tokens', () => {
    it('index.css declares a theme layer', () => {
        expect(CSS).toMatch(/@theme\s*\{/);
    });

    it('declares a type scale with an 11px floor', () => {
        // --text-2xs is 0.6875rem = 11px. It exists because 8/9/10px text was in
        // use on 325 elements and none of it was legible.
        expect(CSS).toMatch(/--text-2xs:\s*0\.6875rem/);
    });

    it('names no colour after a Tailwind font-size step', () => {
        // Tailwind generates `text-<name>` from every `--color-<name>`, and
        // `text-xs`/`text-sm`/`text-base`/`text-lg` are *also* font sizes. A
        // theme colour named after one of them makes the utility resolve to a
        // colour instead, shadowing the size utility of the same name across
        // the whole app. `--color-base` did exactly that: 23 `text-base`
        // elements silently lost their size and inherited the page background
        // as their text colour, and nothing failed.
        const SIZE_NAMES = ['xs', 'sm', 'base', 'lg', 'xl', '2xl', '3xl', '4xl', '5xl',
                            '6xl', '7xl', '8xl', '9xl'];
        const theme = CSS.slice(CSS.indexOf('@theme'), CSS.indexOf('@theme') + 4000);
        const collisions = [...theme.matchAll(/--color-([a-z0-9-]+):/g)]
            .map((m) => m[1])
            .filter((name) => SIZE_NAMES.includes(name));
        expect(
            collisions,
            `these theme colours shadow the font-size utility text-<name>: ${collisions.join(', ')}`
        ).toEqual([]);
    });

    it('enforces the floor in a rule that can actually win the cascade', () => {
        // Unlayered on purpose. Tailwind v4 emits utilities inside
        // `@layer theme, base, components, utilities`, so a rule in `@layer base`
        // loses to any `text-[Npx]` — which is exactly what the floor has to
        // beat. This test fails if someone "tidies" it back into a layer.
        const floor = CSS.slice(CSS.indexOf('.text-\\[8px\\]'));
        expect(floor).toBeTruthy();
        expect(floor.slice(0, 400)).not.toMatch(/@layer/);
    });
});

describe('type scale is respected', () => {
    it('no component hardcodes a font size below 11px', () => {
        const offenders = [];
        for (const file of FILES) {
            if (file.endsWith('.css')) continue;
            const src = readFileSync(file, 'utf8');
            for (const match of src.matchAll(/text-\[(\d+(?:\.\d+)?)px\]/g)) {
                if (parseFloat(match[1]) < 11) {
                    offenders.push(`${file.replace(SRC + '/', '')}: text-[${match[1]}px]`);
                }
            }
        }
        expect(offenders, `sub-11px text is not legible:\n${offenders.join('\n')}`).toEqual([]);
    });

    it('uses the scale rather than arbitrary pixel sizes for body text', () => {
        // Arbitrary sizes are not banned — a one-off optical adjustment is fine.
        // What must not creep back is the *bulk* of small text bypassing the
        // scale, which is how 325 of them accumulated.
        const arbitrary = FILES
            .filter((f) => !f.endsWith('.css'))
            .reduce((n, f) => n + [...readFileSync(f, 'utf8').matchAll(/text-\[\d+px\]/g)].length, 0);
        expect(arbitrary, 'arbitrary pixel font sizes are creeping back in').toBeLessThanOrEqual(20);
    });
});

describe('colour literals are not growing', () => {
    it('hardcoded colour count is not increasing', () => {
        // ~390 hex/rgba literals in JSX and 85 arbitrary Tailwind colour values
        // when this test was written. The scale exists so they can be migrated;
        // this stops the number going the other way in the meantime. Lower it
        // when you do a migration pass.
        const hexish = FILES
            .filter((f) => !f.endsWith('.css'))
            .reduce((n, f) => n + [...readFileSync(f, 'utf8').matchAll(/#[0-9a-fA-F]{6}\b|rgba?\(\s*\d/g)].length, 0);
        expect(hexish, 'hardcoded colours are creeping back in').toBeLessThanOrEqual(400);
    });
});
