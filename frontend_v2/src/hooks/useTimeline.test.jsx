import { cleanup, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useTimeline } from './useTimeline';

const apiMock = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('../api', () => ({ api: apiMock }));

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const wrapper = ({ children }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

describe('useTimeline', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
        apiMock.get.mockResolvedValue({ events: [], total: 0 });
    });

    it('hits the backend /timeline/timeline route (mounted prefix + route)', async () => {
        renderHook(() => useTimeline({}), { wrapper });
        await vi.waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(1));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/timeline?');
    });

    it('serializes non-empty filters into the query string', async () => {
        renderHook(() => useTimeline({ character_id: 'c1', limit: 20 }), { wrapper });
        await vi.waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(1));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/timeline?character_id=c1&limit=20');
    });

    it('omits empty filter values', async () => {
        renderHook(() => useTimeline({ character_id: '', limit: 0, story_id: 's1' }), { wrapper });
        await vi.waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(1));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/timeline?story_id=s1');
    });

    it('sends the camelCase worldId option as the route\'s world_id parameter', async () => {
        renderHook(() => useTimeline({ worldId: 'w1' }), { wrapper });
        await vi.waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(1));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/timeline?world_id=w1');
    });

    it('keeps `location` a name filter — it is not an id column on the server', async () => {
        renderHook(() => useTimeline({ location: 'The Docks' }), { wrapper });
        await vi.waitFor(() => expect(apiMock.get).toHaveBeenCalledTimes(1));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/timeline?location=The+Docks');
    });
});