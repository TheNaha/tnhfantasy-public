import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';

/**
 * Every filter combination's key shares this prefix, so one invalidation of
 * `TIMELINE_KEY` reaches all of them — the Activity page changes its filter set
 * (and therefore its key) on every chip click, and invalidating the exact key of
 * the query that happened to be mounted would leave the other four stale.
 */
export const TIMELINE_KEY = buildQueryKey(QUERY_KEYS.TIMELINE);

export const useTimeline = (filters = {}) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.TIMELINE, filters),
        queryFn: () => {
            const params = new URLSearchParams();
            Object.entries(filters).forEach(([key, value]) => {
                if (value) params.set(key, value);
            });
            return api.get(`/api/v2/timeline/timeline?${params.toString()}`);
        },
        enabled: true,
    });
};
