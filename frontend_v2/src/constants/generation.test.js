import { describe, expect, it } from 'vitest';

import { SAMPLERS, SCHEDULERS } from './generation';

/**
 * The sampler and scheduler vocabularies must match the installed ComfyUI.
 *
 * These two dropdowns are the ONLY allowlist in the path: the backend passes
 * `options.sampler` and `options.scheduler` straight into
 * `core/workflow_builder.py` as `sampler_name`/`scheduler`, with no validation of
 * its own. So an entry missing here is a value no user can submit, which is how
 * this file came to hold 6 of ComfyUI's 47 samplers and 4 of its 9 schedulers —
 * `simple`, `ddim_uniform`, `beta`, `linear_quadratic` and `kl_optimal` were
 * unreachable from the UI entirely, and the reported symptom was a missing
 * scheduler called "simple".
 *
 * The counts are pinned rather than left to drift silently: a list that shrinks
 * back to a familiar handful compiles fine and fails only when a user cannot
 * find a value they used yesterday.
 */

describe('the sampler vocabulary matches KSampler', () => {
    it('carries every sampler the installed ComfyUI accepts', () => {
        // 45, parsed out of `curl http://100.150.0.26:8188/object_info/KSampler`
        // (provider `colab-one`) on 2026-10-15 — machine-parsed, because a
        // hand-count of the printed list read 47 while the list held 45, and the
        // count is the whole point of asserting it. See the header of
        // `constants/generation.js` for the provenance.
        expect(SAMPLERS).toHaveLength(45);
    });

    it('keeps the ones the UI shipped with, so no existing preset breaks', () => {
        // `generatorStore` defaults, the per-model presets and the reuse-parameters
        // path all name these by value; each must still resolve to an <option>.
        for (const known of [
            'euler',
            'euler_ancestral',
            'dpmpp_2m',
            'dpmpp_sde',
            'ddim',
            'uni_pc',
        ]) {
            expect(SAMPLERS).toContain(known);
        }
    });

    it('has no duplicate entries', () => {
        // A duplicate key in `SAMPLERS.map` is a React warning, and on a
        // two-element duplicate it renders one <option>, so the value looks
        // missing when it is present.
        expect(new Set(SAMPLERS).size).toBe(SAMPLERS.length);
    });
});

describe('the scheduler vocabulary matches KSampler', () => {
    it('carries every scheduler the installed ComfyUI accepts', () => {
        expect(SCHEDULERS).toHaveLength(9);
    });

    it('includes the schedulers the UI used to omit', () => {
        // The complete set beyond the four that shipped. `simple` is the one that
        // was asked for; the other four were missing for the same reason.
        expect(SCHEDULERS).toEqual(
            expect.arrayContaining([
                'simple',
                'ddim_uniform',
                'beta',
                'linear_quadratic',
                'kl_optimal',
            ])
        );
    });

    it('keeps the ones that shipped with, so no existing preset breaks', () => {
        for (const known of ['normal', 'karras', 'exponential', 'sgm_uniform']) {
            expect(SCHEDULERS).toContain(known);
        }
    });

    it('has no duplicate entries', () => {
        expect(new Set(SCHEDULERS).size).toBe(SCHEDULERS.length);
    });

    it('contains no empty or non-string entries', () => {
        for (const value of SCHEDULERS) {
            expect(typeof value).toBe('string');
            expect(value).not.toBe('');
        }
    });
});
