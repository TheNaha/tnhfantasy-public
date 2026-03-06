import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock zustand persist middleware
vi.mock('zustand/middleware', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        persist: (fn) => fn,
    };
});

describe('useGeneratorStore', () => {
    let useGeneratorStore;

    beforeEach(async () => {
        vi.resetModules();
        const mod = await import('../store/generatorStore.js');
        useGeneratorStore = mod.useGeneratorStore;
    });

    describe('initial state', () => {
        it('has a default prompt', () => {
            const { prompt } = useGeneratorStore.getState();
            expect(typeof prompt).toBe('string');
            expect(prompt.length).toBeGreaterThan(0);
        });

        it('has default negative prompt', () => {
            const { negativePrompt } = useGeneratorStore.getState();
            expect(typeof negativePrompt).toBe('string');
        });

        it('has default steps of 25', () => {
            const { steps } = useGeneratorStore.getState();
            expect(steps).toBe(25);
        });

        it('has default cfg of 7.0', () => {
            const { cfg } = useGeneratorStore.getState();
            expect(cfg).toBe(7.0);
        });

        it('has default sampler of euler', () => {
            const { sampler } = useGeneratorStore.getState();
            expect(sampler).toBe('euler');
        });

        it('has default dimensions 1024x1024', () => {
            const { width, height } = useGeneratorStore.getState();
            expect(width).toBe(1024);
            expect(height).toBe(1024);
        });

        it('has default batchSize of 1', () => {
            const { batchSize } = useGeneratorStore.getState();
            expect(batchSize).toBe(1);
        });

        it('starts with no checkpoint selected', () => {
            const { selectedCheckpoint } = useGeneratorStore.getState();
            expect(selectedCheckpoint).toBeNull();
        });

        it('starts with empty loras', () => {
            const { selectedLoras } = useGeneratorStore.getState();
            expect(selectedLoras).toEqual([]);
        });

        it('has hiresFix disabled by default', () => {
            const { hiresFix } = useGeneratorStore.getState();
            expect(hiresFix).toBe(false);
        });

        it('has adetailer disabled by default', () => {
            const { adetailer } = useGeneratorStore.getState();
            expect(adetailer).toBe(false);
        });

        it('has default presets', () => {
            const { savedPresets } = useGeneratorStore.getState();
            expect(savedPresets.length).toBeGreaterThan(0);
        });
    });

    describe('basic setters', () => {
        it('setPrompt updates prompt', () => {
            const { setPrompt } = useGeneratorStore.getState();
            setPrompt('a cat on a couch');
            expect(useGeneratorStore.getState().prompt).toBe('a cat on a couch');
        });

        it('setNegativePrompt updates negativePrompt', () => {
            const { setNegativePrompt } = useGeneratorStore.getState();
            setNegativePrompt('ugly, deformed');
            expect(useGeneratorStore.getState().negativePrompt).toBe('ugly, deformed');
        });

        it('setSeed updates seed', () => {
            const { setSeed } = useGeneratorStore.getState();
            setSeed(99999);
            expect(useGeneratorStore.getState().seed).toBe(99999);
        });

        it('setSteps updates steps', () => {
            const { setSteps } = useGeneratorStore.getState();
            setSteps(30);
            expect(useGeneratorStore.getState().steps).toBe(30);
        });

        it('setCfg updates cfg', () => {
            const { setCfg } = useGeneratorStore.getState();
            setCfg(4.5);
            expect(useGeneratorStore.getState().cfg).toBe(4.5);
        });

        it('setWidth and setHeight update dimensions', () => {
            const { setWidth, setHeight } = useGeneratorStore.getState();
            setWidth(768);
            setHeight(512);
            const state = useGeneratorStore.getState();
            expect(state.width).toBe(768);
            expect(state.height).toBe(512);
        });

        it('setBatchSize updates batchSize', () => {
            const { setBatchSize } = useGeneratorStore.getState();
            setBatchSize(4);
            expect(useGeneratorStore.getState().batchSize).toBe(4);
        });
    });

    describe('randomizeSeed', () => {
        it('sets a new random seed', () => {
            const { setSeed, randomizeSeed } = useGeneratorStore.getState();
            setSeed(42);
            randomizeSeed();
            const { seed } = useGeneratorStore.getState();
            expect(typeof seed).toBe('number');
            expect(seed).toBeGreaterThanOrEqual(0);
        });
    });

    describe('LoRA management', () => {
        it('addLora adds an empty lora entry', () => {
            const { addLora } = useGeneratorStore.getState();
            addLora();
            const { selectedLoras } = useGeneratorStore.getState();
            expect(selectedLoras.length).toBe(1);
            expect(selectedLoras[0]).toEqual({ name: '', strength: 1.0 });
        });

        it('addLora can add multiple entries', () => {
            const { addLora } = useGeneratorStore.getState();
            addLora();
            addLora();
            expect(useGeneratorStore.getState().selectedLoras.length).toBe(2);
        });

        it('removeLora removes entry at index', () => {
            const { addLora, removeLora } = useGeneratorStore.getState();
            addLora();
            addLora();
            removeLora(0);
            expect(useGeneratorStore.getState().selectedLoras.length).toBe(1);
        });

        it('updateLora updates field for lora at index', () => {
            const { addLora, updateLora } = useGeneratorStore.getState();
            addLora();
            updateLora(0, 'strength', 0.75);
            const { selectedLoras } = useGeneratorStore.getState();
            expect(selectedLoras[0].strength).toBe(0.75);
        });

        it('updateLora with model field spreads model properties', () => {
            const { addLora, updateLora } = useGeneratorStore.getState();
            addLora();
            updateLora(0, 'model', { name: 'lora.pt', display_name: 'My LoRA', preview: 'preview.jpg' });
            const { selectedLoras } = useGeneratorStore.getState();
            expect(selectedLoras[0].name).toBe('lora.pt');
            expect(selectedLoras[0].display_name).toBe('My LoRA');
        });

        it('updateLora with model preserves existing strength', () => {
            const { addLora, updateLora } = useGeneratorStore.getState();
            addLora();
            updateLora(0, 'strength', 0.6);
            updateLora(0, 'model', { name: 'lora.pt' });
            const { selectedLoras } = useGeneratorStore.getState();
            expect(selectedLoras[0].strength).toBe(0.6);
        });
    });

    describe('setSelectedCheckpoint with auto-apply', () => {
        it('sets checkpoint without auto-apply when autoApplyModelSettings is false', () => {
            const { setAutoApplyModelSettings, setSelectedCheckpoint } = useGeneratorStore.getState();
            setAutoApplyModelSettings(false);
            const checkpoint = { name: 'model.safetensors', base_model: 'flux' };
            setSelectedCheckpoint(checkpoint);
            // Steps should NOT have changed to flux defaults
            const { selectedCheckpoint } = useGeneratorStore.getState();
            expect(selectedCheckpoint).toEqual(checkpoint);
        });

        it('auto-applies sdxl settings when checkpoint has sdxl base model', () => {
            const { setAutoApplyModelSettings, setSelectedCheckpoint } = useGeneratorStore.getState();
            setAutoApplyModelSettings(true);
            setSelectedCheckpoint({ name: 'model.safetensors', base_model: 'SDXL' });
            const { steps, width, height } = useGeneratorStore.getState();
            expect(steps).toBe(30);
            expect(width).toBe(1024);
            expect(height).toBe(1024);
        });

        it('auto-applies flux settings when checkpoint name contains flux', () => {
            const { setAutoApplyModelSettings, setSelectedCheckpoint } = useGeneratorStore.getState();
            setAutoApplyModelSettings(true);
            setSelectedCheckpoint({ name: 'flux_dev.safetensors' });
            const { steps, cfg } = useGeneratorStore.getState();
            expect(steps).toBe(20);
            expect(cfg).toBe(1.0);
        });

        it('auto-applies sd15 settings for sd15 base model', () => {
            const { setAutoApplyModelSettings, setSelectedCheckpoint } = useGeneratorStore.getState();
            setAutoApplyModelSettings(true);
            setSelectedCheckpoint({ name: 'model.safetensors', base_model: 'SD 1.5' });
            const { steps, width, height } = useGeneratorStore.getState();
            expect(steps).toBe(25);
            expect(width).toBe(512);
            expect(height).toBe(768);
        });
    });

    describe('applyModelSettings', () => {
        it('applies pony settings', () => {
            const { applyModelSettings } = useGeneratorStore.getState();
            const result = applyModelSettings('pony');
            expect(result).toBe(true);
            const { sampler, scheduler } = useGeneratorStore.getState();
            expect(sampler).toBe('dpmpp_2m');
            expect(scheduler).toBe('karras');
        });

        it('returns false for unknown model type', () => {
            const { applyModelSettings } = useGeneratorStore.getState();
            const result = applyModelSettings('unknown_model');
            expect(result).toBe(false);
        });

        it('applies illustrious settings', () => {
            const { applyModelSettings } = useGeneratorStore.getState();
            applyModelSettings('illustrious');
            const { sampler } = useGeneratorStore.getState();
            expect(sampler).toBe('euler_ancestral');
        });
    });

    describe('addTriggerWords', () => {
        it('appends trigger words to prompt', () => {
            const { setPrompt, addTriggerWords } = useGeneratorStore.getState();
            setPrompt('a cat');
            addTriggerWords(['photorealistic', 'detailed']);
            const { prompt } = useGeneratorStore.getState();
            expect(prompt).toContain('photorealistic');
            expect(prompt).toContain('detailed');
        });

        it('skips words already in prompt', () => {
            const { setPrompt, addTriggerWords } = useGeneratorStore.getState();
            setPrompt('photorealistic cat');
            addTriggerWords(['photorealistic']);
            const { prompt } = useGeneratorStore.getState();
            // Should not add duplicate
            expect(prompt).toBe('photorealistic cat');
        });

        it('handles null words gracefully', () => {
            const { addTriggerWords } = useGeneratorStore.getState();
            expect(() => addTriggerWords(null)).not.toThrow();
        });
    });

    describe('preset management', () => {
        it('addPreset adds a new preset', () => {
            const { addPreset } = useGeneratorStore.getState();
            const initialCount = useGeneratorStore.getState().savedPresets.length;
            addPreset({ name: 'My Preset', description: 'Test', data: { steps: 15 } });
            expect(useGeneratorStore.getState().savedPresets.length).toBe(initialCount + 1);
        });

        it('addPreset assigns an id', () => {
            const { addPreset } = useGeneratorStore.getState();
            addPreset({ name: 'Preset', data: {} });
            const presets = useGeneratorStore.getState().savedPresets;
            const newPreset = presets[presets.length - 1];
            expect(newPreset.id).toBeDefined();
        });

        it('removePreset removes preset by id', () => {
            const { addPreset, removePreset } = useGeneratorStore.getState();
            addPreset({ name: 'To Remove', data: {} });
            const presets = useGeneratorStore.getState().savedPresets;
            const lastPreset = presets[presets.length - 1];
            removePreset(lastPreset.id);
            const updated = useGeneratorStore.getState().savedPresets;
            expect(updated.find(p => p.id === lastPreset.id)).toBeUndefined();
        });
    });

    describe('img2img state', () => {
        it('setSourceImage stores source image', () => {
            const { setSourceImage } = useGeneratorStore.getState();
            const img = { filename: 'test.png', width: 512, height: 512 };
            setSourceImage(img);
            expect(useGeneratorStore.getState().sourceImage).toEqual(img);
        });

        it('clearSourceImage clears both source image and mask', () => {
            const { setSourceImage, setMaskImage, clearSourceImage } = useGeneratorStore.getState();
            setSourceImage({ filename: 'test.png' });
            setMaskImage('data:image/png;base64,...');
            clearSourceImage();
            const { sourceImage, maskImage } = useGeneratorStore.getState();
            expect(sourceImage).toBeNull();
            expect(maskImage).toBeNull();
        });

        it('setDenoise updates denoise strength', () => {
            const { setDenoise } = useGeneratorStore.getState();
            setDenoise(0.4);
            expect(useGeneratorStore.getState().denoise).toBe(0.4);
        });
    });

    describe('setAll', () => {
        it('bulk updates multiple state fields', () => {
            const { setAll } = useGeneratorStore.getState();
            setAll({ prompt: 'bulk prompt', steps: 15, cfg: 5.0 });
            const state = useGeneratorStore.getState();
            expect(state.prompt).toBe('bulk prompt');
            expect(state.steps).toBe(15);
            expect(state.cfg).toBe(5.0);
        });
    });
});
