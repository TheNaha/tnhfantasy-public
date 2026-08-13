import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export const useChats = ({ limit = 50, offset = 0, workspace } = {}) => {
    const params = {};
    if (workspace) params.workspace = workspace;
    if (limit) params.limit = limit;
    if (offset) params.offset = offset;
    return useQuery({
        queryKey: ['world_vault', 'chats', workspace, limit, offset],
        queryFn: () => api.get('/api/v2/chats', { params })
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

export const useChatJobs = (chatId) => {
    const ACTIVE_STATUSES = ['pending', 'sent_to_provider', 'connected', 'pre_generation', 'generating', 'post_processing'];
    return useQuery({
        queryKey: ['world_vault', 'chats', chatId, 'jobs'],
        queryFn: () => {
            if (!chatId) return [];
            return api.get(`/api/v2/chats/${chatId}/jobs`);
        },
        enabled: !!chatId,
        refetchInterval: (query) => {
            const jobs = query.state.data;
            if (Array.isArray(jobs) && jobs.some(j => ACTIVE_STATUSES.includes(j.status))) return 5000;
            return 30000;
        },
        refetchIntervalInBackground: false
    });
};

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

export const useGenerateScene = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId }) => api.post(`/api/v2/chats/${chatId}/scene`, {}),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', variables.chatId] });
        }
    });
};

export const useSuggestReply = () => {
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
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', variables.chatId] });
        }
    });
};

export const useIllustrateChat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, imagePrompt }) =>
            api.post(`/api/v2/chats/${chatId}/illustrate`, { image_prompt: imagePrompt || '' }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', variables.chatId] });
        }
    });
};

export const useChatImages = (chatId) => {
    return useQuery({
        queryKey: ['world_vault', 'chat', 'images', chatId],
        queryFn: () => api.get(`/api/v2/chats/${chatId}/images`),
        enabled: !!chatId
    });
};
