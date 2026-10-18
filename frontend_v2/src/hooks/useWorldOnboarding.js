import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { QUERY_KEYS, buildQueryKey } from '../constants/queryKeys';
import { invalidateVaultAggregates } from './useWorldVaultResource';

const CHAT_DETAIL_KEY = (id) => buildQueryKey(QUERY_KEYS.CHATS, 'detail', id);
const CHAT_LIST_KEY = buildQueryKey(QUERY_KEYS.CHATS, 'list');

export const useAnalyzeCardOnboarding = () => {
    return useMutation({
        mutationFn: async ({ file, useVision = true }) => {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('use_vision', String(useVision));
            return api.post('/api/v2/world-vault/onboarding/analyze-card', formData);
        },
    });
};

export const useAnalyzeExistingCharacterOnboarding = () => {
    return useMutation({
        mutationFn: ({ characterId, useVision = true }) =>
            api.post(`/api/v2/world-vault/onboarding/analyze-character/${characterId}`, {
                use_vision: useVision,
            }),
    });
};

export const useAnalyzeDocumentOnboarding = () => {
    return useMutation({
        mutationFn: async ({ file, rawText, title }) => {
            if (file) {
                const formData = new FormData();
                formData.append('file', file);
                if (rawText) formData.append('raw_text', rawText);
                if (title) formData.append('title', title);
                return api.post('/api/v2/world-vault/onboarding/analyze-document', formData);
            }
            return api.post('/api/v2/world-vault/onboarding/analyze-story-text', {
                raw_text: rawText || '',
                title: title || null,
            });
        },
    });
};

export const useCrossoverPreview = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v2/world-vault/onboarding/crossover-preview', payload),
        onSuccess: (data) => {
            if (data?.launched_chat_id) {
                queryClient.invalidateQueries({ queryKey: CHAT_LIST_KEY });
                queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.SCENARIOS) });
                invalidateVaultAggregates(queryClient);
            }
        },
    });
};

export const useCommitWorldBlueprint = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (blueprint) =>
            api.post('/api/v2/world-vault/onboarding/commit', blueprint),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.WORLDS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.LOCATIONS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.SCENARIOS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.LOREBOOKS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.PERSONAS) });
            queryClient.invalidateQueries({ queryKey: CHAT_LIST_KEY });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.STORIES) });
            invalidateVaultAggregates(queryClient);
        },
    });
};

export const useCommitChatToCanon = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (chatId) =>
            api.post(`/api/v2/world-vault/onboarding/commit-canon/${chatId}`),
        onSuccess: (_, chatId) => {
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(chatId) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.WORLDS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.LOREBOOKS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.LOCATIONS) });
            invalidateVaultAggregates(queryClient);
        },
    });
};

export const useCompileChatToStory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, title }) =>
            api.post(`/api/v2/world-vault/onboarding/compile-story/${chatId}`, { title }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.STORIES) });
            invalidateVaultAggregates(queryClient);
        },
    });
};

export const useRunWorldTick = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ worldId, timeAdvanceLabel = '+1 Day', activeChatId = null }) =>
            api.post(`/api/v2/world-vault/onboarding/world-tick/${worldId}`, {
                time_advance_label: timeAdvanceLabel,
                active_chat_id: activeChatId,
            }),
        onSuccess: (_, variables) => {
            if (variables.activeChatId) {
                queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.activeChatId) });
            }
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.WORLDS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            invalidateVaultAggregates(queryClient);
        },
    });
};

export const useReverseVisionSync = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, imagePath = null, imageBase64 = null }) =>
            api.post(`/api/v2/world-vault/onboarding/reverse-vision/${chatId}`, {
                image_path: imagePath,
                image_base64: imageBase64,
            }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
        },
    });
};

export const useFastTravelChat = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, locationId = null, locationName = null, timeOfDay = null }) =>
            api.post(`/api/v2/world-vault/onboarding/fast-travel/${chatId}`, {
                location_id: locationId,
                location_name: locationName,
                time_of_day: timeOfDay,
            }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, variables.chatId) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.LOCATIONS) });
        },
    });
};

export const useVisualizeInventoryItem = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ chatId, itemName, branchId = null }) =>
            api.post(`/api/v2/world-vault/onboarding/visualize-item/${chatId}`, {
                item_name: itemName,
                branch_id: branchId,
            }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: CHAT_DETAIL_KEY(variables.chatId) });
        },
    });
};

export const useExtractScenarios = () => {
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v2/world-vault/onboarding/extract-scenarios', payload),
    });
};

export const useExtractVisualTags = () => {
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v2/world-vault/onboarding/extract-visual-tags', payload),
    });
};

export const useExtractStatekeeper = () => {
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v2/world-vault/onboarding/extract-statekeeper', payload),
    });
};

export const useExtractWorldLore = () => {
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v2/world-vault/onboarding/extract-world-lore', payload),
    });
};

export const useEnrichField = () => {
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v2/world-vault/onboarding/enrich-field', payload),
    });
};

export const useIngestStoryChained = () => {
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v2/world-vault/onboarding/ingest-story-chained', payload),
    });
};

