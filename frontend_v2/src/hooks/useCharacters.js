import { useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { invalidateVaultAggregates, reportError } from './useWorldVaultResource';
import { getApiUrl } from '../api/config';
import {
    DEFAULT_CARD_EXPORT_FORMAT,
    assertCharacterCardFile,
    buildCharacterCardExportFilename,
    buildCharacterCardExportUrl,
    normalizeCardImportResult,
} from '../api/characterCards';

function appendCardFile(formData, file) {
    formData.append('file', file, file?.name);
    return formData;
}

function downloadUrl(url, filename) {
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = 'noopener';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
}

export const useCharacters = () => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS),
        queryFn: ({ signal }) => api.get('/api/v2/characters', { signal })
    });
};

export const useCreateCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (characterData) => api.post('/api/v2/characters', characterData),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            invalidateVaultAggregates(queryClient);
        },
        onError: (error) => reportError('create character', error),
    });
};

export const useUpdateCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`/api/v2/characters/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, variables.id) });
            invalidateVaultAggregates(queryClient);
        },
        onError: (error) => reportError('update character', error),
    });
};

export const usePatchCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.patch(`/api/v2/characters/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, variables.id) });
            invalidateVaultAggregates(queryClient);
        },
        onError: (error) => reportError('patch character', error),
    });
};

export const getAvatarUrl = (characterId) =>
    characterId ? `${getApiUrl()}/api/v2/characters/${characterId}/avatar` : null;

export const useUploadAvatar = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ characterId, file }) => {
            const formData = new FormData();
            formData.append('file', file);
            return api.post(`/api/v2/characters/${characterId}/avatar`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, variables.characterId) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            invalidateVaultAggregates(queryClient);
        },
        onError: (error) => reportError('upload avatar', error),
    });
};

export const useReorderCharacters = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (characterIds) => api.post('/api/v2/characters/reorder', { character_ids: characterIds }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            invalidateVaultAggregates(queryClient);
        },
        onError: (error) => reportError('reorder characters', error),
    });
};

export const useDeleteCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v2/characters/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            invalidateVaultAggregates(queryClient);
        },
        onError: (error) => reportError('delete character', error),
    });
};

export const useImportCharacterCard = () => {
    const queryClient = useQueryClient();
    return useMutation({
        // Accepts a File, a FormData (legacy callers), or { file }.
        mutationFn: async (payload) => {
            const isFormData = typeof FormData !== 'undefined' && payload instanceof FormData;
            const file = isFormData ? payload.get('file') : payload?.file || payload;

            if (!isFormData) {
                assertCharacterCardFile(file);
            }

            const formData = isFormData
                ? payload
                : appendCardFile(new FormData(), file);

            const raw = await api.post('/api/v2/characters/import', formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });

            return normalizeCardImportResult(raw);
        },
        onSuccess: (result) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            if (result?.character?.id) {
                queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, result.character.id) });
            }
            invalidateVaultAggregates(queryClient);
        },
        onError: (error) => reportError('import character card', error),
    });
};

/**
 * Triggers a browser download of a character card. The endpoint streams a
 * file, so this navigates to the export URL instead of using the JSON client.
 */
export const useExportCharacterCard = () => {
    return useMutation({
        mutationFn: ({ character, format, include } = {}) => {
            const url = buildCharacterCardExportUrl(character?.id, format, include);
            if (!url) {
                throw new Error('Character is required to export a card');
            }
            const filename = buildCharacterCardExportFilename(character, format);
            downloadUrl(url, filename);
            return { url, filename, format: format || DEFAULT_CARD_EXPORT_FORMAT };
        },
        onError: (error) => reportError('export character card', error),
    });
};

/**
 * What an export of this character can and cannot carry.
 *
 * The export is a PNG or an archive, so it has nowhere to say "this
 * character has six expressions and a voice model and the card has
 * neither". The export menu shows this BEFORE the download, so the user
 * finds out here rather than by opening the card elsewhere.
 */
export const useCharacterExportPreview = (characterId, options = {}) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, characterId, 'export-preview'),
        queryFn: ({ signal }) =>
            api.get(`/api/v2/characters/${characterId}/export/preview`, { signal }),
        enabled: Boolean(characterId),
        staleTime: 30_000,
        ...options,
    });
};

/**
 * Preview what importing a card would do. Writes nothing.
 *
 * The import used to write immediately, so the only way to find out what a
 * card would do was to do it — and re-importing a card created a second
 * character with the same name, silently.
 */
export const useAnalyzeCharacterCard = () => {
    return useMutation({
        mutationFn: async (payload) => {
            const file = payload?.file || payload;
            assertCharacterCardFile(file);
            const formData = appendCardFile(new FormData(), file);
            return api.post('/api/v2/characters/import/analyze', formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
        },
        onError: (error) => reportError('analyze character card', error),
    });
};

/**
 * Import a card with the scope and the match already chosen.
 *
 * `scope` is 'character' (the card's fields and nothing else) or 'world'
 * (the World Architect's blueprint). `matchAction` is 'auto', 'update' or
 * 'create'.
 */
export const useCommitCharacterCard = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ file, scope = 'character', matchAction = 'auto' } = {}) => {
            assertCharacterCardFile(file);
            const formData = appendCardFile(new FormData(), file);
            formData.append('scope', scope);
            formData.append('match_action', matchAction);
            const raw = await api.post('/api/v2/characters/import/commit', formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            return raw?.scope === 'world' ? { character: null, compatibility: null, raw } : normalizeCardImportResult(raw);
        },
        onSuccess: (result) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            if (result?.character?.id) {
                queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, result.character.id) });
            }
            invalidateVaultAggregates(queryClient);
        },
        onError: (error) => reportError('commit character card', error),
    });
};

export const useCloneCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.post(`/api/v2/characters/${id}/clone`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            invalidateVaultAggregates(queryClient);
        },
        onError: (error) => reportError('clone character', error),
    });
};

export const useCharacterCollection = (characterId) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, characterId, 'collection'),
        queryFn: ({ signal }) => api.get(`/api/v2/collections/by-character/${characterId}`, { signal }),
        enabled: !!characterId
    });
};

export const useCharacterCollections = (characterIds) => {
    const idsParam = useMemo(
        () => [...new Set((characterIds || []).filter(Boolean))].sort().join(','),
        [characterIds]
    );
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, 'collections-batch', idsParam),
        queryFn: ({ signal }) => api.get('/api/v2/collections/by-characters', { params: { ids: idsParam }, signal }),
        enabled: idsParam.length > 0
    });
};

export const useAnimateCharacterAvatar = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ characterId, prompt, checkpoint }) => {
            const response = await api.post(`/api/v2/characters/${characterId}/avatar/animate`, {
                prompt,
                checkpoint
            });
            return response;
        },
        onSuccess: (data, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, variables.characterId) });
            invalidateVaultAggregates(queryClient);
        },
        onError: (error) => reportError('animate character avatar', error),
    });
};
