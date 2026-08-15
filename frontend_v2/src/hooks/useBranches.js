import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export const useBranches = (chatId) => {
    return useQuery({
        queryKey: ['world_vault', 'chats', chatId, 'branches'],
        queryFn: () => api.get(`/api/v2/chats/${chatId}/branches`),
        enabled: !!chatId,
    });
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

export const useAlternates = (chatId, messageId) => {
    return useQuery({
        queryKey: ['world_vault', 'messages', messageId, 'alternates'],
        queryFn: () => api.get(`/api/v2/chats/${chatId}/messages/${messageId}/alternates`),
        enabled: !!chatId && !!messageId,
    });
};
