import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { jobsApi } from '../api';
import * as ws from '../api/websocket';

const isMobile = () => typeof navigator !== 'undefined' && ('ontouchstart' in window || navigator.maxTouchPoints > 0);

export function useActiveJobs() {
    // Subscribe to connection events so the poll fallback starts/stops
    // reactively instead of reading a stale module-level flag on the next
    // query evaluation.
    const [wsConnected, setWsConnected] = useState(() => ws.getConnectionStatus());

    useEffect(() => {
        const unsub = ws.on('connection', ({ connected }) => setWsConnected(connected));
        return unsub;
    }, []);

    return useQuery({
        queryKey: ['jobs', 'active'],
        queryFn: async () => {
            const data = await jobsApi.getActive();
            return data?.jobs || [];
        },
        staleTime: 30000, // 30 seconds
        refetchOnWindowFocus: false, // useJobsRealtime refreshes on visibility change
        refetchInterval: (query) => {
            const hasActiveJobs = (query.state.data || []).length > 0;
            if (hasActiveJobs && isMobile() && !wsConnected) {
                return 2000;
            }
            return false;
        }
    });
}
