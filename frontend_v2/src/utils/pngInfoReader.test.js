import { describe, it, expect, vi } from 'vitest';
import { extractPngInfo } from './pngInfoReader';

describe('pngInfoReader', () => {
    it('throws error when no file is passed', async () => {
        await expect(extractPngInfo(null)).rejects.toThrow('No file provided');
    });

    it('extracts metadata when server responds successfully', async () => {
        global.fetch = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({
                prompt: '1girl, solo, dark blue hair',
                negative_prompt: 'worst quality, blurry',
                tags: ['1girl', 'solo', 'dark blue hair'],
                source: 'embedded_metadata',
                metadata: { format: 'comfyui' },
            }),
        });

        const fakeFile = new File(['dummy bytes'], 'image.png', { type: 'image/png' });
        const result = await extractPngInfo(fakeFile);

        expect(result.prompt).toBe('1girl, solo, dark blue hair');
        expect(result.negativePrompt).toBe('worst quality, blurry');
        expect(result.tags).toEqual(['1girl', 'solo', 'dark blue hair']);
        expect(result.source).toBe('embedded_metadata');
    });
});
