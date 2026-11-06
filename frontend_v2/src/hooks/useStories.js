import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { downloadJson, downloadText, triggerFile } from '../utils/download';
import { useCreateResource, useDeleteResource, useUpdateResource, invalidateVaultAggregates, reportError } from './useWorldVaultResource';

const STORY_LIST_KEY = buildQueryKey(QUERY_KEYS.STORIES);
const STORY_DETAIL_KEY = (storyId) => buildQueryKey(QUERY_KEYS.STORIES, storyId);
const STORY_CHAPTERS_KEY = (storyId) => buildQueryKey(QUERY_KEYS.STORIES, storyId, 'chapters');
const STORY_IMAGES_KEY = (storyId) => buildQueryKey(QUERY_KEYS.STORIES, storyId, 'images');
const CHAPTER_REVISIONS_KEY = (storyId, chapterId) =>
    buildQueryKey(QUERY_KEYS.STORIES, storyId, 'chapters', chapterId, 'revisions');

export const useStories = () => {
    return useQuery({
        queryKey: STORY_LIST_KEY,
        queryFn: ({ signal }) => api.get('/api/v2/stories', { signal })
    });
};

export const useStory = (storyId) => {
    return useQuery({
        queryKey: STORY_DETAIL_KEY(storyId),
        queryFn: ({ signal }) => api.get(`/api/v2/stories/${storyId}`, { signal }),
        enabled: !!storyId
    });
};

export const useStoryChapters = (storyId) => {
    return useQuery({
        queryKey: STORY_CHAPTERS_KEY(storyId),
        queryFn: ({ signal }) => api.get(`/api/v2/stories/${storyId}/chapters`, { signal }),
        enabled: !!storyId
    });
};

export const useStoryImages = (storyId) => {
    return useQuery({
        queryKey: STORY_IMAGES_KEY(storyId),
        queryFn: ({ signal }) => api.get(`/api/v2/stories/${storyId}/images`, { signal }),
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
            queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(variables.storyId) });
            invalidateVaultAggregates(queryClient);
        }
    });
};

export const useContinueChapter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, prompt, directive, directorPreset }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/continue`, {
                prompt: prompt || '',
                directive: directive || undefined,
                director_preset: directorPreset || undefined,
            }),
        onMutate: async ({ storyId, chapterId, prompt }) => {
            const key = STORY_CHAPTERS_KEY(storyId);
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
        onError: (error, { storyId }, context) => {
            if (context?.previous) {
                queryClient.setQueryData(STORY_CHAPTERS_KEY(storyId), context.previous);
            }
            reportError('continue story', error);
        },
        onSuccess: (_, variables) => {
            queryClient.setQueryData(STORY_CHAPTERS_KEY(variables.storyId), (old) =>
                old?.map((ch) => ch.id === variables.chapterId ? { ...ch, _isStreaming: false } : ch)
            );
            queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(variables.storyId) });
            invalidateVaultAggregates(queryClient);
        },
    });
};

export const useDiscoverWorldbuilding = () => {
    return useMutation({
        mutationFn: ({ storyId, chapterId }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/discover-worldbuilding`),
    });
};

export const useAdoptWorldbuilding = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, data }) =>
            api.post(`/api/v2/stories/${storyId}/adopt-worldbuilding`, data),
        onSuccess: () => {
            // These must be ARRAY keys. React Query prefix-matches, and a
            // bare string never prefix-matches an array key - so the bare
            // `QUERY_KEYS.LOCATIONS` this used to pass invalidated NOTHING,
            // and the Locations and Lorebooks lists kept their pre-adopt
            // contents for the whole global staleTime.
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.LOCATIONS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.LOREBOOKS) });
            invalidateVaultAggregates(queryClient);
        },
    });
};

