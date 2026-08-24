import React from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
}));

vi.mock('../api', () => ({
    api: apiMock,
}));

import {
    useCharacters,
    useCreateCharacter,
    useUpdateCharacter,
    usePatchCharacter,
    getAvatarUrl,
    useUploadAvatar,
    useDeleteCharacter,
    useImportCharacterCard,
    useCharacterCollection,
} from './useCharacters';

function createWrapper() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return {
        wrapper: ({ children }) =>
            React.createElement(QueryClientProvider, { client: queryClient }, children),
        queryClient,
    };
}

describe('useCharacters', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('fetches the character list', async () => {
        apiMock.get.mockResolvedValue([{ id: 'ch1', name: 'Aria' }]);
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useCharacters(), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual([{ id: 'ch1', name: 'Aria' }]));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/characters');
    });

    it('create/update/patch/delete invalidate the character list', async () => {
        apiMock.post.mockResolvedValue({ id: 'ch2' });
        apiMock.put.mockResolvedValue({ id: 'ch1' });
        apiMock.patch.mockResolvedValue({ id: 'ch1' });
        apiMock.delete.mockResolvedValue({ ok: true });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

        const create = renderHook(() => useCreateCharacter(), { wrapper });
        await act(async () => create.result.current.mutateAsync({ name: 'B' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/characters', { name: 'B' });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'characters'] });

        const update = renderHook(() => useUpdateCharacter(), { wrapper });
        await act(async () => update.result.current.mutateAsync({ id: 'ch1', name: 'C' }));
        expect(apiMock.put).toHaveBeenCalledWith('/api/v2/characters/ch1', { name: 'C' });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'characters', 'ch1'] });

        const patch = renderHook(() => usePatchCharacter(), { wrapper });
        await act(async () => patch.result.current.mutateAsync({ id: 'ch1', description: 'd' }));
        expect(apiMock.patch).toHaveBeenCalledWith('/api/v2/characters/ch1', { description: 'd' });

        const del = renderHook(() => useDeleteCharacter(), { wrapper });
        await act(async () => del.result.current.mutateAsync('ch1'));
        expect(apiMock.delete).toHaveBeenCalledWith('/api/v2/characters/ch1');
    });

    it('getAvatarUrl returns null without an id', () => {
        expect(getAvatarUrl(null)).toBeNull();
        expect(getAvatarUrl('ch1')).toBe('/api/v2/characters/ch1/avatar');
    });

    it('useUploadAvatar sends multipart form data and invalidates detail + list', async () => {
        apiMock.post.mockResolvedValue({ ok: true });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useUploadAvatar(), { wrapper });
        const file = new File(['x'], 'avatar.png', { type: 'image/png' });

        await act(async () => result.current.mutateAsync({ characterId: 'ch1', file }));
        const [url, formData, opts] = apiMock.post.mock.calls[0];
        expect(url).toBe('/api/v2/characters/ch1/avatar');
        expect(formData.get('file')).toBe(file);
        expect(opts.headers['Content-Type']).toBe('multipart/form-data');
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'characters', 'ch1'] });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'characters'] });
    });

    it('useImportCharacterCard posts multipart and invalidates the list', async () => {
        apiMock.post.mockResolvedValue({ id: 'ch9' });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useImportCharacterCard(), { wrapper });
        const formData = new FormData();
        formData.append('file', new File(['png'], 'card.png'));

        await act(async () => result.current.mutateAsync(formData));
        const [url, sentFormData, opts] = apiMock.post.mock.calls[0];
        expect(url).toBe('/api/v2/characters/import');
        expect(sentFormData).toBe(formData);
        expect(opts.headers['Content-Type']).toBe('multipart/form-data');
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'characters'] });
    });

    it('useCharacterCollection fetches from the legacy collections route and gates on id', async () => {
        apiMock.get.mockResolvedValue({ id: 'col1' });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useCharacterCollection('ch1'), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual({ id: 'col1' }));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/collections/by-character/ch1');
    });
});