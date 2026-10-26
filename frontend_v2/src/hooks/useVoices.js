import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { useCreateResource, useDeleteResource, useUpdateResource } from './useWorldVaultResource';

const VOICES_KEY = buildQueryKey(QUERY_KEYS.VOICES);

export const useVoices = () => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.VOICES),
        queryFn: ({ signal }) => api.get('/api/v2/voices', { signal }),
    });
};


export const useCreateVoice = () => useCreateResource({ basePath: '/api/v2/voices', listQueryKey: VOICES_KEY });

// No `detailQueryKey`: there is no per-voice query. `useVoices` declares only
// the list, and `invalidateQueries` prefix-matches, so a key of
// `['world_vault','voices',id]` matched nothing at all — the preview below
// invalidated a query that did not exist and the voices list kept whatever
// `preview_path` it had.
export const useUpdateVoice = () => useUpdateResource({
    basePath: '/api/v2/voices',
    listQueryKey: VOICES_KEY,
});

export const useDeleteVoice = () => useDeleteResource({ basePath: '/api/v2/voices', listQueryKey: VOICES_KEY });

export const useVoicePreview = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ voiceId }) => api.post(`/api/v2/voices/${voiceId}/preview`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: VOICES_KEY });
        }
    });
};

export const useDesignVoice = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data) => api.post('/api/v2/voices/design', data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: VOICES_KEY });
        },
    });
};

export const useVoicePresets = () => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.VOICE_PRESETS),
        queryFn: ({ signal }) => api.get('/api/v2/voices/presets', { signal }),
    });
};

