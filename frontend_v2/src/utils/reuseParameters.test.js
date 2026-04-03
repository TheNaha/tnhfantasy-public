import { describe, expect, it } from 'vitest';

import {
    buildGeneratorStateFromMetadata,
    hydrateGeneratorStateModelVisuals,
} from './reuseParameters';

describe('buildGeneratorStateFromMetadata', () => {
    it('normalizes direct metadata fields and aliases for generator state', () => {
        const updates = buildGeneratorStateFromMetadata({
            prompt: 'test prompt',
            negativePrompt: 'test negative',
            seed: '12345',
            steps: '28',
            cfg: '6.5',
            sampler: 'euler_ancestral',
            scheduler: 'normal',
            width: '832',
            height: '1216',
            checkpoint: 'model_xl.safetensors',
            loras: [{ name: 'detail_lora.safetensors', weight: 0.8 }],
            controlnets: [{ control_net_name: 'lineart.safetensors', input: 'line.png', weight: 0.7 }],
            batchSize: 2,
        });

        expect(updates.prompt).toBe('test prompt');
        expect(updates.negativePrompt).toBe('test negative');
        expect(updates.seed).toBe(12345);
        expect(updates.steps).toBe(28);
        expect(updates.cfg).toBe(6.5);
        expect(updates.width).toBe(832);
        expect(updates.height).toBe(1216);
        expect(updates.batchSize).toBe(2);

        expect(updates.selectedCheckpoint).toEqual({
            name: 'model_xl.safetensors',
            display_name: 'model_xl.safetensors',
        });
        expect(updates.selectedLoras).toEqual([
            { name: 'detail_lora.safetensors', weight: 0.8, strength: 0.8 },
        ]);
        expect(updates.controlnets).toEqual([
            {
                control_net_name: 'lineart.safetensors',
                input: 'line.png',
                weight: 0.7,
                name: 'lineart.safetensors',
                image: 'line.png',
                strength: 0.7,
                preprocessor: 'None',
            },
        ]);
    });

    it('extracts reusable params from workflow when top-level metadata is incomplete', () => {
        const workflow = {
            nodes: {
                '1': {
                    class_type: 'CheckpointLoaderSimple',
                    inputs: { ckpt_name: 'checkpoint.safetensors' },
                },
                '2': {
                    class_type: 'LoraLoader',
                    inputs: {
                        model: ['1', 0],
                        clip: ['1', 1],
                        lora_name: 'style_lora.safetensors',
                        strength_model: 0.75,
                    },
                },
                '3': {
                    class_type: 'CLIPTextEncode',
                    inputs: { text: 'workflow prompt', clip: ['2', 1] },
                },
                '4': {
                    class_type: 'CLIPTextEncode',
                    inputs: { text: 'workflow negative', clip: ['2', 1] },
                },
                '5': {
                    class_type: 'ControlNetLoader',
                    inputs: { control_net_name: 'cn.safetensors' },
                },
                '6': {
                    class_type: 'LoadImage',
                    inputs: { image: 'input/control.png' },
                },
                '7': {
                    class_type: 'ControlNetApply',
                    inputs: {
                        conditioning: ['3', 0],
                        control_net: ['5', 0],
                        image: ['6', 0],
                        strength: 0.55,
                    },
                },
                '8': {
                    class_type: 'EmptyLatentImage',
                    inputs: { width: 896, height: 1152, batch_size: 1 },
                },
                '9': {
                    class_type: 'KSampler',
                    inputs: {
                        seed: 998877,
                        steps: 32,
                        cfg: 5.5,
                        sampler_name: 'dpmpp_2m',
                        scheduler: 'karras',
                        model: ['2', 0],
                        positive: ['3', 0],
                        negative: ['4', 0],
                        latent_image: ['8', 0],
                    },
                },
            },
        };

        const updates = buildGeneratorStateFromMetadata({ workflow });

        expect(updates.prompt).toBe('workflow prompt');
        expect(updates.negativePrompt).toBe('workflow negative');
        expect(updates.seed).toBe(998877);
        expect(updates.steps).toBe(32);
        expect(updates.cfg).toBe(5.5);
        expect(updates.sampler).toBe('dpmpp_2m');
        expect(updates.scheduler).toBe('karras');
        expect(updates.width).toBe(896);
        expect(updates.height).toBe(1152);
        expect(updates.selectedCheckpoint?.name).toBe('checkpoint.safetensors');
        expect(updates.selectedLoras).toEqual([
            { name: 'style_lora.safetensors', strength: 0.75 },
        ]);
        expect(updates.controlnets).toEqual([
            {
                name: 'cn.safetensors',
                image: 'input/control.png',
                strength: 0.55,
                preprocessor: 'None',
            },
        ]);
    });

    it('retains explicit empty loras/controlnets to clear previous state', () => {
        const updates = buildGeneratorStateFromMetadata({
            loras: [],
            controlnets: [],
        });

        expect(updates.selectedLoras).toEqual([]);
        expect(updates.controlnets).toEqual([]);
    });

    it('returns empty updates for invalid metadata payloads', () => {
        expect(buildGeneratorStateFromMetadata(null)).toEqual({});
        expect(buildGeneratorStateFromMetadata(undefined)).toEqual({});
        expect(buildGeneratorStateFromMetadata('not-an-object')).toEqual({});
    });

    it('hydrates checkpoint and lora visuals from catalog lookup when missing', async () => {
        const lookupModel = async (directory, modelName) => {
            if (directory === 'models/checkpoints' && modelName === 'nova_xl.safetensors') {
                return {
                    name: 'nova_xl.safetensors',
                    display_name: 'Nova XL',
                    civitai_id: 123,
                    preview: 'https://example.com/checkpoint-preview.jpg',
                };
            }

            if (directory === 'models/loras' && modelName === 'detail_lora.safetensors') {
                return {
                    name: 'detail_lora.safetensors',
                    display_name: 'Detail LoRA',
                    civitai_id: 456,
                    preview: 'https://example.com/lora-preview.jpg',
                };
            }

            return null;
        };

        const hydrated = await hydrateGeneratorStateModelVisuals({
            selectedCheckpoint: {
                name: 'nova_xl.safetensors',
                display_name: 'Nova XL',
            },
            selectedLoras: [
                {
                    name: 'detail_lora.safetensors',
                    strength: 0.8,
                },
            ],
        }, lookupModel);

        expect(hydrated.selectedCheckpoint?.preview).toBe('https://example.com/checkpoint-preview.jpg');
        expect(hydrated.selectedCheckpoint?.civitai_id).toBe(123);
        expect(hydrated.selectedLoras?.[0]?.preview).toBe('https://example.com/lora-preview.jpg');
        expect(hydrated.selectedLoras?.[0]?.civitai_id).toBe(456);
        expect(hydrated.selectedLoras?.[0]?.strength).toBe(0.8);
    });

    it('does not overwrite existing model visuals during hydration', async () => {
        const lookupModel = async () => ({
            preview: 'https://example.com/new-preview.jpg',
            civitai_id: 999,
        });

        const hydrated = await hydrateGeneratorStateModelVisuals({
            selectedCheckpoint: {
                name: 'checkpoint.safetensors',
                preview: 'https://example.com/existing-preview.jpg',
                civitai_id: 111,
            },
            selectedLoras: [
                {
                    name: 'my_lora.safetensors',
                    preview: 'https://example.com/existing-lora-preview.jpg',
                    civitai_id: 222,
                    strength: 1.0,
                },
            ],
        }, lookupModel);

        expect(hydrated.selectedCheckpoint?.preview).toBe('https://example.com/existing-preview.jpg');
        expect(hydrated.selectedCheckpoint?.civitai_id).toBe(111);
        expect(hydrated.selectedLoras?.[0]?.preview).toBe('https://example.com/existing-lora-preview.jpg');
        expect(hydrated.selectedLoras?.[0]?.civitai_id).toBe(222);
    });
});
