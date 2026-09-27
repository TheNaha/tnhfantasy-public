import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { useCreateResource, useDeleteResource, useUpdateResource } from './useWorldVaultResource';

const VOICES_KEY = buildQueryKey(QUERY_KEYS.VOICES);
const VOICE_DETAIL_KEY = (id) => buildQueryKey(QUERY_KEYS.VOICES, id);

export const useVoices = () => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.VOICES),
        queryFn: () => api.get('/api/v2/voices'),
    });
};


export const useCreateVoice = () => useCreateResource({ basePath: '/api/v2/voices', listQueryKey: VOICES_KEY });

export const useUpdateVoice = () => useUpdateResource({
    basePath: '/api/v2/voices',
    listQueryKey: VOICES_KEY,
    detailQueryKey: VOICE_DETAIL_KEY,
});

export const useDeleteVoice = () => useDeleteResource({ basePath: '/api/v2/voices', listQueryKey: VOICES_KEY });

export const useVoicePreview = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ voiceId }) => api.post(`/api/v2/voices/${voiceId}/preview`),
        onSuccess: (_, { voiceId }) => {
            queryClient.invalidateQueries({ queryKey: VOICE_DETAIL_KEY(voiceId) });
        }
    });
};
