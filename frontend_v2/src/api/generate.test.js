import { beforeEach, describe, expect, it, vi } from 'vitest';

const postMock = vi.hoisted(() => vi.fn());
const createIdempotencyKeyMock = vi.hoisted(() => vi.fn(() => 'generated-idempotency-key'));

vi.mock('./client', () => ({
    default: {
        post: postMock,
    },
    createIdempotencyKey: createIdempotencyKeyMock,
}));

import generateApi from './generate';

describe('generateApi', () => {
    beforeEach(() => {
        postMock.mockReset();
        createIdempotencyKeyMock.mockClear();
        if (typeof window !== 'undefined') {
            window.localStorage.clear();
        }
    });

    it('submits workflow requests to /api/generate with metadata payload', async () => {
        postMock.mockResolvedValue({ ok: true });

        const workflow = { nodes: {} };
        const metadata = { prompt: 'test prompt' };

        await generateApi.workflow(workflow, metadata);

        expect(postMock).toHaveBeenCalledWith(
            '/api/generate',
            {
                workflow,
                metadata,
            },
            {
                idempotencyKey: 'generated-idempotency-key',
            },
        );
        expect(createIdempotencyKeyMock).toHaveBeenCalledWith('generate-workflow');
    });

    it('accepts explicit metadata field and custom idempotency key override', async () => {
        postMock.mockResolvedValue({ ok: true });

        const workflow = { nodes: { a: {} } };
        const params = { metadata: { steps: 20 } };

        await generateApi.workflow(workflow, params, { idempotencyKey: 'custom-key' });

        expect(postMock).toHaveBeenCalledWith(
            '/api/generate',
            {
                workflow,
                metadata: { steps: 20 },
            },
            {
                idempotencyKey: 'custom-key',
            },
        );
        expect(createIdempotencyKeyMock).not.toHaveBeenCalled();
    });

    it('reads and writes legacy local presets without calling unsupported endpoints', async () => {
        const existing = [{ id: 1, name: 'preset-a' }];
        window.localStorage.setItem('comfy-generator-presets', JSON.stringify(existing));

        const loaded = await generateApi.getPresets();
        expect(loaded).toEqual({ presets: existing });

        const saved = await generateApi.savePreset({ name: 'preset-b' });
        expect(saved.name).toBe('preset-b');

        const afterSave = JSON.parse(window.localStorage.getItem('comfy-generator-presets'));
        expect(afterSave).toHaveLength(2);
        expect(afterSave[1].name).toBe('preset-b');
        expect(postMock).not.toHaveBeenCalled();
    });
});
