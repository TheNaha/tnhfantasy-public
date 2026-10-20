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
                kind: 'graph',
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
                kind: 'graph',
                workflow,
                metadata: { steps: 20 },
            },
            {
                idempotencyKey: 'custom-key',
            },
        );
        expect(createIdempotencyKeyMock).not.toHaveBeenCalled();
    });


    it('sends the kind explicitly, and pins the provider when asked', async () => {
        postMock.mockResolvedValue({ ok: true });

        await generateApi.submit(
            { kind: 'guided', options: { prompt: 'a cat', mode: 't2i' } },
            { prompt: 'a cat' },
            { preferredProviderId: 'modal-primary' }
        );

        expect(postMock).toHaveBeenCalledWith(
            '/api/generate',
            {
                kind: 'guided',
                options: { prompt: 'a cat', mode: 't2i' },
                metadata: { prompt: 'a cat' },
                preferred_provider_id: 'modal-primary',
            },
            { idempotencyKey: 'generated-idempotency-key' }
        );
    });

    it('reads an options-shaped argument as guided, not as a graph', async () => {
        postMock.mockResolvedValue({ ok: true });

        await generateApi.workflow({ prompt: 'a cat', mode: 't2i' });

        const body = postMock.mock.calls[0][1];
        expect(body.kind).toBe('guided');
        expect(body.options).toEqual({ prompt: 'a cat', mode: 't2i' });
        expect(body.workflow).toBeUndefined();
    });

});

