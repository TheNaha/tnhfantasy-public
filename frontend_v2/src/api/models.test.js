import { beforeEach, describe, expect, it, vi } from 'vitest';

// The tag endpoints are the write path for a table that used to be reachable
// only by a CivitAI resync. Two things about them are easy to get wrong and
// both are load-bearing, so they are pinned here rather than in a component
// test: the maintenance path prefix, and the fact that a user tag is arbitrary
// text and has to be escaped into the URL.

const getMock = vi.hoisted(() => vi.fn());
const postMock = vi.hoisted(() => vi.fn());
const deleteMock = vi.hoisted(() => vi.fn());

vi.mock('./client', () => ({
    default: {
        get: getMock,
        post: postMock,
        delete: deleteMock,
    },
    API_V2_BASE: '/api/v2',
}));

import modelsApi, { modelsApi as namedModelsApi } from './models';

describe('modelsApi', () => {
    beforeEach(() => {
        getMock.mockReset();
        postMock.mockReset();
        deleteMock.mockReset();
    });

    it('exposes the same object as the default and named export', () => {
        expect(namedModelsApi).toBe(modelsApi);
    });

    it('keeps the pre-existing V2 delete', () => {
        modelsApi.deleteV2('abc-123');
        expect(deleteMock).toHaveBeenCalledWith('/api/v2/models/abc-123');
    });

    describe('tags', () => {
        it('lists tags from the maintenance endpoint', async () => {
            const payload = { tags: [{ tag: 'anime', source: 'civitai' }] };
            getMock.mockResolvedValue(payload);

            await expect(modelsApi.listTags('abc-123')).resolves.toEqual(payload);
            expect(getMock).toHaveBeenCalledWith('/api/v2/models/maintenance/abc-123/tags');
        });

        it('adds a tag with {tag} as the request body', async () => {
            postMock.mockResolvedValue({ tag: 'kneeling', source: 'user', created: true });

            await modelsApi.addTag('abc-123', 'kneeling');

            expect(postMock).toHaveBeenCalledWith(
                '/api/v2/models/maintenance/abc-123/tags',
                { tag: 'kneeling' },
            );
        });

        it('escapes a tag into the path so spaces and slashes survive', async () => {
            modelsApi.removeTag('abc-123', 'pose: hands up / kneeling');

            expect(deleteMock).toHaveBeenCalledWith(
                '/api/v2/models/maintenance/abc-123/tags/' +
                    encodeURIComponent('pose: hands up / kneeling'),
            );
        });

        it('propagates a refused delete rather than swallowing it', async () => {
            // The backend answers 404 for a CivitAI-owned tag. The client must
            // let that through as a rejection carrying the status, because the
            // caller's only way to say "that one is not yours to delete" is the
            // status code.
            const refusal = Object.assign(new Error('Not found'), { status: 404 });
            deleteMock.mockRejectedValue(refusal);

            await expect(modelsApi.removeTag('abc-123', 'anime')).rejects.toMatchObject({
                status: 404,
            });
        });
    });
});
