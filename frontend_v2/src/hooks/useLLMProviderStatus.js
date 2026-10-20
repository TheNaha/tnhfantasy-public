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
export const LLM_ROUTING_KEY = ['llm', 'routing'];

/** Fetch all registered LLM providers with is_default flag. */
async function fetchLLMProviders({ signal } = {}) {
    return api.get(`${API_V2_BASE}/llm/providers`, { signal });
}

/** Fetch the rp/util routing table: role -> primary + fallback chain, kind -> role. */
async function fetchLLMRouting({ signal } = {}) {
    return api.get(`${API_V2_BASE}/llm/routing`, { signal });
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
    const isHealthy = enabledProviders.length > 0 && availableModels.length > 0 && !modelsQuery.isError;

    return {
        providers,
        enabledProviders,
        defaultProvider: defaultQuery.data ?? null,
        availableModels,
        isHealthy,
        isLoading: providersQuery.isLoading || modelsQuery.isLoading || defaultQuery.isLoading,
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
        mutationFn: (providerId) => api.post(`${API_V2_BASE}/llm/providers/${providerId}/test`),
    });
}

export const LLM_PROVIDERS_HEALTH_KEY = ['llm', 'providers', 'health'];

/**
 * useProvidersHealth — the aggregate health of every LLM/hybrid provider.
 *
 * `GET /llm/providers/health` runs the real connectivity check against every
 * registered LLM or hybrid provider in parallel and reports how many are up.
 * It was the one worker-health signal the backend computed and nothing in the
 * frontend ever asked for, so the roleplay surface had no way to say "every
 * LLM provider is down" — the user just saw a failed job.
 *
 * The check is a live probe, so it is polled on a slow interval rather than
 * fetched on every render. A 404 means no providers are registered at all,
 * which is a legitimate state (and not an error).
 */
export function useProvidersHealth(options = {}) {
    return useQuery({
        queryKey: LLM_PROVIDERS_HEALTH_KEY,
        queryFn: async ({ signal } = {}) => {
            try {
                return await api.get(`${API_V2_BASE}/llm/providers/health`, { signal });
            } catch (err) {
                if (err?.status === 404 || err?.response?.status === 404) {
                    return { providers: [], healthy_count: 0, total_count: 0 };
                }
                throw err;
            }
        },
        staleTime: 60_000,
        refetchInterval: 120_000,
        retry: 1,
        ...options,
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
            // The providers list carries `is_default` per row, so the old
            // winner keeps its badge while the new winner gets none: the UI
            // reports the new default and marks the old one at the same time.
            queryClient.invalidateQueries({ queryKey: LLM_PROVIDERS_KEY });
            // The routing table is a *description* of how kinds resolve, and a
            // provider change can change which model a role actually reaches:
            // `resolve_model_for_kind` only routes to the registry's primary
            // when a real provider serves it. Without this the panel keeps
            // showing the role's primary as reachable after it stopped being.
            queryClient.invalidateQueries({ queryKey: LLM_ROUTING_KEY });
        },
    });
}


/**
 * useLLMRouting — the rp/util table.
 *
 * Which model serves which *kind* of work, and why. Without it the two-role
 * split is invisible: a user cannot tell why a chat reply comes from one model
 * and a memory extraction from another, nor that editing
 * `modal_llm/models.json` is how it changes.
 */
export function useLLMRouting(options = {}) {
    return useQuery({
        queryKey: LLM_ROUTING_KEY,
        queryFn: fetchLLMRouting,
        staleTime: 60_000,
        ...options,
    });
}

export const LLM_CATALOG_KEY = ['llm', 'catalog'];

/** Fetch the full model catalog with active selections. */
async function fetchLLMCatalog({ signal } = {}) {
    return api.get(`${API_V2_BASE}/llm/catalog`, { signal });
}

export function useLLMCatalog(options = {}) {
    return useQuery({
        queryKey: LLM_CATALOG_KEY,
        queryFn: fetchLLMCatalog,
        staleTime: 60_000,
        ...options,
    });
}

/** Set the active models (rp, util, decisions, image) in backend. */
export function useSetActiveModels() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ active_rp, active_util, active_decisions, active_image }) =>
            api.put(`${API_V2_BASE}/llm/catalog/active`, { active_rp, active_util, active_decisions, active_image }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: LLM_CATALOG_KEY });
            queryClient.invalidateQueries({ queryKey: LLM_ROUTING_KEY });
        },
    });
}

/** Live playground evaluation of the System 1 Director (13 parallel typed questions). */
export function useEvaluateDirectorDecisions() {
    return useMutation({
        mutationFn: (payload) => api.post(`${API_V2_BASE}/llm/decisions/evaluate`, payload),
    });
}

export const LLM_RUNTIME_DEFAULTS_KEY = ['llm', 'runtime-defaults'];

export const LLM_DIRECTOR_GATES_KEY = ['llm', 'director', 'gates'];

/**
 * Canonical Director gate registry from the backend.
 *
 * The 16-Gate Studio used to keep its own list, and four keys had already
 * drifted to aliases the Director never emits. Server data replaces it; the
 * static copy in the page remains only as an offline fallback.
 */
export function useLLMDirectorGates(options = {}) {
    return useQuery({
        queryKey: LLM_DIRECTOR_GATES_KEY,
        queryFn: ({ signal } = {}) => api.get(`${API_V2_BASE}/llm/director/gates`, { signal }),
        staleTime: 60_000,
        ...options,
    });
}

/** Fetch resolved runtime defaults (context budget, max output tokens, temp, top_p, director_mode, gate/image thresholds). */
export function useLLMRuntimeDefaults(options = {}) {
    return useQuery({
        queryKey: LLM_RUNTIME_DEFAULTS_KEY,
        queryFn: async ({ signal } = {}) => {
            try {
                return await api.get(`${API_V2_BASE}/llm/runtime-defaults`, { signal });
            } catch {
                return {
                    context_tokens: 4096,
                    max_output_tokens: 2048,
                    temperature: 1.0,
                    top_p: 1.0,
                    frequency_penalty: 0.0,
                    presence_penalty: 0.0,
                    director_mode: 'steered',
                    gate_threshold: 0.6,
                    image_threshold: 0.65,
                };
            }
        },
        staleTime: 60_000,
        ...options,
    });
}
