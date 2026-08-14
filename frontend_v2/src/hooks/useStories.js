import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { useCreateResource, useDeleteResource, useUpdateResource } from './useWorldVaultResource';

const STORY_LIST_KEY = ['world_vault', 'stories'];
const STORY_DETAIL_KEY = (storyId) => ['world_vault', 'stories', storyId];

export const useStories = () => {
    return useQuery({
        queryKey: STORY_LIST_KEY,
        queryFn: () => api.get('/api/v2/stories')
    });
};

export const useStory = (storyId) => {
    return useQuery({
        queryKey: STORY_DETAIL_KEY(storyId),
        queryFn: () => api.get(`/api/v2/stories/${storyId}`),
        enabled: !!storyId
    });
};

export const useStoryChapters = (storyId) => {
    return useQuery({
        queryKey: ['world_vault', 'stories', storyId, 'chapters'],
        queryFn: () => api.get(`/api/v2/stories/${storyId}/chapters`),
        enabled: !!storyId
    });
};

export const useStoryImages = (storyId) => {
    return useQuery({
        queryKey: ['world_vault', 'story', 'images', storyId],
        queryFn: () => api.get(`/api/v2/stories/${storyId}/images`),
        enabled: !!storyId
    });
};

export const useCreateStory = () => useCreateResource({
    basePath: '/api/v2/stories',
    listQueryKey: STORY_LIST_KEY,
});

export const useCreateChapter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, data }) => api.post(`/api/v2/stories/${storyId}/chapters`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', variables.storyId, 'chapters'] });
        }
    });
};

export const useContinueChapter = () => {
    return useMutation({
        mutationFn: ({ storyId, chapterId, prompt }) => api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/continue`, { prompt: prompt || '' }),
    });
};

export const useBranchChapter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, fromBeatId, prompt }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/branch`, { from_beat_id: fromBeatId, prompt: prompt || '' }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', variables.storyId, 'chapters'] });
        }
    });
};

export const useAddStoryBeat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, content, role }) => api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/beats`, { content, role: role || 'user' }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', variables.storyId, 'chapters'] });
        }
    });
};

export const useIllustrateChapter = () => {
    return useMutation({
        mutationFn: ({ storyId, chapterId, image_prompt }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/illustrate`, { image_prompt: image_prompt || '' }),
    });
};

export const useDeleteStory = () => useDeleteResource({
    basePath: '/api/v2/stories',
    listQueryKey: STORY_LIST_KEY,
});

export const useUpdateStory = () => useUpdateResource({
    basePath: '/api/v2/stories',
    listQueryKey: STORY_LIST_KEY,
    detailQueryKey: STORY_DETAIL_KEY,
});

export const useDeleteChapter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId }) => api.delete(`/api/v2/stories/${storyId}/chapters/${chapterId}`),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', variables.storyId, 'chapters'] });
        }
    });
};

export const useUpdateChapter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, ...data }) => api.put(`/api/v2/stories/${storyId}/chapters/${chapterId}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', variables.storyId, 'chapters'] });
        }
    });
};
