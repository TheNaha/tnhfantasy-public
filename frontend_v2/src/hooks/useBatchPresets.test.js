import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
    BATCH_SIZE_OPTIONS,
    DEFAULT_BATCH_PRESET,
    MAX_BATCH_WORKFLOWS,
    batchImageCount,
    batchLimitMessage,
    batchWorkflowCount,
    buildPreset,
    describeMissingModels,
    exceedsBatchLimit,
    findMissingModels,
    lorasFromSelectedLoras,
    lorasToRequestOptions,
    lorasToSelectedLoras,
    normalizePreset,
    parsePresetPayload,
    resolvePrompts,
    serializePreset,
    summarizePreset,
} from './useBatchPresets';

const INSTALLED = {
    checkpoints: [{ name: 'nova_xl.safetensors', display_name: 'Nova XL' }],
    loras: [{ name: 'style.safetensors' }, { name: 'detail.safetensors' }],
};

describe('normalizePreset', () => {
    it('fills every field of a garbage blob instead of leaving holes', () => {
        const preset = normalizePreset('not an object', 'Fallback');
        expect(preset.name).toBe('Fallback');
        expect(preset.steps).toBe(DEFAULT_BATCH_PRESET.steps);
        expect(preset.sampler).toBe(DEFAULT_BATCH_PRESET.sampler);
        expect(preset.loras).toEqual([]);
        expect(preset.prompts).toEqual([]);
    });

    it('rejects out-of-range and non-numeric numbers', () => {
        const preset = normalizePreset({
            steps: 5000, cfg: -3, clipSkip: 99, batchSize: 0, width: 'wide', height: -1,
        });
        expect(preset.steps).toBe(150);
        expect(preset.cfg).toBe(0);
        expect(preset.clipSkip).toBe(4);
        expect(preset.batchSize).toBe(1);
        expect(preset.width).toBe(DEFAULT_BATCH_PRESET.width);
        expect(preset.height).toBe(64);
    });

    it('falls back to a known seed mode and batch kind', () => {
        expect(normalizePreset({ seedMode: 'chaos' }).seedMode).toBe('random');
        expect(normalizePreset({ bakedType: 'nope' }).bakedType).toBe('character_sheet');
    });

    it('reads a legacy sizeKey into width/height', () => {
        const preset = normalizePreset({ sizeKey: 1 });
        expect(preset.width).toBe(BATCH_SIZE_OPTIONS[1].width);
        expect(preset.height).toBe(BATCH_SIZE_OPTIONS[1].height);
    });

    it('takes the filename out of a stored checkpoint object', () => {
        expect(normalizePreset({ checkpoint: { name: 'nova_xl.safetensors' } }).checkpoint)
            .toBe('nova_xl.safetensors');
    });

    it('drops blank prompts and blank LoRA filenames', () => {
        const preset = normalizePreset({
            prompts: ['  keep me  ', '', '   '],
            loras: [{ filename: 'style.safetensors', strength: 0.5 }, { filename: '  ' }, null, 'nope'],
        });
        expect(preset.prompts).toEqual(['keep me']);
        expect(preset.loras).toEqual([{ filename: 'style.safetensors', strength: 0.5 }]);
    });

    it('clamps a LoRA weight and lets a later row win a duplicate filename', () => {
        const preset = normalizePreset({
            loras: [
                { filename: 'style.safetensors', strength: 9 },
                { filename: 'style.safetensors', strength: 0.25 },
            ],
        });
        expect(preset.loras).toEqual([{ filename: 'style.safetensors', strength: 0.25 }]);
    });
});

describe('LoRA weights', () => {
    it('keeps the weight and drops the model object the store carries', () => {
        expect(lorasFromSelectedLoras([
            { name: 'style.safetensors', strength: 0.8, preview: 'data:image/png;base64,AAAA', metadata: { civitai_id: 7 } },
        ])).toEqual([{ filename: 'style.safetensors', strength: 0.8 }]);
    });

    it('defaults a missing weight to 1.0 and ignores nameless rows', () => {
        expect(lorasFromSelectedLoras([{ name: 'style.safetensors' }, { name: '' }, null]))
            .toEqual([{ filename: 'style.safetensors', strength: 1 }]);
    });

    it('speaks the backend LoraOption shape ({ name, strength }) on the wire', () => {
        expect(lorasToRequestOptions([{ filename: 'style.safetensors', strength: -0.35 }]))
            .toEqual([{ name: 'style.safetensors', strength: -0.35 }]);
    });

    it('preserves strengths beyond the standard -2..2 slider range (e.g. 3.0 or -2.5)', () => {
        expect(lorasFromSelectedLoras([
            { name: 'slider_extreme.safetensors', strength: 3.0 },
            { name: 'slider_negative.safetensors', strength: -2.5 },
        ])).toEqual([
            { filename: 'slider_extreme.safetensors', strength: 3.0 },
            { filename: 'slider_negative.safetensors', strength: -2.5 },
        ]);
    });

    it('round-trips a preset weight through the store shape and back', () => {
        const preset = normalizePreset({ loras: [{ filename: 'style.safetensors', strength: 0.65 }] });
        const inStore = lorasToSelectedLoras(preset.loras);
        expect(inStore).toEqual([{ name: 'style.safetensors', strength: 0.65 }]);
        expect(lorasFromSelectedLoras(inStore)).toEqual(preset.loras);
    });
});

