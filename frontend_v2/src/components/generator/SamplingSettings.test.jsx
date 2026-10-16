import { render, screen, within, act } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

import SamplingSettings from './SamplingSettings';
import { SAMPLERS, SCHEDULERS } from '../../constants/generation';
import { useGeneratorStore } from '../../store/generatorStore';
import useSettingsStore from '../../store/settingsStore';

/**
 * The sampler and scheduler dropdowns in Simple Generator.
 *
 * The list used to hold 6 of ComfyUI's 45 samplers and 4 of its 9 schedulers, so
 * `simple`, `ddim_uniform`, `beta`, `linear_quadratic` and `kl_optimal` could not
 * be selected at all. The backend validates nothing — `core/workflow_builder.py`
 * writes `options.sampler` straight into `sampler_name` — so the `<select>`
 * options were the only allowlist in the path.
 *
 * The second half of this file is the part that keeps the first half honest: a
 * value reused off an old image can be outside the vocabulary, and a `<select>`
 * whose `value` has no `<option>` renders BLANK and submits an empty string,
 * deleting the parameter the user is trying to reuse.
 */

const MODALS = [
    { id: 'x', title: 'x', content: 'x', actions: [] },
];

describe('SamplingSettings option coverage', () => {
    beforeEach(() => {
        useSettingsStore.setState({
            settings: {
                ...useSettingsStore.getState().settings,
                generator: { autoRandomizeSeed: false },
            },
        });
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('offers every scheduler the installed ComfyUI accepts', () => {
        render(<SamplingSettings modals={MODALS} />);
        const scheduler = screen.getByLabelText('Scheduler');
        const values = within(scheduler)
            .getAllByRole('option')
            .map((o) => o.value);
        expect(values).toEqual(SCHEDULERS);
        // The one that was missing when this was asked for.
        expect(values).toContain('simple');
    });

    it('offers every sampler the installed ComfyUI accepts', () => {
        render(<SamplingSettings modals={MODALS} />);
        const sampler = screen.getByLabelText('Sampler');
        const values = within(sampler)
            .getAllByRole('option')
            .map((o) => o.value);
        expect(values).toEqual(SAMPLERS);
    });

    it('selecting a newly-available scheduler commits it', () => {
        const setScheduler = vi.fn();
        useGeneratorStore.setState({ scheduler: 'normal', setScheduler });

        render(<SamplingSettings modals={MODALS} />);
        act(() => {
            const select = screen.getByLabelText('Scheduler');
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLSelectElement.prototype,
                'value'
            ).set;
            setter.call(select, 'simple');
            select.dispatchEvent(new Event('change', { bubbles: true }));
        });

        expect(setScheduler).toHaveBeenCalledWith('simple');
    });

    it('selecting a newly-available sampler commits it', () => {
        const setSampler = vi.fn();
        useGeneratorStore.setState({ sampler: 'euler', setSampler });

        render(<SamplingSettings modals={MODALS} />);
        act(() => {
            const select = screen.getByLabelText('Sampler');
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLSelectElement.prototype,
                'value'
            ).set;
            setter.call(select, 'dpmpp_3m_sde');
            select.dispatchEvent(new Event('change', { bubbles: true }));
        });

        expect(setSampler).toHaveBeenCalledWith('dpmpp_3m_sde');
    });
});

describe('a reused value outside the vocabulary', () => {
    beforeEach(() => {
        useSettingsStore.setState({
            settings: {
                ...useSettingsStore.getState().settings,
                generator: { autoRandomizeSeed: false },
            },
        });
    });

    it('still renders, rather than showing a blank control', () => {
        // The whole reason `withCurrentOption` exists. `reuseParameters` reads
        // scheduler off stored image metadata, and an image from another rig can
        // carry a value this ComfyUI does not list.
        useGeneratorStore.setState({
            sampler: 'euler',
            scheduler: 'beta_twist_not_in_this_comfy',
            setSampler: vi.fn(),
            setScheduler: vi.fn(),
            lockedParams: {},
        });

        render(<SamplingSettings modals={MODALS} />);
        const scheduler = screen.getByLabelText('Scheduler');
        const values = within(scheduler)
            .getAllByRole('option')
            .map((o) => o.value);

        expect(values[0]).toBe('beta_twist_not_in_this_comfy');
        // And the vocabulary is still there, in order, below it.
        expect(values.slice(1)).toEqual(SCHEDULERS);
        // The control is NOT blank — this is the assertion that fails on the
        // un-patched `SCHEDULERS.map(...)` form.
        expect(scheduler.value).toBe('beta_twist_not_in_this_comfy');
    });

    it('says the value came from elsewhere, so a blank-looking result is explained', () => {
        useGeneratorStore.setState({
            sampler: 'euler',
            scheduler: 'beta_twist_not_in_this_comfy',
            setSampler: vi.fn(),
            setScheduler: vi.fn(),
            lockedParams: {},
        });

        render(<SamplingSettings modals={MODALS} />);
        expect(screen.getByText(/not in this comfyui's scheduler list/i)).toBeTruthy();
    });

    it('says nothing about an unrecognised value when the form is untouched', () => {
        useGeneratorStore.setState({
            sampler: 'euler',
            scheduler: 'karras',
            setSampler: vi.fn(),
            setScheduler: vi.fn(),
            lockedParams: {},
        });

        render(<SamplingSettings modals={MODALS} />);
        expect(screen.queryByText(/not in this comfyui's sampler list/i)).toBeNull();
        expect(screen.queryByText(/not in this comfyui's scheduler list/i)).toBeNull();
    });
});
