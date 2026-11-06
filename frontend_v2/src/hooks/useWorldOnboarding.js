import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { QUERY_KEYS, buildQueryKey } from '../constants/queryKeys';
import { invalidateVaultAggregates, reportError } from './useWorldVaultResource';
import { CHAT_LIST_KEY, CHAT_DETAIL_KEY } from './useChats';

export const useAnalyzeCardOnboarding = () => {
    return useMutation({
        mutationFn: async ({ file, useVision = true }) => {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('use_vision', String(useVision));
            return api.post('/api/v2/world-vault/onboarding/analyze-card', formData);
        },
        onError: (error) => reportError('analyze card onboarding', error),
    });
};

export const useAnalyzeExistingCharacterOnboarding = () => {
    return useMutation({
        mutationFn: ({ characterId, useVision = true }) =>
            api.post(`/api/v2/world-vault/onboarding/analyze-character/${characterId}`, {
                use_vision: useVision,
            }),
        onError: (error) => reportError('analyze existing character onboarding', error),
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
        onError: (error) => reportError('analyze document onboarding', error),
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
        onError: (error) => reportError('crossover preview', error),
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
        onError: (error) => reportError('commit world blueprint', error),
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
        onError: (error) => reportError('commit chat to canon', error),
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
        onError: (error) => reportError('compile chat to story', error),
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
        onError: (error) => reportError('run world tick', error),
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
        onError: (error) => reportError('reverse vision sync', error),
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
        onError: (error) => reportError('fast travel chat', error),
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
        onError: (error) => reportError('visualize inventory item', error),
    });
};

export const useExtractScenarios = () => {
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v2/world-vault/onboarding/extract-scenarios', payload),
        onError: (error) => reportError('extract scenarios', error),
    });
};

export const useExtractVisualTags = () => {
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v2/world-vault/onboarding/extract-visual-tags', payload),
        onError: (error) => reportError('extract visual tags', error),
    });
};

export const useExtractStatekeeper = () => {
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v2/world-vault/onboarding/extract-statekeeper', payload),
        onError: (error) => reportError('extract statekeeper', error),
    });
};

export const useExtractWorldLore = () => {
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v2/world-vault/onboarding/extract-world-lore', payload),
        onError: (error) => reportError('extract world lore', error),
    });
};

export const useEnrichField = () => {
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v2/world-vault/onboarding/enrich-field', payload),
        onError: (error) => reportError('enrich field', error),
    });
};

export const useIngestStoryChained = () => {
    return useMutation({
        mutationFn: (payload) =>
            api.post('/api/v2/world-vault/onboarding/ingest-story-chained', payload),
        onError: (error) => reportError('ingest story chained', error),
    });
};

