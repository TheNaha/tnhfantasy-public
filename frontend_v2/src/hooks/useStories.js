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
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, prompt }) => api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/continue`, { prompt: prompt || '' }),
        onMutate: async ({ storyId, chapterId, prompt }) => {
            const key = ['world_vault', 'stories', storyId, 'chapters'];
            await queryClient.cancelQueries({ queryKey: key });
            const previous = queryClient.getQueryData(key);
            queryClient.setQueryData(key, (old) => {
                if (!old) return old;
                return old.map((ch) => {
                    if (ch.id !== chapterId) return ch;
                    return {
                        ...ch,
                        content: (ch.content || '') + (prompt ? `\n\n${prompt}` : ''),
                        _isStreaming: true,
                    };
                });
            });
            return { previous };
        },
        onError: (_, { storyId }, context) => {
            if (context?.previous) {
                queryClient.setQueryData(['world_vault', 'stories', storyId, 'chapters'], context.previous);
            }
        },
        onSuccess: (_, variables) => {
            queryClient.setQueryData(['world_vault', 'stories', variables.storyId, 'chapters'], (old) =>
                old?.map((ch) => ch.id === variables.chapterId ? { ...ch, _isStreaming: false } : ch)
            );
        },
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
        onMutate: async ({ storyId, chapterId, content, role }) => {
            const key = ['world_vault', 'stories', storyId, 'chapters'];
            await queryClient.cancelQueries({ queryKey: key });
            const previous = queryClient.getQueryData(key);
            const optimisticBeat = {
                id: `temp-${crypto.randomUUID()}`,
                parent_beat_id: null,
                role: role || 'user',
                content,
            };
            queryClient.setQueryData(key, (old) => {
                if (!old) return old;
                return old.map((ch) => {
                    if (ch.id !== chapterId) return ch;
                    return {
                        ...ch,
                        beats: [...(ch.beats || []), optimisticBeat],
                    };
                });
            });
            return { previous };
        },
        onError: (_, { storyId }, context) => {
            if (context?.previous) {
                queryClient.setQueryData(['world_vault', 'stories', storyId, 'chapters'], context.previous);
            }
        },
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

export const useParseStory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, text }) => api.post(`/api/v2/stories/parse`, { story_id: storyId, text }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'lorebooks'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories'] });
        }
    });
};

export const useExportStory = () => {
    return useMutation({
        mutationFn: ({ storyId }) => api.get(`/api/v2/stories/${storyId}/export`),
        onSuccess: (data) => {
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `story-${data.story?.title || 'export'}.json`;
            a.click();
            URL.revokeObjectURL(url);
        }
    });
};

export const useExportStoryFormatted = (format = 'json') => {
    return useMutation({
        mutationFn: ({ storyId }) => api.get(`/api/v2/stories/${storyId}/export?format=${format}`),
        onSuccess: (data, { storyId }) => {
            let blob, filename;
            if (format === 'md' || format === 'markdown') {
                blob = new Blob([data.content || ''], { type: 'text/markdown' });
                filename = `story-${storyId}.md`;
            } else if (format === 'epub') {
                blob = new Blob([data.content || ''], { type: 'application/epub+zip' });
                filename = `story-${storyId}.epub`;
            } else {
                blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                filename = `story-${storyId}.json`;
            }
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(url);
        }
    });
};

export const useNarrateChapter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/narrate`),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', variables.storyId] });
        },
    });
};

export const usePublishStory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId }) => api.post(`/api/v2/stories/${storyId}/publish`),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', variables.storyId] });
        },
    });
};