describe('resolvePrompts', () => {
    it('leaves {char} and {scene} literal while their fields are empty', () => {
        expect(resolvePrompts(['portrait of {char}, {scene}'], {}))
            .toEqual(['portrait of {char}, {scene}']);
    });

    it('substitutes every placeholder at once, not one per preset type', () => {
        expect(resolvePrompts(['{char} in {scene} at {prompt}'], {
            charName: 'Elara', sceneName: 'Old Forest', basePrompt: 'sunset',
        })).toEqual(['Elara in Old Forest at sunset']);
    });

    it('replaces every occurrence, not just the first', () => {
        expect(resolvePrompts(['{char} and {char}'], { charName: 'Elara' }))
            .toEqual(['Elara and Elara']);
    });

    it('falls back to a label for an empty {prompt}', () => {
        expect(resolvePrompts(['{prompt}, style A'], {})).toEqual(['untitled concept, style A']);
    });
});

describe('batch limits', () => {
    it('counts submitted workflows, not images', () => {
        expect(batchWorkflowCount(4, 8)).toBe(4);
        expect(batchImageCount(4, 8)).toBe(32);
    });

    it('allows exactly the backend cap and rejects one more', () => {
        expect(exceedsBatchLimit(MAX_BATCH_WORKFLOWS)).toBe(false);
        expect(exceedsBatchLimit(MAX_BATCH_WORKFLOWS + 1)).toBe(true);
    });

    it('names the cap in the message so the user can act on it', () => {
        expect(batchLimitMessage(61)).toContain('61');
        expect(batchLimitMessage(61)).toContain(String(MAX_BATCH_WORKFLOWS));
    });

    it('mirrors the backend MAX_GENERATE_BATCH', () => {
        expect(MAX_BATCH_WORKFLOWS).toBe(60);
    });
});

describe('findMissingModels', () => {
    it('reports nothing when every reference is installed', () => {
        const preset = normalizePreset({
            checkpoint: 'nova_xl.safetensors',
            loras: [{ filename: 'style.safetensors', strength: 1 }],
        });
        expect(findMissingModels(preset, INSTALLED)).toEqual({
            missingCheckpoint: null, missingLoras: [], hasMissing: false,
        });
    });

    it('names the checkpoint and every LoRA that is not installed', () => {
        const preset = normalizePreset({
            checkpoint: 'ghost.safetensors',
            loras: [{ filename: 'style.safetensors', strength: 1 }, { filename: 'ghost_lora.safetensors', strength: 0.5 }],
        });
        const missing = findMissingModels(preset, INSTALLED);
        expect(missing.missingCheckpoint).toBe('ghost.safetensors');
        expect(missing.missingLoras).toEqual(['ghost_lora.safetensors']);
        expect(missing.hasMissing).toBe(true);
        expect(describeMissingModels(missing)).toContain('ghost.safetensors');
        expect(describeMissingModels(missing)).toContain('ghost_lora.safetensors');
    });

    it('does not flag a preset that leaves the checkpoint on auto', () => {
        expect(findMissingModels(normalizePreset({ checkpoint: '' }), INSTALLED).hasMissing).toBe(false);
    });
});

describe('summarizePreset', () => {
    it('describes the configuration, not just the name', () => {
        const summary = summarizePreset(normalizePreset({
            width: 512, height: 768, steps: 12, cfg: 4.5, sampler: 'dpmpp_sde',
            scheduler: 'karras', seedMode: 'fixed', checkpoint: 'nova_xl.safetensors',
            loras: [{ filename: 'style.safetensors', strength: 0.8 }],
        }));
        expect(summary).toContain('512×768');
        expect(summary).toContain('12 steps');
        expect(summary).toContain('CFG 4.5');
        expect(summary).toContain('dpmpp_sde/karras');
        expect(summary).toContain('fixed seed');
        expect(summary).toContain('nova_xl.safetensors');
        expect(summary).toContain('1 LoRA');
    });
});

describe('export / import', () => {
    let createObjectURL;

    beforeEach(() => {
        createObjectURL = vi.fn(() => 'blob:preset');
        vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('round-trips a preset through the file format', () => {
        const preset = buildPreset({
            name: 'Round Trip',
            loras: [{ filename: 'style.safetensors', strength: 0.42 }],
            steps: 33,
        });
        const parsed = parsePresetPayload(serializePreset('Round Trip', preset));
        expect(parsed).toEqual(preset);
        expect(parsed.loras).toEqual([{ filename: 'style.safetensors', strength: 0.42 }]);
    });

    it('accepts a bare preset object with no envelope', () => {
        expect(parsePresetPayload(JSON.stringify({ name: 'Bare', steps: 9 })).name).toBe('Bare');
    });

    it('rejects a file that is not a preset, with a readable reason', () => {
        expect(() => parsePresetPayload('nope')).toThrow('not valid JSON');
        expect(() => parsePresetPayload(JSON.stringify({ kind: 'something-else' })))
            .toThrow('not a TNHFantasy batch preset');
        expect(() => parsePresetPayload(JSON.stringify({ steps: 4 }))).toThrow('no name');
    });

    it('downloads through an object URL and revokes it', async () => {
        const { downloadPresetJson } = await import('./useBatchPresets');
        const clicks = [];
        const originalCreate = document.createElement.bind(document);
        vi.spyOn(document, 'createElement').mockImplementation((tag) => {
            const element = originalCreate(tag);
            if (tag === 'a') {
                element.click = () => clicks.push(element.download);
            }
            return element;
        });
        downloadPresetJson('My Preset', buildPreset({ name: 'My Preset' }));
        expect(createObjectURL).toHaveBeenCalledTimes(1);
        expect(clicks).toEqual(['batch-preset-My_Preset.json']);
        document.createElement.mockRestore();
    });
});
