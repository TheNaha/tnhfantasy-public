/**
 * The collection mutations' failure path.
 *
 * `useRemoveImagesFromCollection` had `onSuccess` and no `onError`, so a failed
 * removal had no default reporting at all: the only way it was ever seen was a
 * caller remembering to wrap `mutateAsync` in a try/catch of its own. Nothing
 * about the hook itself made a fire-and-forget `.mutate()` call safe, so a
 * rejection arrived as nothing at all — the collection list stayed stale, the
 * selected images stayed selected, and no error appeared anywhere.
 *
 * It also carries the batch contract: the whole selection goes out as ONE
 * `images` array, because `useDashboardSelection` used to fan the selection out
 * into one request per image through this single mutation.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { createElement } from 'react';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const { toastMock, removeImagesFromCollectionMock } = vi.hoisted(() => ({
    toastMock: { success: vi.fn(), error: vi.fn() },
    removeImagesFromCollectionMock: vi.fn(),
}));

vi.mock('react-hot-toast', () => ({ default: toastMock }));

vi.mock('../api/collectionsApi', () => ({
    listCollections: vi.fn().mockResolvedValue({ collections: [] }),
    getCollection: vi.fn().mockResolvedValue({ images: [] }),
    createCollection: vi.fn(),
    deleteCollection: vi.fn(),
    updateCollection: vi.fn(),
    addImagesToCollection: vi.fn(),
    removeImagesFromCollection: removeImagesFromCollectionMock,
    importCollections: vi.fn(),
    moveImagesBetweenCollections: vi.fn(),
}));

function makeWrapper(queryClient) {
    return function Wrapper({ children }) {
        return createElement(QueryClientProvider, { client: queryClient }, children);
    };
}

function makeClient() {
    return new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
}

describe('useRemoveImagesFromCollection', () => {
    let queryClient;
    let useRemoveImagesFromCollection;
    let consoleError;

    beforeEach(async () => {
        vi.clearAllMocks();
        // The hook logs the raw error alongside the toast; keep the suite output
        // readable and pin that the log is there at all.
        consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
        removeImagesFromCollectionMock.mockReset();
        queryClient = makeClient();
        ({ useRemoveImagesFromCollection } = await import('./useCollections'));
    });

    afterEach(() => {
        consoleError.mockRestore();
    });

    it('sends the whole images array in one DELETE and refreshes both queries', async () => {
        removeImagesFromCollectionMock.mockResolvedValue({ removed: 4 });
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useRemoveImagesFromCollection(), {
            wrapper: makeWrapper(queryClient),
        });

        const images = ['a.png', 'b.png', 'c.png', 'd.png'];
        await act(async () => {
            await result.current.mutateAsync({ collectionId: 'col-1', images });
        });

        expect(removeImagesFromCollectionMock).toHaveBeenCalledTimes(1);
        expect(removeImagesFromCollectionMock).toHaveBeenCalledWith('col-1', images);
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['collections'] });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['collections', 'col-1', 'images'] });
        expect(toastMock.error).not.toHaveBeenCalled();
    });

    it('reports the failure itself when the request rejects', async () => {
        removeImagesFromCollectionMock.mockRejectedValue(new Error('500 from the server'));
        const { result } = renderHook(() => useRemoveImagesFromCollection(), {
            wrapper: makeWrapper(queryClient),
        });

        await act(async () => {
            await expect(
                result.current.mutateAsync({ collectionId: 'col-1', images: ['a.png'] }),
            ).rejects.toThrow('500 from the server');
        });

        expect(toastMock.error).toHaveBeenCalledTimes(1);
        expect(toastMock.error).toHaveBeenCalledWith('Failed to remove images from collection');
        expect(consoleError).toHaveBeenCalled();
    });

    it('reports the failure for a fire-and-forget mutate() too, with no caller catch', async () => {
        // The shape that produced no output at all before: `.mutate()` rather
        // than `.mutateAsync()`, so there was no rejected promise for a caller
        // to notice and nothing attached the error to the mutation state.
        removeImagesFromCollectionMock.mockRejectedValue(new Error('offline'));
        const { result } = renderHook(() => useRemoveImagesFromCollection(), {
            wrapper: makeWrapper(queryClient),
        });

        await act(async () => {
            result.current.mutate({ collectionId: 'col-1', images: ['a.png'] });
        });

        expect(toastMock.error).toHaveBeenCalledWith('Failed to remove images from collection');
        await waitFor(() => expect(result.current.isError).toBe(true));
    });

    it('does not invalidate on failure — the collection still holds the images', async () => {
        removeImagesFromCollectionMock.mockRejectedValue(new Error('500'));
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useRemoveImagesFromCollection(), {
            wrapper: makeWrapper(queryClient),
        });

        await act(async () => {
            await result.current.mutateAsync({ collectionId: 'col-1', images: ['a.png'] }).catch(() => {});
        });

        expect(invalidate).not.toHaveBeenCalled();
    });
});