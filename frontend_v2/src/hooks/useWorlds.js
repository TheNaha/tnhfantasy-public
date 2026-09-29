import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { useCreateResource, useDeleteResource, useUpdateResource } from './useWorldVaultResource';

const WORLDS_KEY = buildQueryKey(QUERY_KEYS.WORLDS);
const WORLD_DETAIL_KEY = (id) => buildQueryKey(QUERY_KEYS.WORLDS, id);

/**
 * The World Vault's grouping entity.
 *
 * `a338abc0` renamed the server-side `Campaign` resource to `World` and deleted
 * `campaigns.py`, but left the frontend pointing at `/api/v2/campaigns` on all
 * five verbs. The old page had no `isError` branch, so the 404 rendered as
 * "No campaigns yet" with a working-looking button, and the failure reached the
 * sidebar, the ⌘K palette, the roleplay front door and the count card (which read
 * 0 forever) without a single visible error. The route is `/api/v2/worlds` and
 * the request models are `WorldCreate` / `WorldUpdate`.
 */
export const useWorlds = () => {
    return useQuery({
        queryKey: WORLDS_KEY,
        queryFn: () => api.get('/api/v2/worlds'),
    });
};

export const useWorld = (worldId) => {
    return useQuery({
        queryKey: WORLD_DETAIL_KEY(worldId),
        queryFn: () => api.get(`/api/v2/worlds/${worldId}`),
        enabled: !!worldId,
    });
};

/**
 * The world's membership index, resolved to real rows.
 *
 * `character_ids` / `story_ids` / `chat_ids` / `location_ids` on a `World` are a
 * denormalised index, not ownership of record — a Chat's or Story's `world_id`
 * column is. This route joins the index against the tables, which is why it
 * exists separately from the list.
 */
export const useWorldDashboard = (worldId) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.WORLDS, worldId, 'dashboard'),
        queryFn: () => api.get(`/api/v2/worlds/${worldId}/dashboard`),
        enabled: !!worldId,
    });
};

export const useCreateWorld = () => useCreateResource({ basePath: '/api/v2/worlds', listQueryKey: WORLDS_KEY });

export const useUpdateWorld = () => useUpdateResource({
    basePath: '/api/v2/worlds',
    listQueryKey: WORLDS_KEY,
    detailQueryKey: WORLD_DETAIL_KEY,
});

export const useDeleteWorld = () => useDeleteResource({ basePath: '/api/v2/worlds', listQueryKey: WORLDS_KEY });
