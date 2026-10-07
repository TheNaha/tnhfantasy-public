/**
 * useLLMProviderStatus — unified hook for LLM worker health and model availability.
 *
 * Queries /api/v2/llm/providers and /api/v2/llm/available-models.
 * Exposes health state, provider list, and available models in one place.
 * Used by Settings AI tab and Providers page detail panel.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, API_V2_BASE } from '../api';

export const LLM_PROVIDERS_KEY = ['llm', 'providers'];
export const LLM_MODELS_KEY = ['llm', 'available-models'];
export const LLM_DEFAULT_KEY = ['llm', 'default-provider'];

/** Fetch all registered LLM providers with is_default flag. */
async function fetchLLMProviders({ signal } = {}) {
    return api.get(`${API_V2_BASE}/llm/providers`, { signal });
}

/** Fetch available models from the default LLM provider's worker. */
async function fetchLLMModels({ signal } = {}) {
    return api.get(`${API_V2_BASE}/llm/available-models`, { signal });
}

/** Fetch the current default provider config. */
async function fetchLLMDefault({ signal } = {}) {
    try {
        return await api.get(`${API_V2_BASE}/llm/default-provider`, { signal });
    } catch (err) {
        // 404 means no LLM providers registered — not a hard error
        if (err?.status === 404 || err?.response?.status === 404) return null;
        throw err;
    }
}

/**
 * Returns comprehensive LLM worker status:
 *  - providers: array of { provider_id, provider_type, enabled, is_default }
 *  - defaultProvider: { provider_id, model_id } | null
 *  - availableModels: array of { id, name }
 *  - isHealthy: boolean — true when at least one enabled LLM provider exists AND models resolved
 *  - isLoading: boolean
 *  - error: Error | null
 */
export function useLLMProviderStatus() {
    const providersQuery = useQuery({
        queryKey: LLM_PROVIDERS_KEY,
        queryFn: fetchLLMProviders,
        staleTime: 30_000,
        retry: 1,
    });

    const modelsQuery = useQuery({
        queryKey: LLM_MODELS_KEY,
        queryFn: fetchLLMModels,
        staleTime: 60_000,
        retry: 1,
        // Don't fetch models if there are no providers
        enabled: Array.isArray(providersQuery.data) && providersQuery.data.length > 0,
    });

    const defaultQuery = useQuery({
        queryKey: LLM_DEFAULT_KEY,
        queryFn: fetchLLMDefault,
        staleTime: 30_000,
        retry: 0,
    });

    const providers = providersQuery.data ?? [];
    const enabledProviders = providers.filter(p => p.enabled);
    const availableModels = modelsQuery.data ?? [];
    const isHealthy = enabledProviders.length > 0 && !modelsQuery.isError;

    return {
        providers,
        enabledProviders,
        defaultProvider: defaultQuery.data ?? null,
        availableModels,
        isHealthy,
        isLoading: providersQuery.isLoading || defaultQuery.isLoading,
        isModelsLoading: modelsQuery.isLoading || modelsQuery.isFetching,
        error: providersQuery.error ?? modelsQuery.error ?? null,
    };
}

export const LLM_METADATA_STALE_TIME = 60_000;

/**
 * Convenience hook: current default LLM provider config ({provider_id, model_id} | null).
 */
export function useLLMDefaultProvider() {
    return useQuery({
        queryKey: LLM_DEFAULT_KEY,
        queryFn: fetchLLMDefault,
        staleTime: LLM_METADATA_STALE_TIME,
    });
}

/**
 * Convenience hook: models available on the default LLM provider's worker.
 */
export function useLLMAvailableModels() {
    return useQuery({
        queryKey: LLM_MODELS_KEY,
        queryFn: fetchLLMModels,
        staleTime: LLM_METADATA_STALE_TIME,
    });
}

/**
 * Test connectivity to a specific LLM provider.
 * Calls POST /api/v2/llm/providers/{providerId}/test
 * Returns { healthy, models, error, worker_url }
 */
export function useLLMProviderTest() {
    return useMutation({
        mutationFn: (providerId) => api.post(`/api/v2/llm/providers/${providerId}/test`),
    });
}

/**
 * Set the default LLM provider and model.
 */
export function useSetLLMDefault() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ provider_id, model_id }) =>
            api.put(`${API_V2_BASE}/llm/default-provider`, { provider_id, model_id }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: LLM_DEFAULT_KEY });
            queryClient.invalidateQueries({ queryKey: LLM_MODELS_KEY });
        },
    });
}


