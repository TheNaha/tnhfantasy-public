/**
 * useLLMRouting — the rp/util table.
 *
 * The two-role split exists because an rp model is chosen for prose and a util
 * model for structure, and neither does the other's job. These tests pin that
 * the split is *visible*: a user cannot fix a routing problem they cannot see.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { api, API_V2_BASE } from '../api';
import { LLM_ROUTING_KEY, useLLMRouting } from './useLLMProviderStatus';

vi.mock('../api', () => ({
    api: { get: vi.fn(), put: vi.fn() },
    API_V2_BASE: '/api/v2',
}));

const ROUTING = {
    roles: {
        rp: { primary: 'artemis_31b', chain: ['artemis_31b', 'writers_31b_v2', 'magnum_diamond_24b'] },
        util: { primary: 'gemma4_31b_heretic_util', chain: ['gemma4_31b_heretic_util', 'mistral_small_32_it'] },
    },
    kinds: { chat_reply: 'rp', narrator: 'rp', memory_extraction: 'util', story_parse: 'util' },
    default_role: 'rp',
};

function wrapper({ children }) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('useLLMRouting', () => {
    beforeEach(() => vi.clearAllMocks());

    it('fetches the routing table from /llm/routing', async () => {
        api.get.mockResolvedValue(ROUTING);
        const { result } = renderHook(() => useLLMRouting(), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));
        expect(api.get).toHaveBeenCalledWith('/api/v2/llm/routing', expect.anything());
        expect(result.current.data.roles.rp.primary).toBe('artemis_31b');
    });

    it('exposes both roles with a primary each', async () => {
        api.get.mockResolvedValue(ROUTING);
        const { result } = renderHook(() => useLLMRouting(), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));
        expect(Object.keys(result.current.data.roles)).toEqual(['rp', 'util']);
        expect(result.current.data.roles.rp.chain).toHaveLength(3);
        expect(result.current.data.roles.util.chain[0]).toBe(result.current.data.roles.util.primary);
    });

    it('is query-keyed so a provider change can refresh it', () => {
        expect(LLM_ROUTING_KEY).toEqual(['llm', 'routing']);
    });
});
