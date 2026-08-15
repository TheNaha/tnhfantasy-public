import React from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
}));

const api404 = Object.assign(new Error('not found'), { status: 404 });

vi.mock('../api', () => ({
    api: apiMock,
}));

import {
    useLLMProviderStatus,
    useLLMDefaultProvider,
    useLLMAvailableModels,
    useLLMProviderTest,
    useSetLLMDefault,
    LLM_PROVIDERS_KEY,
    LLM_MODELS_KEY,
    LLM_DEFAULT_KEY,
} from './useLLMProviderStatus';

function createWrapper() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return {
        wrapper: ({ children }) =>
            React.createElement(QueryClientProvider, { client: queryClient }, children),
        queryClient,
    };
}

const PROVIDERS = [{ provider_id: 'llm-local', provider_type: 'llm-local', enabled: true, is_default: true }];
const MODELS = [{ id: 'model-a', name: 'Model A' }];

describe('useLLMProviderStatus', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
        apiMock.get.mockImplementation((url) => {
            if (url === '/api/v2/llm/providers') return Promise.resolve(PROVIDERS);
            if (url === '/api/v2/llm/available-models') return Promise.resolve(MODELS);
            if (url === '/api/v2/llm/default-provider') return Promise.resolve({ provider_id: 'llm-local', model_id: 'model-a' });
            return Promise.reject(new Error(`unexpected url ${url}`));
        });
    });

    afterEach(() => cleanup());

    it('reports healthy when an enabled provider exists and models resolve', async () => {
        const { wrapper, queryClient } = createWrapper();
        const { result } = renderHook(() => useLLMProviderStatus(), { wrapper });
        await waitFor(() => expect(result.current.isLoading).toBe(false));
        expect(result.current.providers).toEqual(PROVIDERS);
        expect(result.current.enabledProviders).toEqual(PROVIDERS);
        expect(result.current.availableModels).toEqual(MODELS);
        expect(result.current.defaultProvider).toEqual({ provider_id: 'llm-local', model_id: 'model-a' });
        expect(result.current.isHealthy).toBe(true);
        expect(queryClient.getQueryData(LLM_PROVIDERS_KEY)).toEqual(PROVIDERS);
    });

    it('skips the models query when there are no providers', async () => {
        apiMock.get.mockImplementation((url) => {
            if (url === '/api/v2/llm/providers') return Promise.resolve([]);
            if (url === '/api/v2/llm/default-provider') return Promise.resolve(null);
            return Promise.reject(new Error(`unexpected url ${url}`));
        });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useLLMProviderStatus(), { wrapper });
        await waitFor(() => expect(result.current.providers).toEqual([]));
        expect(apiMock.get).not.toHaveBeenCalledWith('/api/v2/llm/available-models');
        expect(result.current.enabledProviders).toEqual([]);
        expect(result.current.isHealthy).toBe(false);
    });

    it('treats a 404 on default-provider as no default (not an error)', async () => {
        apiMock.get.mockImplementation((url) => {
            if (url === '/api/v2/llm/providers') return Promise.resolve(PROVIDERS);
            if (url === '/api/v2/llm/available-models') return Promise.resolve(MODELS);
            if (url === '/api/v2/llm/default-provider') return Promise.reject(api404);
            return Promise.reject(new Error(`unexpected url ${url}`));
        });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useLLMProviderStatus(), { wrapper });
        await waitFor(() => expect(result.current.isLoading).toBe(false));
        expect(result.current.defaultProvider).toBeNull();
        expect(result.current.error).toBeNull();
    });

    it('exposes query errors through the error field', async () => {
        apiMock.get.mockImplementation((url) => {
            if (url === '/api/v2/llm/providers') return Promise.reject(new Error('boom'));
            if (url === '/api/v2/llm/default-provider') return Promise.resolve(null);
            return Promise.reject(new Error(`unexpected url ${url}`));
        });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useLLMProviderStatus(), { wrapper });
        await waitFor(() => expect(result.current.error?.message).toBe('boom'), { timeout: 5000 });
        expect(result.current.isHealthy).toBe(false);
    });

    it('useLLMDefaultProvider fetches the default config on its own key', async () => {
        const { wrapper, queryClient } = createWrapper();
        const { result } = renderHook(() => useLLMDefaultProvider(), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual({ provider_id: 'llm-local', model_id: 'model-a' }));
        expect(queryClient.getQueryData(LLM_DEFAULT_KEY)).toEqual({ provider_id: 'llm-local', model_id: 'model-a' });
    });

    it('useLLMAvailableModels fetches models on its own key', async () => {
        const { wrapper, queryClient } = createWrapper();
        const { result } = renderHook(() => useLLMAvailableModels(), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual(MODELS));
        expect(queryClient.getQueryData(LLM_MODELS_KEY)).toEqual(MODELS);
    });
});

describe('useLLMProviderStatus mutations', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('useLLMProviderTest POSTs to the test endpoint', async () => {
        apiMock.post.mockResolvedValue({ healthy: true, models: [] });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useLLMProviderTest(), { wrapper });
        await act(async () => result.current.mutateAsync('llm-local'));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/llm/providers/llm-local/test');
    });

    it('useSetLLMDefault PUTs the selection and invalidates default + models keys', async () => {
        apiMock.put.mockResolvedValue({ ok: true });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useSetLLMDefault(), { wrapper });
        await act(async () => result.current.mutateAsync({ provider_id: 'llm-local', model_id: 'model-a' }));
        expect(apiMock.put).toHaveBeenCalledWith('/api/v2/llm/default-provider', {
            provider_id: 'llm-local',
            model_id: 'model-a',
        });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: LLM_DEFAULT_KEY });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: LLM_MODELS_KEY });
    });
});