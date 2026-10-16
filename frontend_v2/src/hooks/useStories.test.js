import React from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
}));

vi.mock('../api', () => ({
    api: apiMock,
}));

import {
    useStories,
    useStory,
    useStoryChapters,
    useStoryImages,
    useCreateStory,
    useCreateChapter,
    useContinueChapter,
    useBranchChapter,
    useAddStoryBeat,
    useIllustrateChapter,
    useDeleteStory,
    useUpdateStory,
    useDeleteChapter,
    useUpdateChapter,
    useParseStory,
    useExportStoryFormatted,
    useNarrateChapter,
    usePublishStory,
    useStartChatFromStory,
} from './useStories';

function createWrapper() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return {
        wrapper: ({ children }) =>
            React.createElement(QueryClientProvider, { client: queryClient }, children),
        queryClient,
    };
}

describe('useStories queries', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('fetches the story list', async () => {
        apiMock.get.mockResolvedValue([{ id: 's1', title: 'Tale' }]);
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useStories(), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual([{ id: 's1', title: 'Tale' }]));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/stories', { signal: expect.any(AbortSignal) });
    });

    it('useStory/useStoryChapters/useStoryImages gate on storyId and use subkeys', async () => {
        apiMock.get.mockResolvedValue([]);
        const { wrapper, queryClient } = createWrapper();

        const story = renderHook(() => useStory('s1'), { wrapper });
        await waitFor(() => expect(story.result.current.data).toEqual([]));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/stories/s1', { signal: expect.any(AbortSignal) });
        expect(queryClient.getQueryState(['world_vault', 'stories', 's1'])).toBeDefined();

        const chapters = renderHook(() => useStoryChapters('s1'), { wrapper });
        await waitFor(() => expect(chapters.result.current.data).toEqual([]));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/stories/s1/chapters', { signal: expect.any(AbortSignal) });

        const images = renderHook(() => useStoryImages('s1'), { wrapper });
        await waitFor(() => expect(images.result.current.data).toEqual([]));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/stories/s1/images', { signal: expect.any(AbortSignal) });
    });

    it('useStory does not fetch without an id', async () => {
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useStory(null), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(false));
        expect(apiMock.get).not.toHaveBeenCalled();
    });
});

