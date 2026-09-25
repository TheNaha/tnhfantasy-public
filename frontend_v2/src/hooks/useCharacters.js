import { useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
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
        queryKey: ['world_vault', 'characters'],
        queryFn: () => api.get('/api/v2/characters')
    });
};

export const useCreateCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (characterData) => api.post('/api/v2/characters', characterData),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
        }
    });
};

export const useUpdateCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`/api/v2/characters/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', variables.id] });
        }
    });
};

export const usePatchCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.patch(`/api/v2/characters/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', variables.id] });
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
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', variables.characterId] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
        }
    });
};

export const useReorderCharacters = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (characterIds) => api.post('/api/v2/characters/reorder', { character_ids: characterIds }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
        }
    });
};

export const useDeleteCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v2/characters/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
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
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
            if (result?.character?.id) {
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', result.character.id] });
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
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
        }
    });
};

export const useCharacterCollection = (characterId) => {
    return useQuery({
        queryKey: ['world_vault', 'characters', characterId, 'collection'],
        queryFn: () => api.get(`/api/v2/collections/by-character/${characterId}`),
        enabled: !!characterId
    });
};

export const useCharacterCollections = (characterIds) => {
    const idsParam = useMemo(
        () => [...new Set((characterIds || []).filter(Boolean))].sort().join(','),
        [characterIds]
    );
    return useQuery({
        queryKey: ['world_vault', 'characters', 'collections-batch', idsParam],
        queryFn: () => api.get('/api/v2/collections/by-characters', { params: { ids: idsParam } }),
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
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', variables.characterId] });
        }
    });
};
