import { describe, expect, it } from 'vitest';

import { withCurrentOption, isOutsideVocabulary } from './options';

/**
 * A `<select>` whose `value` has no matching `<option>` renders as BLANK.
 *
 * `reuseParameters` reads `sampler_name` and `scheduler` off stored image
 * metadata and pre-fills the generator with them. An imported image, or one
 * generated on a rig whose ComfyUI differs from this one, can carry a value the
 * vocabulary does not list — and without this helper the control showed nothing
 * and the next submit sent an empty string, deleting the user's own parameter on
 * the screen whose whole job is reproducing an image.
 */

const KNOWN = ['simple', 'sgm_uniform', 'karras', 'exponential', 'normal'];

describe('withCurrentOption', () => {
    it('leaves the list alone when the value is already known', () => {
        expect(withCurrentOption(KNOWN, 'karras')).toBe(KNOWN);
    });

    it('puts an unknown value first, so it is what the user sees', () => {
        expect(withCurrentOption(KNOWN, 'my_custom_sampler')).toEqual([
            'my_custom_sampler',
            ...KNOWN,
        ]);
    });

    it('does not mutate the vocabulary it was given', () => {
        // The caller renders this per render; a push would grow the module-level
        // array one entry per keystroke of an unrelated field.
        const source = [...KNOWN];
        withCurrentOption(source, 'x');
        expect(source).toEqual(KNOWN);
        expect(KNOWN).toHaveLength(5);
    });

    it.each([null, undefined, ''])('treats %p as "nothing selected", not as an unknown value', (value) => {
        expect(withCurrentOption(KNOWN, value)).toBe(KNOWN);
    });

    it('still surfaces an unknown value when nothing is known either', () => {
        // An empty vocabulary is a degenerate case, but the contract does not
        // bend: the caller's value must be renderable, or the select shows blank
        // and submits ''. Asserting `[]` here would be asserting the bug.
        expect(withCurrentOption([], 'anything')).toEqual(['anything']);
    });
});

describe('isOutsideVocabulary', () => {
    it('is false for a value the list contains', () => {
        expect(isOutsideVocabulary(KNOWN, 'karras')).toBe(false);
    });

    it('is true for a value the list does not contain', () => {
        expect(isOutsideVocabulary(KNOWN, 'beta')).toBe(true);
    });

    it.each([null, undefined, ''])('is false for %p, because nothing is selected yet', (value) => {
        // Marking an untouched form as carrying an unrecognized sampler is noise.
        expect(isOutsideVocabulary(KNOWN, value)).toBe(false);
    });
});
