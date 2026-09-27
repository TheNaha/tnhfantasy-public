import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';

/**
 * @param {string} chatId
 * @param {string|null} [activeBranch] - the branch the workspace is currently
 *   showing. Callers on a normal `/chat/:id` entry pass nothing, so the hook
 *   falls back to the original thread: `GET /branches` groups messages in
 *   `created_at` order, so the first row holds the oldest message. This
 *   parameter used to be accepted and dropped, which left callers comparing
 *   every branch row against `undefined` and showing none as active.
 * @returns the query result plus `activeBranchId`, resolved for the caller.
 */
export const useBranches = (chatId, activeBranch = null) => {
    const query = useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.CHATS, chatId, 'branches'),
        queryFn: () => api.get(`/api/v2/chats/${chatId}/branches`),
        enabled: !!chatId,
    });

    const activeBranchId = activeBranch
        || (Array.isArray(query.data) ? query.data[0]?.branch_id ?? null : null);

    return { ...query, activeBranchId };
};

export const useCreateBranch = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, messageId }) =>
            api.post(`/api/v2/chats/${chatId}/branches`, { message_id: messageId }),
        onSuccess: (_, variables) => {
            // Branches only: the second call, on the chat prefix, refetched the
            // whole system-prompt assembly (character + lorebook + world state +
            // last N messages) for a branch insert that changes none of it.
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHATS, variables.chatId, 'branches') });
        }
    });
};
