import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export const useStories = () => {
    return useQuery({
        queryKey: ['world_vault', 'stories'],
        queryFn: () => api.get('/api/v2/stories')
    });
};

export const useStory = (storyId) => {
    return useQuery({
        queryKey: ['world_vault', 'stories', storyId],
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

export const useCreateStory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (storyData) => api.post('/api/v2/stories', storyData),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories'] });
        }
    });
};

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

export const useDeleteStory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (storyId) => api.delete(`/api/v2/stories/${storyId}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories'] });
        }
    });
};

export const useUpdateStory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`/api/v2/stories/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', variables.id] });
        }
    });
};

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
