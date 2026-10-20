/**
 * The dashboard's bulk-selection handlers.
 *
 * The one that matters here is "remove the selection from the current
 * collection". It used to fan a selected set out into one `removeFromCollection`
 * call per filename, which meant N parallel DELETEs of a one-element array
 * through a single `useMutation` — so `isPending`/`error` described whichever
 * request landed last, not the batch, and 50 selected images meant 50 requests.
 */
import { renderHook, act, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useDashboardSelection } from './useDashboardSelection';

const { toastMock, filesApiMock } = vi.hoisted(() => ({
    toastMock: { success: vi.fn(), error: vi.fn(), promise: vi.fn() },
    filesApiMock: {
        deleteMultiple: vi.fn().mockResolvedValue({}),
        batchDownload: vi.fn(),
    },
}));

vi.mock('react-hot-toast', () => ({ default: toastMock }));

vi.mock('../api', () => ({ filesApi: filesApiMock }));

const filesApi = filesApiMock;

const FOUR_IMAGES = new Set(['a.png', 'b.png', 'c.png', 'd.png']);

function mount({ removeFromCollection = vi.fn().mockResolvedValue(undefined) } = {}) {
    const confirm = vi.fn().mockResolvedValue(true);
    const hook = renderHook(() => useDashboardSelection({
        favorites: [],
        addFavorites: vi.fn(),
        queryClient: mockQueryClient(),
        filters: { sort: 'date_desc' },
        confirm,
        activeCollection: 'col-1',
        removeFromCollection,
        setShowSelectCollection: vi.fn(),
    }));
    act(() => { hook.result.current.setSelectedFiles(new Set(FOUR_IMAGES)); });
    return { ...hook, confirm, removeFromCollection };
}

/**
 * A query client with the parts the hook uses.
 *
 * `getQueryCache` is here because the gallery refresh reads the cache to
 * find the loaded listings - a mock without it makes the refresh throw, and
 * the throw lands in the handler's catch, so the selection is never
 * cleared and the test fails for a reason that has nothing to do with the
 * behaviour it is about.
 */
function mockQueryClient() {
    return {
        invalidateQueries: vi.fn(),
        getQueryCache: () => ({ findAll: () => [] }),
    };
}

describe('handleRemoveSelectionFromCollection', () => {
    beforeEach(() => vi.clearAllMocks());

    it('sends the whole selection in ONE request, not one per image', async () => {
        const { result, removeFromCollection } = mount();

        await act(async () => {
            await result.current.handleRemoveSelectionFromCollection();
        });

        // Four selected images. The loop made four calls of one element each.
        expect(removeFromCollection).toHaveBeenCalledTimes(1);
        expect(removeFromCollection).toHaveBeenCalledWith('col-1', ['a.png', 'b.png', 'c.png', 'd.png']);
    });

    it('passes an array, not a bare filename, so the endpoint gets an images list', async () => {
        const { result, removeFromCollection } = mount();

        await act(async () => {
            await result.current.handleRemoveSelectionFromCollection();
        });

        const [, images] = removeFromCollection.mock.calls[0];
        expect(Array.isArray(images)).toBe(true);
        expect(images).toHaveLength(4);
    });

    it('clears the selection and reports success once', async () => {
        const { result } = mount();

        await act(async () => {
            await result.current.handleRemoveSelectionFromCollection();
        });

        expect(toastMock.success).toHaveBeenCalledTimes(1);
        expect(toastMock.success).toHaveBeenCalledWith('Removed 4 images from collection');
        expect(result.current.selectedFiles.size).toBe(0);
    });

    it('keeps the selection and does not report success when the request fails', async () => {
        const removeFromCollection = vi.fn().mockRejectedValue(new Error('500'));
        const { result } = mount({ removeFromCollection });

        await act(async () => {
            await result.current.handleRemoveSelectionFromCollection();
        });

        expect(result.current.selectedFiles.size).toBe(4);
        expect(toastMock.success).not.toHaveBeenCalled();
        // The failure message is `useRemoveImagesFromCollection`'s job now — one
        // error path for every caller. It used to also toast here, which showed
        // the same error twice.
        expect(toastMock.error).not.toHaveBeenCalled();
    });

    it('does nothing without an active collection', async () => {
        const removeFromCollection = vi.fn();
        const { result } = renderHook(() => useDashboardSelection({
            favorites: [],
            addFavorites: vi.fn(),
            queryClient: mockQueryClient(),
            filters: {},
            confirm: vi.fn(),
            activeCollection: null,
            removeFromCollection,
            setShowSelectCollection: vi.fn(),
        }));
        act(() => { result.current.setSelectedFiles(new Set(FOUR_IMAGES)); });

        await act(async () => {
            await result.current.handleRemoveSelectionFromCollection();
        });

        expect(removeFromCollection).not.toHaveBeenCalled();
        expect(toastMock.error).toHaveBeenCalledWith('No collection selected to remove from');
    });

    it('does nothing with an empty selection', async () => {
        const removeFromCollection = vi.fn();
        const { result } = renderHook(() => useDashboardSelection({
            favorites: [],
            addFavorites: vi.fn(),
            queryClient: mockQueryClient(),
            filters: {},
            confirm: vi.fn(),
            activeCollection: 'col-1',
            removeFromCollection,
            setShowSelectCollection: vi.fn(),
        }));

        await act(async () => {
            await result.current.handleRemoveSelectionFromCollection();
        });

        expect(removeFromCollection).not.toHaveBeenCalled();
    });
});

describe('the sibling handlers stay on one request too', () => {
    beforeEach(() => vi.clearAllMocks());

    it('deletes the selection in one batch call', async () => {
        const { result } = mount();

        await act(async () => {
            await result.current.handleBatchDelete();
        });

        expect(filesApi.deleteMultiple).toHaveBeenCalledTimes(1);
        expect(filesApi.deleteMultiple).toHaveBeenCalledWith(['a.png', 'b.png', 'c.png', 'd.png']);
        await waitFor(() => expect(result.current.selectedFiles.size).toBe(0));
    });

    it('sends the whole un-starred selection to addFavorites once', () => {
        const addFavorites = vi.fn();
        const { result } = renderHook(() => useDashboardSelection({
            favorites: ['a.png'],
            addFavorites,
            queryClient: mockQueryClient(),
            filters: {},
            confirm: vi.fn(),
            activeCollection: 'col-1',
            removeFromCollection: vi.fn(),
            setShowSelectCollection: vi.fn(),
        }));
        act(() => { result.current.setSelectedFiles(new Set(FOUR_IMAGES)); });

        act(() => { result.current.handleBatchFavorite(); });

        expect(addFavorites).toHaveBeenCalledTimes(1);
        expect(addFavorites).toHaveBeenCalledWith(['b.png', 'c.png', 'd.png']);
    });
});