import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

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
        queryKey: ['world_vault', 'chats', chatId, 'branches'],
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
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', variables.chatId, 'branches'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', variables.chatId] });
        }
    });
};
