import { useQuery } from '@tanstack/react-query';
import { fetchObjectInfo } from '../api/nodes';
import * as idb from 'idb-keyval';

export function useObjectInfo(providerId) {
    return useQuery({
        queryKey: ['objectInfo', providerId],
        queryFn: async () => {
            const cacheKey = `object_info_${providerId}`;
            const cached = await idb.get(cacheKey);
            // Optionally check for stale time manually here if needed
            // But React Query handles memory caching. This is for cross-session.
            
            try {
                const data = await fetchObjectInfo(providerId);
                await idb.set(cacheKey, data);
                return data;
            } catch (e) {
                if (cached) return cached;
                throw e;
            }
        },
        enabled: !!providerId,
        staleTime: 1000 * 60 * 60 * 24, // 24 hours
        cacheTime: 1000 * 60 * 60 * 24, // 24 hours
        refetchOnWindowFocus: false,
        refetchOnMount: false,
        refetchOnReconnect: false,
    });
}
