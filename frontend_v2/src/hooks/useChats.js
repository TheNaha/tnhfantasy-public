import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { useCreateResource, useDeleteResource } from './useWorldVaultResource';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { isActiveJobStatus } from '../utils/jobStatus';

const CHAT_LIST_KEY = ['world_vault', 'chats'];
const CHAT_DETAIL_KEY = (chatId) => ['world_vault', 'chats', chatId];

export const useChats = ({ limit = 50, offset = 0, workspace } = {}) => {
    const params = {};
    if (workspace) params.workspace = workspace;
    if (limit) params.limit = limit;
    if (offset) params.offset = offset;
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.CHATS, workspace, limit, offset),
        queryFn: () => api.get('/api/v2/chats', { params })
    });
};

export const useChat = (chatId) => {
    return useQuery({
        queryKey: CHAT_DETAIL_KEY(chatId),
        queryFn: () => {
            if (!chatId) return null;
            return api.get(`/api/v2/chats/${chatId}`);
        },
        enabled: !!chatId
    });
};

export const useChatSystemPrompt = (chatId) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.CHATS, chatId, 'system-prompt'),
        queryFn: () => {
            if (!chatId) return null;
            return api.get(`/api/v2/chats/${chatId}/system-prompt`);
        },
        enabled: !!chatId
    });
};

export const useChatJobs = (chatId) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.CHATS, chatId, 'jobs'),
        queryFn: () => {
            if (!chatId) return [];
            return api.get(`/api/v2/chats/${chatId}/jobs`);
        },
        enabled: !!chatId,
        refetchInterval: (query) => {
            const jobs = query.state.data;
            // Previously this used a local snake_case list
            // ('sent_to_provider', 'pre_generation', 'post_processing') while
            // the API emits the hyphenated enum values, so polling stopped the
            // moment a worker picked the job up.
            if (Array.isArray(jobs) && jobs.some(j => isActiveJobStatus(j.status))) return 5000;
            // Stop polling entirely when the queue is empty. The previous
            // unconditional 30000 meant every open chat issued a permanent
            // 30s request forever, on top of the jobs watchdog and the
            // per-job 2s poll. QueueVisualization.jsx already returned false
            // when idle.
            return false;
        },
        refetchIntervalInBackground: false
    });
};

export const useCreateChat = () => useCreateResource({
    basePath: '/api/v2/chats',
    listQueryKey: CHAT_LIST_KEY,
});

export function useExportChatJsonl() {
    return useMutation({
        mutationFn: async ({ chatId, chatName }) => {
            const resp = await api.get(`/api/v2/chats/${chatId}/export`, { params: { format: 'jsonl' } });
            const blob = await resp.blob();
            const safeName = (chatName || 'chat').replace(/[^a-zA-Z0-9-_ ]/g, '').trim().replace(/\s+/g, '_') || chatId;
            return { blob, filename: `${safeName}.jsonl` };
        },
    });
}

export function useImportChat() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (formData) => api.post('/api/v2/chats/import', formData),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: CHAT_LIST_KEY });
        },
    });
}

export const useRenameChat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, name }) => api.patch(`/api/v2/chats/${chatId}`, { name }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: CHAT_LIST_KEY });
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
        }
    });
};

export const useGenerateScene = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId }) => api.post(`/api/v2/chats/${chatId}/scene`, {}),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
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
            // The list is cached under `buildQueryKey(QUERY_KEYS.CHATS, workspace,
            // limit, offset)` — a 5-element key. Reading and writing the bare
            // 2-element prefix always returned `undefined`, so the optimistic
            // rename never appeared in the sidebar and the `onError` rollback
            // below was dead code. `get/setQueriesData` matches by prefix, so it
            // covers every workspace/limit/offset variant at once.
            //
            // Two consequences of the prefix also matching the chat *detail*
            // query: the updater must leave non-array entries alone (calling
            // `.map` on the detail object threw and failed the whole mutation),
            // and the snapshot has to be taken *before* the detail is patched or
            // the rollback would restore the already-optimistic value.
            await queryClient.cancelQueries({ queryKey: CHAT_LIST_KEY });
            const previousChats = queryClient.getQueriesData({ queryKey: CHAT_LIST_KEY });

            await queryClient.cancelQueries({ queryKey: CHAT_DETAIL_KEY(chatId) });
            const previousChat = queryClient.getQueryData(CHAT_DETAIL_KEY(chatId));

            if (previousChat) {
                queryClient.setQueryData(CHAT_DETAIL_KEY(chatId), {
                    ...previousChat,
                    ...data
                });
            }

            if (previousChats.length > 0) {
                queryClient.setQueriesData({ queryKey: CHAT_LIST_KEY }, (cached) =>
                    Array.isArray(cached)
                        ? cached.map(c => c.id === chatId ? { ...c, ...data } : c)
                        : cached
                );
            }

            return { previousChat, previousChats };
        },
        onError: (err, variables, context) => {
            if (context?.previousChat) {
                queryClient.setQueryData(CHAT_DETAIL_KEY(variables.chatId), context.previousChat);
            }
            // Only the list-shaped entries; the detail entry is restored above.
            context?.previousChats?.forEach(([key, value]) => {
                if (Array.isArray(value)) {
                    queryClient.setQueryData(key, value);
                }
            });
        },
        onSettled: (data, error, variables) => {
            // The list prefix-matches every cached list variant; the detail key
            // prefix-matches the detail query and its system-prompt/jobs/images
            // sub-queries, which is intended. A second identical call with an
            // explicit `exact: false` was a no-op duplicate.
            queryClient.invalidateQueries({ queryKey: CHAT_LIST_KEY });
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
        }
    });
};

export const useDeleteChat = () => useDeleteResource({
    basePath: '/api/v2/chats',
    listQueryKey: CHAT_LIST_KEY,
});

export const useSendMessage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, message }) => api.post(`/api/v2/chats/${chatId}/messages`, message),
        onMutate: async ({ chatId, message }) => {
            const keyPrefix = ['world_vault', 'messages', chatId];
            await queryClient.cancelQueries({ queryKey: keyPrefix });
            const previous = queryClient.getQueriesData({ queryKey: keyPrefix });
            const optimisticMessage = {
                id: `temp-${crypto.randomUUID()}`,
                role: message.role,
                content: message.content,
                chat_id: chatId,
                created_at: new Date().toISOString(),
                optimistic: true,
            };
            // Prefix update is what actually reaches the components: every page
            // of messages lives under a longer key
            // ([...,'messages',chatId,limit,offset,branch,search,tail]).
            // A parallel exact-key write here was dead — getQueryData on the
            // 3-element prefix never matched a real cache entry, so it created
            // an orphan entry and the onError rollback branch that read it back
            // could never run.
            queryClient.setQueriesData({ queryKey: keyPrefix }, (old) => [
                ...(old || []),
                optimisticMessage,
            ]);
            return { previous };
        },
        onError: (_, { chatId }, context) => {
            context?.previous?.forEach(([key, data]) => queryClient.setQueryData(key, data));
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', chatId] });
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: CHAT_LIST_KEY });
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
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
        }
    });
};

export const useChatImages = (chatId) => {
    return useQuery({
        queryKey: ['world_vault', 'chats', chatId, 'images'],
        queryFn: () => api.get(`/api/v2/chats/${chatId}/images`),
        enabled: !!chatId
    });
};

export const useSearchChats = (query) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.CHATS, 'search', query),
        queryFn: () => api.get('/api/v2/chats', { params: { q: query } }),
        enabled: !!query && query.trim().length > 0,
    });
};


