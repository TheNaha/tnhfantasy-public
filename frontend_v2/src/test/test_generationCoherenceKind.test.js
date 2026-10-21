import { beforeEach, describe, expect, it, vi } from 'vitest';

const postMock = vi.hoisted(() => vi.fn());

vi.mock('../api/client', () => ({
    default: { post: postMock },
    createIdempotencyKey: () => 'test-key',
}));

import { generateApi, GUIDED, GRAPH, resolveGenerationKind } from '../api/generate';
import jobsApi from '../api/jobs';

/**
 * The request "kind" is stated, never inferred.
 *
 * The kind used to be read off the shape of the argument: an object with a
 * `mode` or a `prompt` key was taken for generator options, and anything
 * else for a ComfyUI graph. The backend honours the kind strictly
 * (`backend_v2/api/routes/generation.py`): `kind == "guided"` compiles
 * `request.options`, and anything else compiles `request.workflow`.
 *
 * So the inference was wrong in a way that broke real requests:
 *
 *  - A ComfyUI graph in API format has a top-level `prompt` key. Pasted into
 *    the Advanced generator's Raw JSON tab, it was read as options, compiled
 *    as generator options, and rejected by the option schema.
 *  - The same misroute sent the graph to `jobsApi.validate` as `options`,
 *    where the backend answered 422 for a request that was a perfectly good
 *    graph.
 *
 * A request that states no kind takes the strict path - the backend refuses
 * a graph it cannot compile rather than silently compiling a request as
 * options and sending the wrong thing to the provider.
 */

/** A ComfyUI graph in API format. Its top-level key IS `prompt`. */
const API_FORMAT_GRAPH = {
    prompt: { '1': { class_type: 'KSampler', inputs: {} } },
    extra_data: { extra_pnginfo: {} },
};

describe('a generation request states its kind', () => {
    beforeEach(() => {
        postMock.mockReset();
        postMock.mockResolvedValue({ ok: true });
    });

    it('sends options for a guided request', async () => {
        // The payload has no `prompt` and no `mode` key, so the old
        // inference read it as a graph.
        await generateApi.workflow({ steps: 20, sampler: 'euler' }, { prompt: 'a cat' }, { kind: GUIDED });

        const [url, body] = postMock.mock.calls[0];
        expect(url).toBe('/api/generate');
        expect(body.kind).toBe('guided');
        expect(body.options).toEqual({ steps: 20, sampler: 'euler' });
        expect(body.workflow).toBeUndefined();
    });

    it('sends the graph for a graph request', async () => {
        const graph = { nodes: { '1': { type: 'ksampler' } }, edges: [] };

        await generateApi.workflow(graph, {}, { kind: GRAPH });

        const [, body] = postMock.mock.calls[0];
        expect(body.kind).toBe('graph');
        expect(body.workflow).toBe(graph);
        expect(body.options).toBeUndefined();
    });

    it('never infers the kind from the shape of the payload', async () => {
        // The regression: a graph in API format has a top-level `prompt` key,
        // and the old inference read that as "these are options".
        await generateApi.workflow(API_FORMAT_GRAPH, {}, { kind: GRAPH });

        const [, body] = postMock.mock.calls[0];
        expect(body.kind).toBe('graph');
        expect(body.workflow).toEqual(API_FORMAT_GRAPH);
        expect(body.options).toBeUndefined();
    });

    it('takes the strict path when no kind is stated', async () => {
        await generateApi.workflow({ prompt: 'a cat', mode: 't2i' });

        const [, body] = postMock.mock.calls[0];
        expect(body.kind).toBe('graph');
        expect(body.workflow).toEqual({ prompt: 'a cat', mode: 't2i' });
        expect(body.options).toBeUndefined();
    });

    it('sends the kind the caller states', async () => {
        // The payload has no `prompt` and no `mode` key, so the old
        // inference read it as a graph whatever the caller said.
        await generateApi.workflow({ steps: 20, sampler: 'euler' }, { prompt: 'a cat' }, { kind: GUIDED });

        const [, body] = postMock.mock.calls[0];
        expect(body.kind).toBe('guided');
        expect(body.options).toEqual({ steps: 20, sampler: 'euler' });
        expect(body.workflow).toBeUndefined();
    });

    it('honours the kind the payload declares', async () => {
        // The shared builder puts the kind on the options it produces, so a
        // caller that only has the payload still states which shape it is.
        // Here the declared kind contradicts the old inference.
        await generateApi.workflow({ kind: GRAPH, prompt: 'a cat' });

        const [, body] = postMock.mock.calls[0];
        expect(body.kind).toBe('graph');
        expect(body.workflow).toEqual({ prompt: 'a cat' });
        expect(body.options).toBeUndefined();
    });

    it('does not send the kind marker as part of the options', async () => {
        // The marker is a frontend-side contract. The backend's
        // `GeneratorOptions` ignores unknown keys, but the request body
        // should not carry a field the backend does not read.
        await generateApi.workflow({ kind: GUIDED, prompt: 'a cat' });

        const [, body] = postMock.mock.calls[0];
        expect(body.options).not.toHaveProperty('kind');
    });

    it('resolves a kind from the explicit argument first', () => {
        expect(resolveGenerationKind({ kind: GUIDED }, GRAPH)).toBe(GRAPH);
        expect(resolveGenerationKind({ kind: GRAPH }, GUIDED)).toBe(GUIDED);
        expect(resolveGenerationKind({ kind: GUIDED }, null)).toBe(GUIDED);
        expect(resolveGenerationKind({}, null)).toBe(GRAPH);
        expect(resolveGenerationKind(null, null)).toBe(GRAPH);
    });
});

describe('the preflight validates the shape the request has', () => {
    beforeEach(() => {
        postMock.mockReset();
        postMock.mockResolvedValue({ valid: true });
    });

    it('sends a graph as a workflow even when its top-level key is prompt', async () => {
        // The same misroute as above: the graph was sent as `options`, and
        // the backend tried to compile it as generator options and answered
        // 422 for a request that was a perfectly good graph.
        await jobsApi.validate(API_FORMAT_GRAPH);

        const [url, body] = postMock.mock.calls[0];
        expect(url).toBe('/api/jobs/validate');
        expect(body.workflow).toEqual(API_FORMAT_GRAPH);
        expect(body.options).toBeUndefined();
    });

    it('sends options as options when the kind is guided', async () => {
        await jobsApi.validate({ kind: GUIDED, steps: 20, sampler: 'euler' }, 'modal-primary');

        const [, body] = postMock.mock.calls[0];
        expect(body.options).toEqual({ steps: 20, sampler: 'euler' });
        expect(body.workflow).toBeUndefined();
        expect(body.preferred_provider_id).toBe('modal-primary');
    });

    it('takes the strict path when no kind is stated', async () => {
        await jobsApi.validate({ prompt: 'a cat', mode: 't2i' });

        const [, body] = postMock.mock.calls[0];
        expect(body.workflow).toEqual({ prompt: 'a cat', mode: 't2i' });
        expect(body.options).toBeUndefined();
    });
});
