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

/**
 * Callers may pass a filter in camelCase; the route spells it snake_case. Only
 * the ones that differ are listed — everything else is already a valid query
 * parameter and is forwarded verbatim, which is why the `location` filter stays
 * `location` (it takes a location *name*, matching `Chat.story_location`).
 */
const PARAM_NAMES = {
    worldId: 'world_id',
};

export const useTimeline = (filters = {}) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.TIMELINE, filters),
        queryFn: () => {
            const params = new URLSearchParams();
            Object.entries(filters).forEach(([key, value]) => {
                if (value) params.set(PARAM_NAMES[key] || key, value);
            });
            return api.get(`/api/v2/timeline?${params.toString()}`);
        },
        enabled: true,
    });
};
