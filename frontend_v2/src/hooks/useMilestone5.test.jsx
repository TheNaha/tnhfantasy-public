import React from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const websocketMock = vi.hoisted(() => {
    const handlers = new Map();

    const addHandler = (event, callback) => {
        if (!handlers.has(event)) {
            handlers.set(event, new Set());
        }
        handlers.get(event).add(callback);
        return () => handlers.get(event)?.delete(callback);
    };

    return {
        handlers,
        connect: vi.fn().mockResolvedValue(undefined),
        subscribe: vi.fn().mockResolvedValue(undefined),
        unsubscribe: vi.fn(),
        on: vi.fn((event, callback) => addHandler(event, callback)),
        emit(event, payload) {
            for (const callback of handlers.get(event) || []) {
                callback(payload);
            }
        },
        disconnect: vi.fn(),
        getConnectionStatus: vi.fn().mockReturnValue(true),
    };
});

vi.mock('../api/websocket', () => ({
    ...websocketMock,
    EventTypes: {
        JOB_CREATED: 'job.created',
        JOB_UPDATED: 'job.updated',
        JOB_PROGRESS: 'job.progress',
        JOB_POST_PROCESSING: 'job.post_processing',
        JOB_COMPLETED: 'job.completed',
        JOB_FAILED: 'job.failed',
        JOB_CANCELLED: 'job.cancelled',
    },
}));

vi.mock('../api/collectionsApi', () => {
    const mock = {
        listCollections: vi.fn().mockResolvedValue({ collections: [] }),
        getCollection: vi.fn(),
        createCollection: vi.fn(),
        deleteCollection: vi.fn(),
        updateCollection: vi.fn(),
        addImagesToCollection: vi.fn(),
        removeImagesFromCollection: vi.fn(),
        importCollections: vi.fn(),
    };
    return {
        default: mock,
        ...mock
    };
});

vi.mock('../api/promptsApi', () => {
    const mock = {
        listPrompts: vi.fn().mockResolvedValue({ prompts: [] }),
        getCategories: vi.fn().mockResolvedValue({ categories: [] }),
        createPrompt: vi.fn(),
        updatePrompt: vi.fn(),
        deletePrompt: vi.fn(),
        incrementUsage: vi.fn(),
        importPrompts: vi.fn(),
    };
    return {
        default: mock,
        ...mock
    };
});

vi.mock('../api', () => ({
    jobsApi: {
        getActive: vi.fn().mockResolvedValue({ jobs: [] }),
        get: vi.fn(),
    },
}));

import { useCollections, useCollectionImages } from './useCollections';
import { usePrompts, usePromptCategories } from './usePrompts';
import { useActiveJobs } from './useActiveJobs';
import { useTrackJob } from './useTrackJob';
import { useJobsRealtime } from './useJobsRealtime';
import collectionsApi from '../api/collectionsApi';
import promptsApi from '../api/promptsApi';
import { jobsApi } from '../api';

function createWrapper(queryClient) {
    return function Wrapper({ children }) {
        return React.createElement(
            QueryClientProvider,
            { client: queryClient },
            children,
        );
    };
}

describe('Milestone 5 React Query Hooks', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        cleanup();
        websocketMock.handlers.clear();
    });

    afterEach(() => {
        cleanup();
    });

    it('useCollections formats list collections into map', async () => {
        collectionsApi.listCollections.mockResolvedValueOnce({
            collections: [
                { id: '1', name: 'Art', color: '#ff0000', image_count: 5, created_at: '2026-06-19', updated_at: '2026-06-19' }
            ]
        });

        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const wrapper = createWrapper(queryClient);

        const { result } = renderHook(() => useCollections(), { wrapper });

        await waitFor(() => {
            expect(result.current.data).toBeDefined();
        });

        expect(result.current.data['1']).toEqual({
            id: '1',
            name: 'Art',
            color: '#ff0000',
            thumbnail: undefined,
            imageCount: 5,
            images: [],
            created: '2026-06-19',
            updated: '2026-06-19',
        });
    });

    it('useCollectionImages fetches images on demand', async () => {
        collectionsApi.getCollection.mockResolvedValueOnce({
            images: ['image1.png', 'image2.png']
        });

        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const wrapper = createWrapper(queryClient);

        const { result } = renderHook(() => useCollectionImages('1'), { wrapper });

        await waitFor(() => {
            expect(result.current.data).toBeDefined();
        });

        expect(result.current.data).toEqual(['image1.png', 'image2.png']);
        expect(collectionsApi.getCollection).toHaveBeenCalledWith('1', true);
    });

    it('usePrompts lists prompts and usePromptCategories lists categories', async () => {
        promptsApi.listPrompts.mockResolvedValueOnce({
            prompts: [{ id: 'p1', name: 'Style 1', category: 'Portrait' }]
        });
        promptsApi.getCategories.mockResolvedValueOnce({
            categories: ['Portrait', 'CustomCategory']
        });

        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const wrapper = createWrapper(queryClient);

        const { result: promptsResult } = renderHook(() => usePrompts(), { wrapper });
        const { result: categoriesResult } = renderHook(() => usePromptCategories(), { wrapper });

        await waitFor(() => {
            expect(promptsResult.current.data).toBeDefined();
            expect(categoriesResult.current.data).toBeDefined();
        });

        expect(promptsResult.current.data).toHaveLength(1);
        expect(promptsResult.current.data[0].id).toBe('p1');
        expect(categoriesResult.current.data).toContain('CustomCategory');
        expect(categoriesResult.current.data).toContain('All');
    });

    it('useActiveJobs fetches active jobs from api', async () => {
        jobsApi.getActive.mockResolvedValueOnce({
            jobs: [{ id: 'j1', status: 'running' }]
        });

        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const wrapper = createWrapper(queryClient);

        const { result } = renderHook(() => useActiveJobs(), { wrapper });

        await waitFor(() => {
            expect(result.current.data).toBeDefined();
        });

        expect(result.current.data).toHaveLength(1);
        expect(result.current.data[0].id).toBe('j1');
    });

    it('useTrackJob fetches single job and updates reactively', async () => {
        jobsApi.get.mockResolvedValueOnce({
            job: { id: 'j1', status: 'running', progress: 50 }
        });

        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const wrapper = createWrapper(queryClient);

        const { result } = renderHook(() => useTrackJob('j1'), { wrapper });

        await waitFor(() => {
            expect(result.current.data).toBeDefined();
        });

        expect(result.current.data.progress).toBe(50);

        // Simulate WebSocket event update for this single job query
        act(() => {
            queryClient.setQueryData(['jobs', 'j1'], { id: 'j1', status: 'completed', progress: 100 });
        });

        await waitFor(() => {
            expect(result.current.data.status).toBe('completed');
            expect(result.current.data.progress).toBe(100);
        });
    });

    it('useJobsRealtime subscribes to socket events and patches cache', async () => {
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const wrapper = createWrapper(queryClient);

        queryClient.setQueryData(['jobs', 'active'], [{ id: 'j1', status: 'running', progress: 10 }]);

        renderHook(() => useJobsRealtime(), { wrapper });

        await waitFor(() => {
            expect(websocketMock.connect).toHaveBeenCalled();
            expect(websocketMock.subscribe).toHaveBeenCalledWith('job');
        });

        // Simulate JOB_PROGRESS event
        await act(async () => {
            websocketMock.emit('job.progress', {
                data: {
                    job: { id: 'j1', status: 'running', progress: 45 }
                }
            });
        });

        await waitFor(async () => {
            const job = queryClient.getQueryData(['jobs', 'j1']);
            expect(job.progress).toBe(45);
        });
    });
});
