import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { api } from '../api';
import { useCreateResource, useDeleteResource, invalidateVaultAggregates } from './useWorldVaultResource';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { isActiveJobStatus } from '../utils/jobStatus';

// Chat cache layout:
//   ['world_vault','chats','list',workspace,limit,offset,query,character]  the list
//   ['world_vault','chats',chatId]                         one chat's detail
//   ['world_vault','chats',chatId,'system-prompt'|'jobs'|'images'|'branches']
//
// The list used to hang off the root with no marker of its own, so every
// `invalidateQueries({queryKey: CHAT_LIST_KEY})` — rename, update, send, import,
// create — also refetched the system-prompt assembly of every cached chat.
//
// The list's own key used to be spelled three different ways. See
// `chatListKey` below.
const CHATS_ROOT_KEY = buildQueryKey(QUERY_KEYS.CHATS);
const MESSAGES_ROOT_KEY = buildQueryKey(QUERY_KEYS.MESSAGES);
const CHAT_LIST_KEY = [...CHATS_ROOT_KEY, 'list'];
// `CHAT_DETAIL_KEY('list')` would be byte-identical to CHAT_LIST_KEY, so a
// chat whose id is literally `list` would let a detail write/invalidation
// land on the cached list. That is impossible today: chat ids are
// server-generated uuid4, `CreateChatRequest` whitelists no `id`, and the
// one producer that accepts a client-supplied id (character-card import)
// rejects the marker (backend `validate_imported_chat_id`). Pinned by
// backend tests/test_chat_list_key_collision.py — if the API ever starts
// accepting client-chosen chat ids, guard it there or reshape this key.
const CHAT_DETAIL_KEY = (chatId) => [...CHATS_ROOT_KEY, chatId];

export { CHATS_ROOT_KEY, CHAT_LIST_KEY, CHAT_DETAIL_KEY };

/**
 * The one key factory for every chat-list query.
 *
 * The chat list used to be cached under three different keys: the plain list
 * (`list`, workspace, limit, offset), the sidebar search (`list`, 'search',
 * query), and a bare `list` used by the onboarding hooks. React Query matches
 * a query key by PREFIX, so the bare `list` key was a prefix of both of the
 * others — an invalidation aimed at one of them hit all three, and a stale
 * list could survive an update because the invalidation missed the key the
 * list was actually stored under.
 *
 * Every list query now goes through this factory, and the shapes are
 * distinct enough that a prefix match can only ever mean "all chat lists",
 * which is what an invalidation after a chat was created or deleted wants.
 */
export const chatListKey = ({ workspace, limit, offset, query, character_id } = {}) =>
    buildQueryKey(
        QUERY_KEYS.CHATS,
        'list',
        workspace ?? null,
        limit ?? null,
        offset ?? null,
        query ?? null,
        character_id ?? null
    );

export const useChats = ({ limit = 50, offset = 0, workspace, character_id } = {}) => {
    const params = {};
    if (workspace) params.workspace = workspace;
    if (character_id) params.character_id = character_id;
    if (limit) params.limit = limit;
    if (offset) params.offset = offset;
    return useQuery({
        queryKey: chatListKey({ workspace, limit, offset, character_id }),
        queryFn: ({ signal }) => api.get('/api/v2/chats', { params, signal })
    });
};

/**
 * The chats a character appears in — as the primary character or as one of
 * the additional cast.
 *
 * There was no way to get from a character to its conversations: the chat
 * list had no character filter, so the only route was to read every chat in
 * the vault and look.
 */
export const useChatsByCharacter = (characterId, { limit = 20 } = {}) => {
    return useQuery({
        queryKey: chatListKey({ character_id: characterId, limit }),
        queryFn: ({ signal }) => api.get('/api/v2/chats', {
            params: { character_id: characterId, limit },
            signal,
        }),
        enabled: Boolean(characterId),
    });
};

export const useChat = (chatId) => {
    return useQuery({
        queryKey: CHAT_DETAIL_KEY(chatId),
        queryFn: ({ signal }) => {
            if (!chatId) return null;
            return api.get(`/api/v2/chats/${chatId}`, { signal });
        },
        enabled: !!chatId
    });
};

export const useChatSystemPrompt = (chatId) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.CHATS, chatId, 'system-prompt'),
        queryFn: ({ signal }) => {
            if (!chatId) return null;
            return api.get(`/api/v2/chats/${chatId}/system-prompt`, { signal });
        },
        enabled: !!chatId
    });
};

export const useChatJobs = (chatId) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.CHATS, chatId, 'jobs'),
        queryFn: ({ signal }) => {
            if (!chatId) return [];
            return api.get(`/api/v2/chats/${chatId}/jobs`, { signal });
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
            invalidateVaultAggregates(queryClient);
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
            invalidateVaultAggregates(queryClient);
        }
    });
};

