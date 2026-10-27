import { describe, it, expect } from 'vitest';
import {
    isNegativeEmbedding,
    cleanPrompt,
    parseActiveEmbeddings,
    hasEmbedding,
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

    describe('hasEmbedding', () => {
        it('checks if an embedding is active matching bare name or with extension', () => {
            const prompt = '1girl, (embedding:lazypos:1.1), best quality';
            expect(hasEmbedding(prompt, 'lazypos')).toBe(true);
            expect(hasEmbedding(prompt, 'lazypos.safetensors')).toBe(true);
            expect(hasEmbedding(prompt, 'lazyneg')).toBe(false);
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
    });

    describe('removeEmbeddingFromPrompt', () => {
        it('removes target embedding cleanly', () => {
            const initial = '1girl, (embedding:lazyneg:0.9), bad hands';
            expect(removeEmbeddingFromPrompt(initial, 'lazyneg')).toBe('1girl, bad hands');
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

        it('appends embedding with weight when absent', () => {
            const initial = '1girl';
            const updated = setEmbeddingWeightInPrompt(initial, 'lazypos', 1.1);
            expect(updated).toBe('1girl, (embedding:lazypos:1.1)');
        });
    });
});
