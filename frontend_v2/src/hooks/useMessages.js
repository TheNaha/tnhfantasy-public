import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { invalidateVaultAggregates } from './useWorldVaultResource';

export const useMessages = (chatId, { limit = 100, offset = 0, branchId = null, search = null, tail = false } = {}, options = {}) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, chatId, limit, offset, branchId ?? 'active', search ?? '', tail ? 'tail' : 'asc'),
        queryFn: ({ signal }) => {
            if (!chatId) return [];
            const params = {};
            if (limit) params.limit = limit;
            if (offset) params.offset = offset;
            if (branchId) params.branch_id = branchId;
            if (search) params.q = search;
            if (tail) params.tail = true;
            return api.get(`/api/v2/chats/${chatId}/messages`, { params, signal });
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
            await queryClient.cancelQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, chatId) });
            const previous = queryClient.getQueriesData({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, chatId) });
            queryClient.setQueriesData({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, chatId) }, (old) =>
                Array.isArray(old) ? old.map((m) => m.id === msgId ? { ...m, content } : m) : old
            );
            return { previous };
        },
        onError: (error, _vars, context) => {
            if (context?.previous) {
                context.previous.forEach(([key, data]) => queryClient.setQueryData(key, data));
            }
            toast.error(error?.message || 'Failed to edit message');
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, variables.chatId) });
            invalidateVaultAggregates(queryClient);
        }
    });
};

export const useDeleteMessage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, msgId }) =>
            api.delete(`/api/v2/chats/${chatId}/messages/${msgId}`),
        onMutate: async ({ chatId, msgId }) => {
            await queryClient.cancelQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, chatId) });
            const previous = queryClient.getQueriesData({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, chatId) });
            queryClient.setQueriesData({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, chatId) }, (old) =>
                Array.isArray(old) ? old.filter((m) => m.id !== msgId) : old
            );
            return { previous };
        },
        onError: (error, _vars, context) => {
            if (context?.previous) {
                context.previous.forEach(([key, data]) => queryClient.setQueryData(key, data));
            }
            toast.error(error?.message || 'Failed to delete message');
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, variables.chatId) });
            invalidateVaultAggregates(queryClient);
            // `exact: true`: the 3-element chat key prefix-matches the
            // system-prompt / jobs / images / branches sub-queries, so a plain
            // invalidation here refetched the whole system-prompt assembly for a
            // delete that only changes the message list.
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHATS, variables.chatId), exact: true });
            invalidateVaultAggregates(queryClient);
        }
    });
};


export const useRollbackChat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, messageId }) =>
            api.post(`/api/v2/chats/${chatId}/rollback`, { message_id: messageId }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, variables.chatId) });
            invalidateVaultAggregates(queryClient);
            // See useDeleteMessage: exact, so the rollback does not drag the
            // system-prompt assembly along with it.
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHATS, variables.chatId), exact: true });
            invalidateVaultAggregates(queryClient);
        }
    });
};

export const useRegenerateReply = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, messageId, directive }) =>
            api.post(`/api/v2/chats/${chatId}/regenerate`, {
                ...(messageId ? { message_id: messageId } : {}),
                ...(directive ? { directive } : {}),
            }),
        onSuccess: (_, variables) => {
            // See useDeleteMessage: a regenerate only changes this chat, and
            // the bare root key would refetch the system-prompt assembly (and
            // every other cached chat's) on every click.
            if (variables?.chatId) {
                queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHATS, variables.chatId), exact: true });
                queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, variables.chatId) });
                invalidateVaultAggregates(queryClient);
            }
        }
    });
};

export const useImpersonateMessage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, hint }) =>
            api.post(`/api/v2/chats/${chatId}/impersonate`, { hint: hint || '' }),
        onSuccess: (_, variables) => {
            if (variables?.chatId) {
                queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, variables.chatId) });
                invalidateVaultAggregates(queryClient);
            }
        },
    });
};

export const usePinMessage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, msgId, pinned }) =>
            api.patch(`/api/v2/chats/${chatId}/messages/${msgId}/pin`, { pinned }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, variables.chatId) });
            invalidateVaultAggregates(queryClient);
        },
    });
};

export const useSwipeMessage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, msgId, direction, index }) =>
            api.post(`/api/v2/chats/${chatId}/messages/${msgId}/swipe`, { direction, index }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, variables.chatId) });
            invalidateVaultAggregates(queryClient);
        },
    });
};

export const useGenerateSwipe = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, msgId, directive }) =>
            api.post(`/api/v2/chats/${chatId}/messages/${msgId}/generate-swipe`, {
                ...(directive ? { directive } : {}),
            }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, variables.chatId) });
            invalidateVaultAggregates(queryClient);
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
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, variables.chatId) });
            invalidateVaultAggregates(queryClient);
        },
    });
};
