import { describe, it, expect } from 'vitest';
import { getModelWithVersion, getCheckpointDisplayName, checkpointName } from './modelDisplay';

describe('modelDisplay utils', () => {
    it('getCheckpointDisplayName cleans up .safetensors', () => {
        expect(getCheckpointDisplayName({ checkpoint: 'model.safetensors' })).toBe('model');
        expect(getCheckpointDisplayName({ metadata: { checkpoint: 'model2.safetensors' } })).toBe('model2');
        expect(getCheckpointDisplayName(null)).toBe(null);
    });

    it('checkpointName extracts string or object name', () => {
        expect(checkpointName({ checkpoint: 'ckpt.safetensors' })).toBe('ckpt.safetensors');
        expect(checkpointName({ checkpoint: { name: 'ckpt2.safetensors' } })).toBe('ckpt2.safetensors');
        expect(checkpointName(null)).toBe(null);
    });

    describe('getModelWithVersion', () => {
        const baseModel = {
            id: 'm1',
            name: 'default_lora.safetensors',
            display_name: 'Character LoRA',
            civitai_id: 12345,
            preview: 'https://example.com/default.jpg',
            base_model: 'SDXL',
            versions: [
                {
                    id: 'v1',
                    civitai_version_id: 101,
                    name: 'Casual Outfit',
                    base_model: 'SDXL',
                    trained_words: ['casual, shirt'],
                    file: { filename: 'char_casual_101.safetensors', size_kb: 50000 },
                    images: [{ url: 'https://example.com/casual.jpg' }],
                },
                {
                    id: 'v2',
                    civitai_version_id: 102,
                    name: 'Swimsuit Outfit',
                    base_model: 'Illustrious',
                    trained_words: ['swimsuit, bikini'],
                    file: { filename: 'char_swimsuit_102.safetensors', size_kb: 52000 },
                    images: [{ url: 'https://example.com/swimsuit.jpg' }],
                },
            ],
        };

        it('returns original model if version is null', () => {
            expect(getModelWithVersion(baseModel, null)).toBe(baseModel);
        });

        it('hydrates model with version specific file, preview, base_model, and trigger words', () => {
            const v2 = baseModel.versions[1];
            const hydrated = getModelWithVersion(baseModel, v2);

            expect(hydrated.name).toBe('char_swimsuit_102.safetensors');
            expect(hydrated.display_name).toBe('Character LoRA');
            expect(hydrated.preview).toBe('https://example.com/swimsuit.jpg');
            expect(hydrated.base_model).toBe('Illustrious');
            expect(hydrated.trained_words).toEqual(['swimsuit, bikini']);
            expect(hydrated.selectedVersionId).toBe('v2');
            expect(hydrated.default_version).toBe('Swimsuit Outfit');
        });
    });
});
