import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export const useMessages = (chatId, { limit = 100, offset = 0 } = {}, options = {}) => {
    return useQuery({
        queryKey: ['world_vault', 'messages', chatId, limit, offset],
        queryFn: () => {
            if (!chatId) return [];
            const params = {};
            if (limit) params.limit = limit;
            if (offset) params.offset = offset;
            return api.get(`/api/v2/chats/${chatId}/messages`, { params });
        },
        enabled: !!chatId,
        ...options,
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
            if (variables?.chatId) {
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', variables.chatId] });
            }
        }
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
