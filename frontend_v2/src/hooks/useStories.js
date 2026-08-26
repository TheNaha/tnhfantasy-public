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
        queryKey: ['world_vault', 'stories', storyId, 'images'],
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

export const useUpdateStoryBeat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, beatId, content, role }) =>
            api.patch(`/api/v2/stories/${storyId}/chapters/${chapterId}/beats/${beatId}`, {
                ...(content !== undefined ? { content } : {}),
                ...(role !== undefined ? { role } : {}),
            }),
        onMutate: async ({ storyId, chapterId, beatId, content, role }) => {
            const key = ['world_vault', 'stories', storyId, 'chapters'];
            await queryClient.cancelQueries({ queryKey: key });
            const previous = queryClient.getQueryData(key);
            queryClient.setQueryData(key, (old) => {
                if (!old) return old;
                return old.map((ch) => {
                    if (ch.id !== chapterId) return ch;
                    return {
                        ...ch,
                        beats: (ch.beats || []).map((b) =>
                            b?.id === beatId
                                ? { ...b, ...(content !== undefined ? { content } : {}), ...(role !== undefined ? { role } : {}) }
                                : b
                        ),
                    };
                });
            });
            return { previous, key };
        },
        onError: (_, __, context) => {
            if (context?.previous) {
                queryClient.setQueryData(context.key, context.previous);
            }
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', variables.storyId, 'chapters'] });
        }
    });
};

export const useDeleteStoryBeat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, beatId }) =>
            api.delete(`/api/v2/stories/${storyId}/chapters/${chapterId}/beats/${beatId}`),
        onMutate: async ({ storyId, chapterId, beatId }) => {
            const key = ['world_vault', 'stories', storyId, 'chapters'];
            await queryClient.cancelQueries({ queryKey: key });
            const previous = queryClient.getQueryData(key);
            queryClient.setQueryData(key, (old) => {
                if (!old) return old;
                return old.map((ch) => {
                    if (ch.id !== chapterId) return ch;
                    return { ...ch, beats: (ch.beats || []).filter((b) => b?.id !== beatId) };
                });
            });
            return { previous, key };
        },
        onError: (_, __, context) => {
            if (context?.previous) {
                queryClient.setQueryData(context.key, context.previous);
            }
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', variables.storyId, 'chapters'] });
        }
    });
};

export const useStoryAiAction = () => {
    return useMutation({
        mutationFn: ({ storyId, chapterId, action, target_text, directive }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/ai-action`, {
                action,
                target_text: target_text || '',
                directive: directive || '',
            }),
    });
};

export const useRetryLastContinuation = () => {
    return useMutation({
        mutationFn: ({ storyId, chapterId }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/retry-last`),
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

export const useReorderChapters = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterIds }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/reorder`, { chapter_ids: chapterIds }),
        onMutate: async ({ storyId, chapterIds }) => {
            const key = ['world_vault', 'stories', storyId, 'chapters'];
            await queryClient.cancelQueries({ queryKey: key });
            const previous = queryClient.getQueryData(key);
            queryClient.setQueryData(key, (old) => {
                if (!old) return old;
                const byId = new Map(old.map((ch) => [ch.id, ch]));
                return chapterIds
                    .map((id, idx) => {
                        const ch = byId.get(id);
                        return ch ? { ...ch, chapter_number: idx + 1 } : null;
                    })
                    .filter(Boolean);
            });
            return { previous, key };
        },
        onError: (_, __, context) => {
            if (context?.previous) {
                queryClient.setQueryData(context.key, context.previous);
            }
        },
        onSettled: (_, __, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', variables.storyId, 'chapters'] });
        },
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



const FORMAT_EXT = { md: 'md', markdown: 'md', json: 'json', epub: 'epub', comic: 'pdf', webtoon: 'png' };

async function downloadFromExport(data, { storyId, format }) {
    const ext = FORMAT_EXT[format] || format;
    const filename = storyId ? `story-${storyId}.${ext}` : `story.${ext}`;
    let blob;
    if (data && typeof data.blob === 'function' && typeof data.arrayBuffer === 'function') {
        blob = await data.blob();
    } else if (data && typeof data.headers !== 'undefined') {
        blob = await new Response(data).blob();
    } else if (format === 'md' || format === 'markdown') {
        blob = new Blob([data.content || ''], { type: 'text/markdown' });
    } else if (format === 'json') {
        blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    } else {
        blob = new Blob([data?.content || ''], { type: 'application/octet-stream' });
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

export const useExportStoryFormatted = () => {
    return useMutation({
        mutationFn: ({ storyId, format }) => api.get(`/api/v2/stories/${storyId}/export?format=${format}`),
        onSuccess: downloadFromExport,
    });
};

// Token-based export for the public StoryReader (published stories).
// The read_published_story endpoint does not expose the DB story id, so
// we use the /published/{token}/export route instead.
export const useExportPublishedStory = () => {
    return useMutation({
        mutationFn: ({ token, format }) => api.get(`/api/v2/stories/published/${token}/export?format=${format}`, {
            responseType: 'blob',
        }),
        onSuccess: downloadFromExport,
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

export const useUnpublishStory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId }) => api.post(`/api/v2/stories/${storyId}/unpublish`),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', variables.storyId] });
        },
    });
};
