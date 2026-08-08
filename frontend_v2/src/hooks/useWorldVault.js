import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { LLM_DEFAULT_KEY, LLM_MODELS_KEY, LLM_PROVIDERS_KEY } from './useLLMProviderStatus';

// ============================================================================
// QUERIES
// ============================================================================

export const useCharacters = () => {
    return useQuery({
        queryKey: ['world_vault', 'characters'],
        queryFn: () => api.get('/api/v2/characters')
    });
};

export const useChats = () => {
    return useQuery({
        queryKey: ['world_vault', 'chats'],
        queryFn: () => api.get('/api/v2/chats')
    });
};

export const useMessages = (chatId) => {
    return useQuery({
        queryKey: ['world_vault', 'messages', chatId],
        queryFn: () => {
            if (!chatId) return [];
            return api.get(`/api/v2/chats/${chatId}/messages`);
        },
        enabled: !!chatId
    });
};

export const useChat = (chatId) => {
    return useQuery({
        queryKey: ['world_vault', 'chats', chatId],
        queryFn: () => {
            if (!chatId) return null;
            return api.get(`/api/v2/chats/${chatId}`);
        },
        enabled: !!chatId
    });
};

export const useChatSystemPrompt = (chatId) => {
    return useQuery({
        queryKey: ['world_vault', 'chats', chatId, 'system-prompt'],
        queryFn: () => {
            if (!chatId) return null;
            return api.get(`/api/v2/chats/${chatId}/system-prompt`);
        },
        enabled: !!chatId
    });
};

export const useLorebooks = () => {
    return useQuery({
        queryKey: ['world_vault', 'lorebooks'],
        queryFn: () => api.get('/api/v2/lorebooks')
    });
};

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

// ============================================================================
// MUTATIONS
// ============================================================================

export const useCreateChat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (chatData) => api.post('/api/v2/chats', chatData),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats'] });
        }
    });
};

export const useRenameChat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, name }) => api.patch(`/api/v2/chats/${chatId}`, { name }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', variables.chatId] });
        }
    });
};export const useSuggestReply = () => {
    return useMutation({
        mutationFn: ({ chatId, draft }) => api.post(`/api/v2/chats/${chatId}/suggest`, { draft }),
    });
};


export const useUpdateChat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, ...data }) => api.patch(`/api/v2/chats/${chatId}`, data),
        onMutate: async (variables) => {
            const { chatId, ...data } = variables;
            await queryClient.cancelQueries({ queryKey: ['world_vault', 'chats', chatId] });
            const previousChat = queryClient.getQueryData(['world_vault', 'chats', chatId]);
            
            if (previousChat) {
                queryClient.setQueryData(['world_vault', 'chats', chatId], {
                    ...previousChat,
                    ...data
                });
            }
            
            // Also optimistically update the list
            await queryClient.cancelQueries({ queryKey: ['world_vault', 'chats'] });
            const previousChats = queryClient.getQueryData(['world_vault', 'chats']);
            if (previousChats) {
                queryClient.setQueryData(['world_vault', 'chats'], 
                    previousChats.map(c => c.id === chatId ? { ...c, ...data } : c)
                );
            }
            
            return { previousChat, previousChats };
        },
        onError: (err, variables, context) => {
            if (context?.previousChat) {
                queryClient.setQueryData(['world_vault', 'chats', variables.chatId], context.previousChat);
            }
            if (context?.previousChats) {
                queryClient.setQueryData(['world_vault', 'chats'], context.previousChats);
            }
        },
        onSettled: (data, error, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', variables.chatId] });
            // The system-prompt preview is derived from server state — refresh it.
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', variables.chatId, 'system-prompt'] });
        }
    });
};

export const useDeleteChat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (chatId) => api.delete(`/api/v2/chats/${chatId}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats'] });
        }
    });
};

export const useSendMessage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, message }) => api.post(`/api/v2/chats/${chatId}/messages`, message),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats'] });
        }
    });
};

export const useEditMessage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, msgId, content }) =>
            api.patch(`/api/v2/chats/${chatId}/messages/${msgId}`, { content }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', variables.chatId] });
        }
    });
};

export const useRollbackChat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, messageId }) =>
            api.post(`/api/v2/chats/${chatId}/rollback`, { message_id: messageId }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', variables.chatId] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', variables.chatId] });
        }
    });
};

export const useRegenerateReply = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, messageId }) =>
            api.post(`/api/v2/chats/${chatId}/regenerate`, messageId ? { message_id: messageId } : {}),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats'] });
            // The backend already deleted the old reply; refetching messages
            // hides it immediately while the new reply streams in.
            if (variables?.chatId) {
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', variables.chatId] });
            }
        }
    });
};

export const useChatJobs = (chatId) => {
    const ACTIVE_STATUSES = ['pending', 'sent_to_provider', 'connected', 'pre_generation', 'generating', 'post_processing'];
    return useQuery({
        queryKey: ['world_vault', 'chats', chatId, 'jobs'],
        queryFn: () => {
            if (!chatId) return [];
            return api.get(`/api/v2/chats/${chatId}/jobs`);
        },
        enabled: !!chatId,
        // Poll fast while a job is running; back off to 30s otherwise so an
        // idle open chat doesn't re-fetch + re-render every 5 seconds on mobile.
        refetchInterval: (query) => {
            const jobs = query.state.data;
            if (Array.isArray(jobs) && jobs.some(j => ACTIVE_STATUSES.includes(j.status))) return 5000;
            return 30000;
        },
        refetchIntervalInBackground: false
    });
};

export const useImpersonateMessage = () => {
    return useMutation({
        mutationFn: ({ chatId, hint }) =>
            api.post(`/api/v2/chats/${chatId}/impersonate`, { hint: hint || '' }),
    });
};

export const usePinMessage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, msgId, pinned }) =>
            api.patch(`/api/v2/chats/${chatId}/messages/${msgId}/pin`, { pinned }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', variables.chatId] });
        },
    });
};

export const useSwipeMessage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, msgId, direction, index }) =>
            api.post(`/api/v2/chats/${chatId}/messages/${msgId}/swipe`, { direction, index }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', variables.chatId] });
        },
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
    characterId ? `/api/v2/characters/${characterId}/avatar` : null;

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
        mutationFn: (formData) => api.post('/api/v2/characters/import', formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
        }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
        }
    });
};

export const useCharacterCollection = (characterId) => {
    return useQuery({
        queryKey: ['world_vault', 'characters', characterId, 'collection'],
        queryFn: () => api.get(`/api/collections/by-character/${characterId}`),
        enabled: !!characterId
    });
};

export const useChatImages = (chatId) => {
    return useQuery({
        queryKey: ['world_vault', 'chat', 'images', chatId],
        queryFn: () => api.get(`/api/v2/chats/${chatId}/images`),
        enabled: !!chatId
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

// ============================================================================
// AI / LLM Config
// ============================================================================

export const useLLMDefaultProvider = () => useQuery({
    queryKey: LLM_DEFAULT_KEY,
    queryFn: () => api.get('/api/v2/llm/default-provider'),
    staleTime: 1000 * 60 * 5,
});

export const useLLMAvailableModels = () => useQuery({
    queryKey: LLM_MODELS_KEY,
    queryFn: () => api.get('/api/v2/llm/available-models'),
    staleTime: 1000 * 60 * 5,
});
