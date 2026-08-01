import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';

const getApiUrl = () => {
    return import.meta.env.VITE_API_URL || '';
};

// ============================================================================
// QUERIES
// ============================================================================

export const useCharacters = () => {
    return useQuery({
        queryKey: ['world_vault', 'characters'],
        queryFn: async () => {
            const res = await axios.get(`${getApiUrl()}/api/v2/characters`);
            return res.data;
        }
    });
};

export const useChats = () => {
    return useQuery({
        queryKey: ['world_vault', 'chats'],
        queryFn: async () => {
            const res = await axios.get(`${getApiUrl()}/api/v2/chats`);
            return res.data;
        }
    });
};

export const useMessages = (chatId) => {
    return useQuery({
        queryKey: ['world_vault', 'messages', chatId],
        queryFn: async () => {
            if (!chatId) return [];
            const res = await axios.get(`${getApiUrl()}/api/v2/chats/${chatId}/messages`);
            return res.data;
        },
        enabled: !!chatId
    });
};

export const useLorebooks = () => {
    return useQuery({
        queryKey: ['world_vault', 'lorebooks'],
        queryFn: async () => {
            const res = await axios.get(`${getApiUrl()}/api/v2/lorebooks`);
            return res.data;
        }
    });
};

export const useScenarios = () => {
    return useQuery({
        queryKey: ['world_vault', 'scenarios'],
        queryFn: async () => {
            const res = await axios.get(`${getApiUrl()}/api/v2/scenarios`);
            return res.data;
        }
    });
};

// ============================================================================
// MUTATIONS
// ============================================================================

export const useCreateChat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (chatData) => {
            const res = await axios.post(`${getApiUrl()}/api/v2/chats`, chatData);
            return res.data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats'] });
        }
    });
};

export const useSendMessage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ chatId, message }) => {
            const res = await axios.post(`${getApiUrl()}/api/v2/chats/${chatId}/messages`, message);
            return res.data;
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', variables.chatId] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats'] });
        }
    });
};
