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

});

