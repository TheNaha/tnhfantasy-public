import { describe, it, expect } from 'vitest';
import {
    isNegativeEmbedding,
    cleanPrompt,
    getShortEmbeddingName,
    parseActiveEmbeddings,
    hasEmbedding,
    getEmbeddingWeight,
    toggleEmbeddingInPrompt,
    removeEmbeddingFromPrompt,
    setEmbeddingWeightInPrompt,
} from './embeddingHelpers';

describe('embeddingHelpers', () => {
    describe('isNegativeEmbedding', () => {
        it('detects common negative embedding names', () => {
            expect(isNegativeEmbedding('lazyneg')).toBe(true);
            expect(isNegativeEmbedding('lazyneg.safetensors')).toBe(true);
            expect(isNegativeEmbedding('badhandv4')).toBe(true);
            expect(isNegativeEmbedding('easynegative')).toBe(true);
            expect(isNegativeEmbedding('fastnegative_v2')).toBe(true);
            expect(isNegativeEmbedding('lazydn')).toBe(true);
            expect(isNegativeEmbedding('worst-anatomy')).toBe(true);
        });

        it('detects positive/style embedding names as non-negative', () => {
            expect(isNegativeEmbedding('lazypos')).toBe(false);
            expect(isNegativeEmbedding('lazyreal')).toBe(false);
            expect(isNegativeEmbedding('lazympos')).toBe(false);
            expect(isNegativeEmbedding('masterpiece_style')).toBe(false);
            expect(isNegativeEmbedding('anime_enhance')).toBe(false);
        });
    });

    describe('cleanPrompt', () => {
        it('cleans redundant commas and whitespace', () => {
            expect(cleanPrompt('1girl, , 2girls,  ')).toBe('1girl, 2girls');
            expect(cleanPrompt(', 1girl, ')).toBe('1girl');
            expect(cleanPrompt('')).toBe('');
        });

        it('strictly preserves newlines and paragraph breaks', () => {
            const multiline = '1girl, masterpiece\n\ncinematic lighting, ultra detailed';
            expect(cleanPrompt(multiline)).toBe('1girl, masterpiece\n\ncinematic lighting, ultra detailed');

            const withDanglingCommas = '1girl, ,\nmasterpiece, \n\n, cinematic lighting, 8k, ';
            expect(cleanPrompt(withDanglingCommas)).toBe('1girl\nmasterpiece\n\ncinematic lighting, 8k');
        });
    });

    describe('getShortEmbeddingName', () => {
        it('shortens CivitAI pack embeddings cleanly', () => {
            expect(getShortEmbeddingName('_lazy_embeddings_for_all_illus_lazypos_1833157.safetensors')).toBe('lazypos');
            expect(getShortEmbeddingName('_lazy_embeddings_for_all_illus_lazyneg_1833157.safetensors')).toBe('lazyneg');
            expect(getShortEmbeddingName('_lazy_embeddings_for_all_illus_lazynsfw_1833157.safetensors')).toBe('lazynsfw');
            expect(getShortEmbeddingName('_lazy_embeddings_for_all_illus_lazywet_2512494.safetensors')).toBe('lazywet');
            expect(getShortEmbeddingName('_lazy_embeddings_for_all_illus_lazyhand_1833157.safetensors')).toBe('lazyhand');
        });

        it('preserves multi-word model names without stripping base words', () => {
            expect(getShortEmbeddingName('_lazy_embeddings_for_all_illus_lazyup_pony_1473187.safetensors')).toBe('lazyup_pony');
            expect(getShortEmbeddingName('_lazy_embeddings_for_all_illus_lazydn_pony_1473204.safetensors')).toBe('lazydn_pony');
            expect(getShortEmbeddingName('_lazy_embeddings_for_all_illus_lazypos_v1_1470451.safetensors')).toBe('lazypos_v1');
            expect(getShortEmbeddingName('_lazy_embeddings_for_all_illus_lazyneg_v3_1860747.safetensors')).toBe('lazyneg_v3');
            expect(getShortEmbeddingName('_lazy_embeddings_for_all_illus_lazyhand_v10_1550840.safetensors')).toBe('lazyhand_v10');
        });

        it('shortens standalone models and strips version IDs and extensions', () => {
            expect(getShortEmbeddingName('badhandv4.safetensors')).toBe('badhandv4');
            expect(getShortEmbeddingName('easynegative.pt')).toBe('easynegative');
            expect(getShortEmbeddingName('muscle_slider_v1_2830869.safetensors')).toBe('muscle_slider_v1');
        });
    });

    describe('parseActiveEmbeddings', () => {
        it('extracts bare and weighted embeddings', () => {
            const prompt = 'masterpiece, embedding:lazypos, (embedding:lazyreal:1.2), 1girl, (embedding:style/v1.safetensors:0.8)';
            const parsed = parseActiveEmbeddings(prompt);

            expect(parsed).toHaveLength(3);
            expect(parsed[0]).toMatchObject({ name: 'lazypos', weight: 1.0, isWeighted: false });
            expect(parsed[1]).toMatchObject({ name: 'lazyreal', weight: 1.2, isWeighted: true });
            expect(parsed[2]).toMatchObject({ name: 'style/v1.safetensors', weight: 0.8, isWeighted: true });
        });
    });

    describe('hasEmbedding and getEmbeddingWeight', () => {
        it('checks if an embedding is active matching bare name or with extension', () => {
            const prompt = '1girl, (embedding:lazypos:1.1), best quality';
            expect(hasEmbedding(prompt, 'lazypos')).toBe(true);
            expect(hasEmbedding(prompt, 'lazypos.safetensors')).toBe(true);
            expect(hasEmbedding(prompt, 'lazyneg')).toBe(false);

            expect(getEmbeddingWeight(prompt, 'lazypos')).toBe(1.1);
            expect(getEmbeddingWeight(prompt, 'lazyneg')).toBe(null);
        });
    });

    describe('toggleEmbeddingInPrompt', () => {
        it('appends an embedding when absent', () => {
            const initial = '1girl, masterpiece';
            const toggled = toggleEmbeddingInPrompt(initial, 'lazypos');
            expect(toggled).toBe('1girl, masterpiece, embedding:lazypos');
        });

        it('removes an embedding when present', () => {
            const initial = '1girl, embedding:lazypos, masterpiece';
            const toggled = toggleEmbeddingInPrompt(initial, 'lazypos');
            expect(toggled).toBe('1girl, masterpiece');
        });

        it('handles removing weighted embeddings', () => {
            const initial = '1girl, (embedding:lazypos:1.2), masterpiece';
            const toggled = toggleEmbeddingInPrompt(initial, 'lazypos');
            expect(toggled).toBe('1girl, masterpiece');
        });

        it('strictly preserves line breaks when toggling', () => {
            const multiline = 'masterpiece, best quality\n1girl, solo, smile';
            const added = toggleEmbeddingInPrompt(multiline, 'lazypos');
            expect(added).toBe('masterpiece, best quality\n1girl, solo, smile, embedding:lazypos');

            const removed = toggleEmbeddingInPrompt(added, 'lazypos');
            expect(removed).toBe('masterpiece, best quality\n1girl, solo, smile');
        });
    });

    describe('removeEmbeddingFromPrompt', () => {
        it('removes target embedding cleanly while preserving line breaks', () => {
            const initial = 'masterpiece, best quality\n1girl, (embedding:lazyneg:0.9), bad hands';
            expect(removeEmbeddingFromPrompt(initial, 'lazyneg')).toBe('masterpiece, best quality\n1girl, bad hands');
        });
    });

    describe('setEmbeddingWeightInPrompt', () => {
        it('updates existing embedding weight', () => {
            const initial = '1girl, embedding:lazypos, masterpiece';
            const updated = setEmbeddingWeightInPrompt(initial, 'lazypos', 1.2);
            expect(updated).toBe('1girl, (embedding:lazypos:1.2), masterpiece');
        });

        it('reverts to bare syntax when weight is 1.0', () => {
            const initial = '1girl, (embedding:lazypos:1.2), masterpiece';
            const updated = setEmbeddingWeightInPrompt(initial, 'lazypos', 1.0);
            expect(updated).toBe('1girl, embedding:lazypos, masterpiece');
        });

        it('appends embedding with weight when absent while preserving line breaks', () => {
            const initial = 'masterpiece\n1girl';
            const updated = setEmbeddingWeightInPrompt(initial, 'lazypos', 1.1);
            expect(updated).toBe('masterpiece\n1girl, (embedding:lazypos:1.1)');
        });
    });
});
