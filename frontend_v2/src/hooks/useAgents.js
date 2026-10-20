import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, getApiUrl } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { useCreateResource, useUpdateResource, useDeleteResource } from './useWorldVaultResource';
import toast from 'react-hot-toast';

const AGENTS_LIST_KEY = (includeDisabled) => buildQueryKey(QUERY_KEYS.AGENTS, includeDisabled ? 'all' : 'active');
const AGENT_DETAIL_KEY = (id) => buildQueryKey(QUERY_KEYS.AGENTS, id);
const AGENT_VARIANTS_KEY = (agentId) => buildQueryKey(QUERY_KEYS.AGENTS, agentId, 'variants');
const AGENTS_WITH_VARIANTS_KEY = buildQueryKey(QUERY_KEYS.AGENTS, 'with-variants');

export function useAgents({ include_disabled = true } = {}) {
    return useQuery({
        queryKey: AGENTS_LIST_KEY(include_disabled),
        queryFn: ({ signal }) =>
            api.get('/api/v2/agents', {
                params: { include_disabled },
                signal,
            }),
    });
}

/**
 * useAgentsWithVariants — every agent profile together with its variants.
 *
 * The Agent tab used to load the agent list and then fetch the variants of
 * each agent separately, which is one request per agent. The backend serves
 * the whole thing in one response, and it also resolves which variant is
 * active for each agent — which the separate calls did not.
 */
export function useAgentsWithVariants(options = {}) {
    return useQuery({
        queryKey: AGENTS_WITH_VARIANTS_KEY,
        queryFn: ({ signal }) => api.get('/api/v2/llm/agents/with-variants', { signal }),
        ...options,
    });
}

export function useAgent(id) {
    return useQuery({
        queryKey: AGENT_DETAIL_KEY(id),
        queryFn: ({ signal }) => api.get(`/api/v2/agents/${id}`, { signal }),
        enabled: Boolean(id),
    });
}

export function useCreateAgent() {
    return useCreateResource({
        basePath: '/api/v2/agents',
        listQueryKey: buildQueryKey(QUERY_KEYS.AGENTS),
        entityName: 'agent',
    });
}

export function useUpdateAgent() {
    return useUpdateResource({
        basePath: '/api/v2/agents',
        listQueryKey: buildQueryKey(QUERY_KEYS.AGENTS),
        detailQueryKey: AGENT_DETAIL_KEY,
        entityName: 'agent',
    });
}

export function useDeleteAgent() {
    return useDeleteResource({
        basePath: '/api/v2/agents',
        listQueryKey: buildQueryKey(QUERY_KEYS.AGENTS),
        entityName: 'agent',
    });
}

export function useSimulateWorkflow() {
    return useMutation({
        mutationFn: (payload) => api.post('/api/v2/agents/simulate', payload),
        onError: (err) => {
            const detail = err?.message || 'Simulation failed';
            toast.error(`Workflow simulation error: ${detail}`);
        },
    });
}

/**
 * The URL an agent's avatar is served from.
 *
 * The backend stores the path and serves it; the frontend asks for it by id,
 * the same way characters do.
 */
export const getAgentAvatarUrl = (agentId) =>
    agentId ? `${getApiUrl()}/api/v2/agents/${agentId}/avatar` : null;

export function useUploadAgentAvatar() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ agentId, file }) => {
            const formData = new FormData();
            formData.append('file', file);
            return api.post(`/api/v2/agents/${agentId}/avatar`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
        },
        onSuccess: (_data, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.AGENTS, variables.agentId) });
            queryClient.invalidateQueries({ queryKey: AGENTS_WITH_VARIANTS_KEY });
        },
    });
}

export function useAgentVariants(agentId, options = {}) {
    return useQuery({
        queryKey: AGENT_VARIANTS_KEY(agentId),
        queryFn: ({ signal }) => api.get(`/api/v2/agents/${agentId}/variants`, { signal }),
        enabled: Boolean(agentId),
        ...options,
    });
}

function variantError(action, err) {
    toast.error(`Failed to ${action} prompt variant: ${err?.message || 'Unknown error'}`);
}

export function useCreateAgentVariant() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ agentId, ...data }) => api.post(`/api/v2/agents/${agentId}/variants`, data),
        onSuccess: (_data, variables) => {
            queryClient.invalidateQueries({ queryKey: AGENT_VARIANTS_KEY(variables.agentId) });
            queryClient.invalidateQueries({ queryKey: AGENTS_WITH_VARIANTS_KEY });
        },
        onError: (err) => variantError('create', err),
    });
}

export function useUpdateAgentVariant() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ agentId, variantId, ...data }) =>
            api.put(`/api/v2/agents/${agentId}/variants/${variantId}`, data),
        onSuccess: (_data, variables) => {
            queryClient.invalidateQueries({ queryKey: AGENT_VARIANTS_KEY(variables.agentId) });
            queryClient.invalidateQueries({ queryKey: AGENTS_WITH_VARIANTS_KEY });
        },
        onError: (err) => variantError('update', err),
    });
}

export function useDeleteAgentVariant() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ agentId, variantId }) =>
            api.delete(`/api/v2/agents/${agentId}/variants/${variantId}`),
        onSuccess: (_data, variables) => {
            queryClient.invalidateQueries({ queryKey: AGENT_VARIANTS_KEY(variables.agentId) });
            queryClient.invalidateQueries({ queryKey: AGENTS_WITH_VARIANTS_KEY });
        },
        onError: (err) => variantError('delete', err),
    });
}

export function useActivateAgentVariant() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ agentId, variantId }) =>
            api.post(`/api/v2/agents/${agentId}/variants/${variantId}/activate`),
        onSuccess: (_data, variables) => {
            queryClient.invalidateQueries({ queryKey: AGENT_VARIANTS_KEY(variables.agentId) });
            queryClient.invalidateQueries({ queryKey: AGENTS_WITH_VARIANTS_KEY });
        },
        onError: (err) => variantError('activate', err),
    });
}
