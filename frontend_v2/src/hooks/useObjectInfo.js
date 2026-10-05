import { useQuery } from '@tanstack/react-query';
import { fetchObjectInfo } from '../api/nodes';
import * as idb from 'idb-keyval';

/**
 * The `/api/nodes/object_info` proxy answers HTTP 200 for a failed upstream and
 * puts the failure in the body:
 *
 *   {"status":"error","message":"Failed to query ComfyUI: ","retryable":true,
 *    "code":502,"success":false,"provider":"direct_url"}
 *
 * Measured on the live stack: 30.02s per call (three consecutive calls, so not
 * a cold start) for a provider that is registered `enabled=false`. Because the
 * status is 200 this hook could not tell that payload from a successful one, so
 * it wrote it to IndexedDB and returned it — and `NodeRegistry` then built a
 * palette from its six keys, none of which has a `.category`, rendering one
 * group literally named `unknown`. The stale time is 24 hours with
 * `refetchOnMount: false`, so the page stayed broken across reloads until the
 * cache expired on its own.
 *
 * So the error envelope is detected here rather than in the client: the client
 * is correct to hand back a 200 body, and only this consumer knows that a body
 * carrying `status: 'error'` is not a node-definition map.
 */
function assertNodeDefinitions(data, providerId) {
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
        throw new Error(`Provider ${providerId} returned no node definitions`);
    }
    if (data.status === 'error' || data.success === false || data.error) {
        const detail = data.message || data.error || `HTTP ${data.code ?? '?'}`;
        throw new Error(`Failed to load node definitions from ${providerId}: ${detail}`);
    }
    return data;
}

/** Is a cached IndexedDB payload usable as node definitions? */
function isNodeDefinitionCache(cached) {
    if (!cached || typeof cached !== 'object' || Array.isArray(cached)) return false;
    if (cached.status === 'error' || cached.success === false || cached.error) return false;
    return Object.keys(cached).length > 0;
}

/**
 * The IndexedDB payload to offer as a fallback, or `null`.
 *
 * Read separately so the failure path can attach it to the error rather than
 * return it.
 */
async function readStaleCache(cacheKey) {
    try {
        const cached = await idb.get(cacheKey);
        return isNodeDefinitionCache(cached) ? cached : null;
    } catch {
        return null;
    }
}

export function useObjectInfo(providerId) {
    const query = useQuery({
        queryKey: ['objectInfo', providerId],
        queryFn: async ({ signal }) => {
            const cacheKey = `object_info_${providerId}`;

            try {
                const data = assertNodeDefinitions(
                    await fetchObjectInfo(providerId, { signal }),
                    providerId
                );
                await idb.set(cacheKey, data);
                return data;
            } catch (e) {
                // RE-THROWN, with any cached payload attached to the error.
                //
                // This used to `return cached`. Returning from a query function
                // is a success, so React Query recorded a days-old IndexedDB
                // payload as fresh: `ReactFlowEditor.jsx` destructured `error`,
                // which is therefore always `undefined` on this path, and
                // `/advanced` rendered its node palette from the stale cache
                // with no banner, no retry, and no way to force a refetch short
                // of clearing IndexedDB by hand. One transient failure at 16:00
                // and the page was broken until 16:00 the next day.
                //
                // The cache is still worth having — a stale node list is more
                // useful than none — but it has to arrive labelled as stale.
                throw Object.assign(e, { staleData: await readStaleCache(cacheKey) });
            }
        },
        enabled: !!providerId,
        // Was 24h. The node palette changes when a provider's ComfyUI does — a
        // new custom-node pack, a version bump — and a day-long window cannot
        // express that. Five minutes still absorbs remounts and tab switches
        // without the endpoint's cost; the payload is large and the proxy took
        // 30s per call on the live stack.
        staleTime: 1000 * 60 * 5,
        gcTime: 1000 * 60 * 30,
        // Was `false`, and this is the single most consequential deletion: it
        // is what turned "one failure" into "broken until the cache expired",
        // because opening `/advanced` again did not refetch even once.
        refetchOnMount: true,
        refetchOnWindowFocus: true,
        refetchOnReconnect: true,
        retry: 1,
    });

    return {
        ...query,
        /**
         * Failed, but a cached payload is available to render.
         *
         * The editor shows a banner over the stale palette in this state: the
         * user learns the node list may be out of date and gets a Retry button,
         * instead of being handed yesterday's nodes with nothing said.
         */
        isStale: !!query.error && !!query.error.staleData,
        /** The stale payload itself, for rendering. Never presented as fresh. */
        staleData: query.error?.staleData ?? null,
    };
}