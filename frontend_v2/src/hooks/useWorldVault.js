import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

// ============================================================================
// QUERIES
// ============================================================================

export const useCharacters = () => {
    return useQuery({
        queryKey: ['world_vault', 'characters'],
        queryFn: () => api.get('/api/v2/characters')
    });
};

export const useCharacter = (characterId) => {
    return useQuery({
        queryKey: ['world_vault', 'characters', characterId],
        queryFn: () => api.get(`/api/v2/characters/${characterId}`),
        enabled: !!characterId
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

export const useLorebooks = () => {
    return useQuery({
        queryKey: ['world_vault', 'lorebooks'],
        queryFn: () => api.get('/api/v2/lorebooks')
    });
};

export const useScenarios = () => {
    return useQuery({
        queryKey: ['world_vault', 'scenarios'],
        queryFn: () => api.get('/api/v2/scenarios')
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

export const useDeleteMessage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, msgId }) => api.delete(`/api/v2/chats/${chatId}/messages/${msgId}`),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', variables.chatId] });
        }
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
    queryKey: ['llm', 'default-provider'],
    queryFn: () => api.get('/api/v2/llm/default-provider'),
    staleTime: 1000 * 60 * 5,
});

export const useSetLLMDefaultProvider = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (config) => api.put('/api/v2/llm/default-provider', config),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['llm'] })
    });
};

export const useLLMAvailableModels = () => useQuery({
    queryKey: ['llm', 'models'],
    queryFn: () => api.get('/api/v2/llm/available-models'),
    staleTime: 1000 * 60 * 5,
});