describe('useStories mutations', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('useCreateStory posts and invalidates the list', async () => {
        apiMock.post.mockResolvedValue({ id: 's2' });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useCreateStory(), { wrapper });
        await act(async () => result.current.mutateAsync({ title: 'New' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/stories', { title: 'New' });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'stories'] });
    });

    it('useUpdateStory PUTs and invalidates list + detail', async () => {
        apiMock.put.mockResolvedValue({ id: 's1' });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useUpdateStory(), { wrapper });
        await act(async () => result.current.mutateAsync({ id: 's1', title: 'Renamed' }));
        expect(apiMock.put).toHaveBeenCalledWith('/api/v2/stories/s1', { title: 'Renamed' });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'stories', 's1'] });
    });

    it('useDeleteStory DELETEs and invalidates the list', async () => {
        apiMock.delete.mockResolvedValue({ ok: true });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useDeleteStory(), { wrapper });
        await act(async () => result.current.mutateAsync('s1'));
        expect(apiMock.delete).toHaveBeenCalledWith('/api/v2/stories/s1');
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'stories'] });
    });

    it('useCreateChapter posts and invalidates the chapters key', async () => {
        apiMock.post.mockResolvedValue({ id: 'ch1' });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useCreateChapter(), { wrapper });
        await act(async () => result.current.mutateAsync({ storyId: 's1', data: { title: 'C1' } }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/stories/s1/chapters', { title: 'C1' });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'stories', 's1', 'chapters'] });
    });

    it('useContinueChapter optimistically appends the prompt and clears streaming on success', async () => {
        let resolvePost;
        apiMock.post.mockImplementation(() => new Promise((r) => { resolvePost = r; }));
        const { wrapper, queryClient } = createWrapper();
        const chaptersKey = ['world_vault', 'stories', 's1', 'chapters'];
        queryClient.setQueryData(chaptersKey, [{ id: 'ch1', content: 'base' }]);
        const { result } = renderHook(() => useContinueChapter(), { wrapper });

        let pending;
        act(() => {
            pending = result.current.mutate({ storyId: 's1', chapterId: 'ch1', prompt: 'and then...' });
        });
        await waitFor(() => {
            expect(queryClient.getQueryData(chaptersKey)[0].content).toBe('base\n\nand then...');
            expect(queryClient.getQueryData(chaptersKey)[0]._isStreaming).toBe(true);
        });

        await act(async () => { resolvePost({ id: 'ch1', content: 'full' }); await pending; });
        expect(queryClient.getQueryData(chaptersKey)[0]._isStreaming).toBe(false);
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/stories/s1/chapters/ch1/continue', { prompt: 'and then...' });
    });

    it('useContinueChapter rolls back the optimistic append on error', async () => {
        apiMock.post.mockRejectedValue(new Error('nope'));
        const { wrapper, queryClient } = createWrapper();
        const chaptersKey = ['world_vault', 'stories', 's1', 'chapters'];
        queryClient.setQueryData(chaptersKey, [{ id: 'ch1', content: 'base' }]);
        const { result } = renderHook(() => useContinueChapter(), { wrapper });

        await act(async () => {
            try {
                await result.current.mutateAsync({ storyId: 's1', chapterId: 'ch1', prompt: 'boom' });
            } catch {
                /* expected */
            }
        });
        expect(queryClient.getQueryData(chaptersKey)[0].content).toBe('base');
        expect(queryClient.getQueryData(chaptersKey)[0]._isStreaming).toBeUndefined();
    });

    it('useAddStoryBeat appends an optimistic beat and invalidates on success', async () => {
        let resolvePost;
        apiMock.post.mockImplementation(() => new Promise((r) => { resolvePost = r; }));
        const { wrapper, queryClient } = createWrapper();
        const chaptersKey = ['world_vault', 'stories', 's1', 'chapters'];
        queryClient.setQueryData(chaptersKey, [{ id: 'ch1', beats: [] }]);
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useAddStoryBeat(), { wrapper });

        let pending;
        act(() => {
            pending = result.current.mutate({ storyId: 's1', chapterId: 'ch1', content: 'beat', role: 'user' });
        });
        await waitFor(() => expect(queryClient.getQueryData(chaptersKey)[0].beats).toHaveLength(1));
        const optimistic = queryClient.getQueryData(chaptersKey)[0].beats[0];
        expect(optimistic.content).toBe('beat');
        expect(optimistic.role).toBe('user');
        expect(optimistic.id.startsWith('temp-')).toBe(true);

        await act(async () => { resolvePost({ id: 'b1' }); await pending; });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: chaptersKey });
    });

    it('useBranchChapter posts with empty prompt fallback', async () => {
        apiMock.post.mockResolvedValue({ id: 'b1' });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useBranchChapter(), { wrapper });
        await act(async () => result.current.mutateAsync({ storyId: 's1', chapterId: 'ch1', fromBeatId: 'b0', prompt: undefined }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/stories/s1/chapters/ch1/branch', { from_beat_id: 'b0', prompt: '' });
    });

    it('useIllustrateChapter posts with empty image_prompt fallback', async () => {
        apiMock.post.mockResolvedValue({ ok: true });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useIllustrateChapter(), { wrapper });
        await act(async () => result.current.mutateAsync({ storyId: 's1', chapterId: 'ch1', image_prompt: undefined }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/stories/s1/chapters/ch1/illustrate', { image_prompt: '' });
    });

    it('useDeleteChapter/useUpdateChapter hit the chapter endpoints', async () => {
        apiMock.delete.mockResolvedValue({ ok: true });
        apiMock.put.mockResolvedValue({ id: 'ch1' });
        const { wrapper } = createWrapper();

        const del = renderHook(() => useDeleteChapter(), { wrapper });
        await act(async () => del.result.current.mutateAsync({ storyId: 's1', chapterId: 'ch1' }));
        expect(apiMock.delete).toHaveBeenCalledWith('/api/v2/stories/s1/chapters/ch1');

        const upd = renderHook(() => useUpdateChapter(), { wrapper });
        await act(async () => upd.result.current.mutateAsync({ storyId: 's1', chapterId: 'ch1', title: 'T' }));
        expect(apiMock.put).toHaveBeenCalledWith('/api/v2/stories/s1/chapters/ch1', { title: 'T' });
    });

    it('useParseStory invalidates characters, lorebooks and stories', async () => {
        apiMock.post.mockResolvedValue({ parsed: true });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useParseStory(), { wrapper });
        await act(async () => result.current.mutateAsync({ storyId: 's1', text: 'Once upon...' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/stories/parse', { story_id: 's1', text: 'Once upon...' });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'characters'] });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'lorebooks'] });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'stories'] });
    });

    it('useNarrateChapter and usePublishStory invalidate the story detail', async () => {
        apiMock.post.mockResolvedValue({ ok: true });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

        const narrate = renderHook(() => useNarrateChapter(), { wrapper });
        await act(async () => narrate.result.current.mutateAsync({ storyId: 's1', chapterId: 'ch1' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/stories/s1/chapters/ch1/narrate');
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'stories', 's1'], exact: true });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'stories', 's1', 'chapters'] });
        // The list carries the publish badge, so it has to be refetched too.
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'stories'] });

        const publish = renderHook(() => usePublishStory(), { wrapper });
        await act(async () => publish.result.current.mutateAsync({ storyId: 's1' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/stories/s1/publish');
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'stories', 's1'], exact: true });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'stories'] });
    });
});

describe('useExportStoryFormatted', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('triggers a JSON blob download for the default format', async () => {
        const createObjectURL = vi.fn(() => 'blob:url');
        const revokeObjectURL = vi.fn();
        vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });
        class MockBlob {
            constructor(parts, opts) {
                this.parts = parts;
                this.opts = opts;
            }
        }
        vi.stubGlobal('Blob', MockBlob);

        const click = vi.fn();
        const origClick = HTMLAnchorElement.prototype.click;
        HTMLAnchorElement.prototype.click = click;

        try {
            apiMock.get.mockResolvedValue({ id: 's1', title: 'T', content: 'x' });
            const { wrapper } = createWrapper();
            const { result } = renderHook(() => useExportStoryFormatted(), { wrapper });
            await act(async () => result.current.mutateAsync({ storyId: 's1', format: 'json' }));

            expect(apiMock.get).toHaveBeenCalledWith('/api/v2/stories/s1/export?format=json');
            expect(click).toHaveBeenCalledTimes(1);
        } finally {
            HTMLAnchorElement.prototype.click = origClick;
            vi.unstubAllGlobals();
        }
    });

    it('useStartChatFromStory posts to start-chat endpoint and invalidates chats', async () => {
        apiMock.post.mockResolvedValue({ chat_id: 'c100', title: 'Tale — Chapter 1' });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useStartChatFromStory(), { wrapper });

        let res;
        await act(async () => {
            res = await result.current.mutateAsync({ storyId: 's1', chapterId: 'ch1' });
        });

        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/stories/s1/start-chat', { chapter_id: 'ch1' });
        expect(res).toEqual({ chat_id: 'c100', title: 'Tale — Chapter 1' });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'chats'] });
    });
});