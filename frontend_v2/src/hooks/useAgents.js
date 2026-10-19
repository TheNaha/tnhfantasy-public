import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { useCreateResource, useUpdateResource, useDeleteResource } from './useWorldVaultResource';
import toast from 'react-hot-toast';

const AGENTS_LIST_KEY = (includeDisabled) => buildQueryKey(QUERY_KEYS.AGENTS, includeDisabled ? 'all' : 'active');
const AGENT_DETAIL_KEY = (id) => buildQueryKey(QUERY_KEYS.AGENTS, id);
const AGENT_VARIANTS_KEY = (agentId) => buildQueryKey(QUERY_KEYS.AGENTS, agentId, 'variants');

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

export function useAgentVariants(agentId) {
    return useQuery({
        queryKey: AGENT_VARIANTS_KEY(agentId),
        queryFn: ({ signal }) => api.get(`/api/v2/agents/${agentId}/variants`, { signal }),
        enabled: Boolean(agentId),
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
        },
        onError: (err) => variantError('activate', err),
    });
}
