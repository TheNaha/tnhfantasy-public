/**
 * `toggleFavorite` identity regression test.
 *
 * It used to depend on the whole `useMutation` result, which react-query v5
 * rebuilds as a new object literal on every render. That made `toggleFavorite`
 * change identity on every Dashboard render, defeating `useCallback` in
 * Dashboard, useDashboardSelection and `memo(GroupedDashboardContent)`.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useFavorites } from './useFavorites';
import { settingsApi } from '../api/settingsApi';

vi.mock('../api/settingsApi', () => ({
    settingsApi: {
        getFavorites: vi.fn(async () => ({ favorites: ['a.png'] })),
        updateFavorites: vi.fn(async (favorites) => ({ favorites })),
    },
}));

// One client for the whole file: a client rebuilt per wrapper render would
// change the context value and hide the identity regression under test.
const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
});
const wrapper = ({ children }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

describe('useFavorites', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('keeps toggleFavorite stable across a re-render', async () => {
        const { result, rerender } = renderHook(() => useFavorites(), { wrapper });

        await waitFor(() => expect(result.current.favorites).toEqual(['a.png']));
        const first = result.current.toggleFavorite;

        // A re-render with no new server data: the mutation result object is
        // still rebuilt, so only a dep on `mutate` survives.
        rerender();
        expect(result.current.toggleFavorite).toBe(first);

        act(() => result.current.toggleFavorite('b.png'));
        rerender();
        expect(result.current.toggleFavorite).toBe(first);

        await waitFor(() => expect(settingsApi.updateFavorites).toHaveBeenCalled());
        expect(settingsApi.updateFavorites).toHaveBeenLastCalledWith(['a.png', 'b.png']);
    });
});
