import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export const useMessages = (chatId, { limit = 100, offset = 0, branchId = null, search = null, tail = false } = {}, options = {}) => {
    return useQuery({
        queryKey: ['world_vault', 'messages', chatId, limit, offset, branchId ?? 'active', search ?? '', tail ? 'tail' : 'asc'],
        queryFn: () => {
            if (!chatId) return [];
            const params = {};
            if (limit) params.limit = limit;
            if (offset) params.offset = offset;
            if (branchId) params.branch_id = branchId;
            if (search) params.q = search;
            if (tail) params.tail = true;
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
        onMutate: async ({ chatId, msgId, content }) => {
            await queryClient.cancelQueries({ queryKey: ['world_vault', 'messages', chatId] });
            const previous = queryClient.getQueriesData({ queryKey: ['world_vault', 'messages', chatId] });
            queryClient.setQueriesData({ queryKey: ['world_vault', 'messages', chatId] }, (old) =>
                Array.isArray(old) ? old.map((m) => m.id === msgId ? { ...m, content } : m) : old
            );
            return { previous };
        },
        onError: (_, _vars, context) => {
            if (context?.previous) {
                context.previous.forEach(([key, data]) => queryClient.setQueryData(key, data));
            }
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', variables.chatId] });
        }
    });
};

export const useDeleteMessage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, msgId }) =>
            api.delete(`/api/v2/chats/${chatId}/messages/${msgId}`),
        onMutate: async ({ chatId, msgId }) => {
            await queryClient.cancelQueries({ queryKey: ['world_vault', 'messages', chatId] });
            const previous = queryClient.getQueriesData({ queryKey: ['world_vault', 'messages', chatId] });
            queryClient.setQueriesData({ queryKey: ['world_vault', 'messages', chatId] }, (old) =>
                Array.isArray(old) ? old.filter((m) => m.id !== msgId) : old
            );
            return { previous };
        },
        onError: (_, _vars, context) => {
            if (context?.previous) {
                context.previous.forEach(([key, data]) => queryClient.setQueryData(key, data));
            }
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', variables.chatId] });
            // `exact: true`: the 3-element chat key prefix-matches the
            // system-prompt / jobs / images / branches sub-queries, so a plain
            // invalidation here refetched the whole system-prompt assembly for a
            // delete that only changes the message list.
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', variables.chatId], exact: true });
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
            // See useDeleteMessage: exact, so the rollback does not drag the
            // system-prompt assembly along with it.
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', variables.chatId], exact: true });
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

export const useGenerateSwipe = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, msgId }) =>
            api.post(`/api/v2/chats/${chatId}/messages/${msgId}/generate-swipe`),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', variables.chatId] });
        },
    });
};

export const useNarrateMessage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, msgId, voiceId, language }) =>
            api.post(`/api/v2/chats/${chatId}/messages/${msgId}/narrate`, {
                ...(voiceId ? { voice_id: voiceId } : {}),
                ...(language ? { language } : {})
            }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', variables.chatId] });
        },
    });
};
