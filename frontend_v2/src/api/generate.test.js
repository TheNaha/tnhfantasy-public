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
                metadata: expect.objectContaining(metadata),
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
                metadata: expect.objectContaining({ steps: 20 }),
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
                metadata: expect.objectContaining({ prompt: 'a cat' }),
                preferred_provider_id: 'modal-primary',
            },
            { idempotencyKey: 'generated-idempotency-key' }
        );
    });

    it('sends the kind the caller states', async () => {
        postMock.mockResolvedValue({ ok: true });

        await generateApi.workflow({ prompt: 'a cat', mode: 't2i' }, {}, { kind: 'guided' });

        const body = postMock.mock.calls[0][1];
        expect(body.kind).toBe('guided');
        expect(body.options).toEqual({ prompt: 'a cat', mode: 't2i' });
        expect(body.workflow).toBeUndefined();
    });

    it('never infers the kind from the shape of the argument', async () => {
        // The kind used to be INFERRED: an object with a `mode` or a `prompt`
        // key was read as options, and anything else as a graph. So a ComfyUI
        // graph in API format - whose top-level key IS `prompt` - was
        // compiled as generator options and rejected by the option schema.
        //
        // A request that states no kind takes the strict path instead.
        postMock.mockResolvedValue({ ok: true });

        await generateApi.workflow({ prompt: 'a cat', mode: 't2i' });

        const body = postMock.mock.calls[0][1];
        expect(body.kind).toBe('graph');
        expect(body.workflow).toEqual({ prompt: 'a cat', mode: 't2i' });
        expect(body.options).toBeUndefined();
    });

    it('injects client_submitted_at and client_perf_start for end-to-end telemetry', async () => {
        postMock.mockResolvedValue({ ok: true });
        const before = Date.now();
        await generateApi.submit({ kind: 'guided', options: {} });
        const after = Date.now();

        const callBody = postMock.mock.calls[0][1];
        expect(callBody.metadata).toBeDefined();
        expect(callBody.metadata.client_submitted_at).toBeGreaterThanOrEqual(before);
        expect(callBody.metadata.client_submitted_at).toBeLessThanOrEqual(after);
        expect(typeof callBody.metadata.client_perf_start).toBe('number');
    });
});