export const useBranchChapter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, fromBeatId, prompt }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/branch`, { from_beat_id: fromBeatId, prompt: prompt || '' }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(variables.storyId) });
            invalidateVaultAggregates(queryClient);
        }
    });
};

export const useAddStoryBeat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, content, role }) => api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/beats`, { content, role: role || 'user' }),
        onMutate: async ({ storyId, chapterId, content, role }) => {
            const key = STORY_CHAPTERS_KEY(storyId);
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
        onError: (error, { storyId }, context) => {
            if (context?.previous) {
                queryClient.setQueryData(STORY_CHAPTERS_KEY(storyId), context.previous);
            }
            reportError('continue chapter', error);
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(variables.storyId) });
            invalidateVaultAggregates(queryClient);
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
            const key = STORY_CHAPTERS_KEY(storyId);
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
        onError: (error, __, context) => {
            if (context?.previous) {
                queryClient.setQueryData(context.key, context.previous);
            }
            reportError('update story beat', error);
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(variables.storyId) });
            invalidateVaultAggregates(queryClient);
        }
    });
};

export const useSelectStoryBeatAlternate = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, beatId, index }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/beats/${beatId}/select-alternate`, { index }),
        onMutate: async ({ storyId, chapterId, beatId, index }) => {
            // Optimistic, for the same reason the beat edit is: the server
            // response replaces the chapter wholesale, so waiting for the round
            // trip leaves the prose on screen behind the beat the user just
            // switched away from.
            const key = STORY_CHAPTERS_KEY(storyId);
            await queryClient.cancelQueries({ queryKey: key });
            const previous = queryClient.getQueryData(key);
            queryClient.setQueryData(key, (old) => {
                if (!old) return old;
                return old.map((ch) => {
                    if (ch.id !== chapterId) return ch;
                    return {
                        ...ch,
                        beats: (ch.beats || []).map((b) => {
                            if (b?.id !== beatId) return b;
                            const alternates = b?.alternates || [];
                            const take = alternates[index];
                            if (!take) return b;
                            return {
                                ...b,
                                active_index: index,
                                content: take.text || '',
                                // The stamp follows the take, so the reconciler
                                // looks for the job that produced the text on screen.
                                ...(take.source_job_id ? { source_job_id: take.source_job_id } : {}),
                            };
                        }),
                    };
                });
            });
            return { previous };
        },
        onError: (error, _variables, context) => {
            if (context?.previous) {
                queryClient.setQueryData(STORY_CHAPTERS_KEY(_variables.storyId), context.previous);
            }
            reportError('select story beat alternate', error);
        },
        onSettled: (_data, _err, variables) => {
            queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(variables.storyId) });
        },
    });
};

export const useDeleteStoryBeat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, beatId }) =>
            api.delete(`/api/v2/stories/${storyId}/chapters/${chapterId}/beats/${beatId}`),
        onMutate: async ({ storyId, chapterId, beatId }) => {
            const key = STORY_CHAPTERS_KEY(storyId);
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
        onError: (error, __, context) => {
            if (context?.previous) {
                queryClient.setQueryData(context.key, context.previous);
            }
            reportError('delete story beat', error);
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(variables.storyId) });
            invalidateVaultAggregates(queryClient);
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

const revisionsKey = (storyId, chapterId) =>
    CHAPTER_REVISIONS_KEY(storyId, chapterId);

export const useChapterRevisions = (storyId, chapterId) => {
    return useQuery({
        queryKey: revisionsKey(storyId, chapterId),
        queryFn: ({ signal }) => api.get(`/api/v2/stories/${storyId}/chapters/${chapterId}/revisions`, { signal }),
        enabled: Boolean(storyId && chapterId),
    });
};

export const useCreateChapterRevision = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/revisions`),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: revisionsKey(variables.storyId, variables.chapterId) });
        },
    });
};

export const useRestoreChapterRevision = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, revisionId }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/revisions/${revisionId}/restore`),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(variables.storyId) });
            invalidateVaultAggregates(queryClient);
            queryClient.invalidateQueries({ queryKey: revisionsKey(variables.storyId, variables.chapterId) });
        },
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
            queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(variables.storyId) });
            invalidateVaultAggregates(queryClient);
        }
    });
};

export const useUpdateChapter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, ...data }) => api.put(`/api/v2/stories/${storyId}/chapters/${chapterId}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(variables.storyId) });
            invalidateVaultAggregates(queryClient);
        }
    });
};