export const useGenerateScene = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId }) => api.post(`/api/v2/chats/${chatId}/scene`, {}),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
            invalidateVaultAggregates(queryClient);
        }
    });
};

export const useSuggestReply = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, draft }) => api.post(`/api/v2/chats/${chatId}/suggest`, { draft }),
        onSuccess: (_, variables) => {
            if (variables?.chatId) {
                queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
            }
        },
    });
};

export const useUpdateChat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, ...data }) => api.patch(`/api/v2/chats/${chatId}`, data),
        onMutate: async (variables) => {
            const { chatId, ...data } = variables;
            // The list is cached per workspace/limit/offset, so the write has to
            // be a prefix update to reach the variant the sidebar is showing.
            // `cancelQueries` first, so no in-flight page response lands on top
            // of the optimistic value.
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
            // sub-queries, which is intended after a chat-level edit.
            queryClient.invalidateQueries({ queryKey: CHAT_LIST_KEY });
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
            invalidateVaultAggregates(queryClient);
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
        // A stable key per send, so a retry (or two tabs) collapses onto ONE
        // server-side execution rather than becoming two user messages and two
        // paid LLM jobs. The server honours it via the request-dedup map, the
        // same opt-in mechanism `POST /api/jobs` uses; without it the client
        // `isPending` guard is the only protection there is, and it covers one
        // tab.
        mutationFn: ({ chatId, message, idempotencyKey }) =>
            api.post(`/api/v2/chats/${chatId}/messages`, message, { idempotencyKey }),
        onMutate: async ({ chatId, message }) => {
            const keyPrefix = [...MESSAGES_ROOT_KEY, chatId];
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
            //
            // Non-array entries are left alone, as in useEditMessage: spreading
            // a non-iterable `old` throws inside the updater and takes the whole
            // mutation (and its rollback) down with it.
            queryClient.setQueriesData({ queryKey: keyPrefix }, (old) =>
                Array.isArray(old) ? [...old, optimisticMessage] : old
            );
            return { previous };
        },
        onError: (error, { chatId }, context) => {
            context?.previous?.forEach(([key, data]) => queryClient.setQueryData(key, data));
            queryClient.invalidateQueries({ queryKey: [...MESSAGES_ROOT_KEY, chatId] });
            toast.error(error?.message || 'Failed to send message');
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: CHAT_LIST_KEY });
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
            queryClient.invalidateQueries({ queryKey: [...MESSAGES_ROOT_KEY, variables.chatId] });
            invalidateVaultAggregates(queryClient);
        }
    });
};

export const useEvaluateChatDirector = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, force_updater = false }) =>
            api.post(`/api/v2/chats/${chatId}/director/evaluate`, { force_updater }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
            queryClient.invalidateQueries({ queryKey: CHAT_LIST_KEY });
            invalidateVaultAggregates(queryClient);
        },
    });
};

export const useUpdateChatStateSnapshot = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, state_snapshot }) =>
            api.patch(`/api/v2/chats/${chatId}/state-snapshot`, { state_snapshot }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
            queryClient.invalidateQueries({ queryKey: CHAT_LIST_KEY });
        },
        // Autosave path: the panel writes on field blur. Without an error
        // handler a failed save was invisible — the next refetch quietly put
        // the old snapshot back and the edit was simply gone.
        onError: (error) => {
            toast.error(`Could not save chat state: ${error?.message || 'request failed'}`);
        },
    });
};

export const useIllustrateChat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, imagePrompt, branchId }) =>
            api.post(`/api/v2/chats/${chatId}/illustrate`, {
                image_prompt: imagePrompt || '',
                // The thread the illustration belongs to. A branch's copies share
                // their originals' `chat_id` and `created_at`, so an image message
                // written without it lands in the original thread and the fork
                // the user is reading never shows it.
                branch_id: branchId || null,
            }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
        }
    });
};

export const useChatImages = (chatId) => {
    return useQuery({
        queryKey: [...CHAT_DETAIL_KEY(chatId), 'images'],
        queryFn: ({ signal }) => api.get(`/api/v2/chats/${chatId}/images`, { signal }),
        enabled: !!chatId
    });
};

/**
 * Minimum characters before the sidebar fires a chat search. The endpoint has
 * no `min_length` of its own, so a one-character query is a real (and
 * unscoped) table scan rather than a 422; every other search in the app has a
 * floor (`useWorldVaultSearch`, `useLocations`).
 */
export const CHAT_SEARCH_MIN_LENGTH = 2;

export const useSearchChats = (query) => {
    return useQuery({
        queryKey: chatListKey({ query }),
        queryFn: ({ signal }) => api.get('/api/v2/chats', { params: { q: query }, signal }),
        enabled: !!query && query.trim().length >= CHAT_SEARCH_MIN_LENGTH,
    });
};

export const useExportChatToStory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (chatId) => api.post(`/api/v2/chats/${chatId}/export-story`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.STORIES) });
            invalidateVaultAggregates(queryClient);
        }
    });
};




