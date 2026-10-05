import { useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { invalidateVaultAggregates } from './useWorldVaultResource';
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
        }
    });
};

export const useUpdateCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`/api/v2/characters/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            invalidateVaultAggregates(queryClient);
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, variables.id) });
            invalidateVaultAggregates(queryClient);
        }
    });
};

export const usePatchCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.patch(`/api/v2/characters/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            invalidateVaultAggregates(queryClient);
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, variables.id) });
            invalidateVaultAggregates(queryClient);
        }
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
            invalidateVaultAggregates(queryClient);
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            invalidateVaultAggregates(queryClient);
        }
    });
};

export const useReorderCharacters = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (characterIds) => api.post('/api/v2/characters/reorder', { character_ids: characterIds }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            invalidateVaultAggregates(queryClient);
        }
    });
};

export const useDeleteCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v2/characters/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            invalidateVaultAggregates(queryClient);
        }
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
            invalidateVaultAggregates(queryClient);
            if (result?.character?.id) {
                queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, result.character.id) });
                invalidateVaultAggregates(queryClient);
            }
        }
    });
};

/**
 * Triggers a browser download of a character card. The endpoint streams a
 * file, so this navigates to the export URL instead of using the JSON client.
 */
export const useExportCharacterCard = () => {
    return useMutation({
        mutationFn: ({ character, format } = {}) => {
            const url = buildCharacterCardExportUrl(character?.id, format);
            if (!url) {
                throw new Error('Character is required to export a card');
            }
            const filename = buildCharacterCardExportFilename(character, format);
            downloadUrl(url, filename);
            return { url, filename, format: format || DEFAULT_CARD_EXPORT_FORMAT };
        }
    });
};

export const useCloneCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.post(`/api/v2/characters/${id}/clone`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            invalidateVaultAggregates(queryClient);
        }
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
            invalidateVaultAggregates(queryClient);
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, variables.characterId) });
            invalidateVaultAggregates(queryClient);
        }
    });
};