export const useReorderChapters = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterIds }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/reorder`, { chapter_ids: chapterIds }),
        onMutate: async ({ storyId, chapterIds }) => {
            const key = STORY_CHAPTERS_KEY(storyId);
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
        onError: (error, __, context) => {
            if (context?.previous) {
                queryClient.setQueryData(context.key, context.previous);
            }
            reportError('reorder chapters', error);
        },
        onSettled: (_, __, variables) => {
            queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(variables.storyId) });
            invalidateVaultAggregates(queryClient);
        },
    });
};

export const useParseStory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, text }) => api.post(`/api/v2/stories/parse`, { story_id: storyId, text }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.LOREBOOKS) });
            queryClient.invalidateQueries({ queryKey: STORY_LIST_KEY });
        }
    });
};



const FORMAT_EXT = { md: 'md', markdown: 'md', json: 'json', epub: 'epub', comic: 'pdf', webtoon: 'png' };

async function downloadFromExport(data, { storyId, format }) {
    const ext = FORMAT_EXT[format] || format;
    const filename = storyId ? `story-${storyId}.${ext}` : `story.${ext}`;
    // `responseType: 'blob'` already resolves to a Blob; handing that to
    // `new Blob([data.content])` produced a 0-byte file for every binary format.
    if (data instanceof Blob) {
        triggerFile(data, filename);
        return;
    }
    if (typeof Response !== 'undefined' && data instanceof Response) {
        triggerFile(await data.blob(), filename);
        return;
    }
    if (format === 'json') {
        downloadJson(data, filename);
        return;
    }
    const text = typeof data === 'string' ? data : (data?.content ?? '');
    downloadText(text, filename, format === 'md' || format === 'markdown' ? 'text/markdown' : 'application/octet-stream');
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

// Comic/webtoon export for a specific chapter. Generates panel images with
// character consistency, then assembles a CBZ archive + HTML reader.
// Returns a job id; the frontend polls job status or listens for the
// job.completed WebSocket event carrying the download URL.
export const useExportChapterComic = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId, format }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/export-comic`, {
                format: format || 'cbz',
            }),
        onSuccess: (data, variables) => {
            // Invalidate the story detail so any badge reflects the new export.
            queryClient.invalidateQueries({ queryKey: STORY_DETAIL_KEY(variables.storyId), exact: true });
        },
    });
};

export const useNarrateChapter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId }) =>
            api.post(`/api/v2/stories/${storyId}/chapters/${chapterId}/narrate`),
        onSuccess: (_, variables) => {
            // The story-prefix key also matched the list query, but refetched
            // every chapter of the story; the list keeps the summary rows fresh.
            queryClient.invalidateQueries({ queryKey: STORY_DETAIL_KEY(variables.storyId), exact: true });
            queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(variables.storyId) });
            invalidateVaultAggregates(queryClient);
            queryClient.invalidateQueries({ queryKey: STORY_LIST_KEY });
        },
    });
};

export const usePublishStory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId }) => api.post(`/api/v2/stories/${storyId}/publish`),
        onSuccess: (_, variables) => {
            // The list carries the `is_published` badge shown in the sidebar.
            queryClient.invalidateQueries({ queryKey: STORY_DETAIL_KEY(variables.storyId), exact: true });
            queryClient.invalidateQueries({ queryKey: STORY_LIST_KEY });
        },
    });
};

export const useUnpublishStory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId }) => api.post(`/api/v2/stories/${storyId}/unpublish`),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: STORY_DETAIL_KEY(variables.storyId), exact: true });
            queryClient.invalidateQueries({ queryKey: STORY_LIST_KEY });
        },
    });
};

export const useStartChatFromStory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ storyId, chapterId }) =>
            api.post(`/api/v2/stories/${storyId}/start-chat`, chapterId ? { chapter_id: chapterId } : {}),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHATS) });
            invalidateVaultAggregates(queryClient);
        },
    });
};

