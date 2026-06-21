import { useQuery } from '@tanstack/react-query';
import { jobsApi } from '../api';
import * as ws from '../api/websocket';

const isMobile = () => typeof navigator !== 'undefined' && ('ontouchstart' in window || navigator.maxTouchPoints > 0);

export function useActiveJobs() {
    return useQuery({
        queryKey: ['jobs', 'active'],
        queryFn: async () => {
            const data = await jobsApi.getActive();
            return data?.jobs || [];
        },
        staleTime: 30000, // 30 seconds
        refetchInterval: (query) => {
            const hasActiveJobs = (query.state.data || []).length > 0;
            const wsConnected = ws.getConnectionStatus();
            if (hasActiveJobs && isMobile() && !wsConnected) {
                return 2000;
            }
            return false;
        }
    });
}
