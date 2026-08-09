/**
 * useJobStatus — single source of truth for a job's live status.
 *
 * Reads the ['jobs', jobId] React Query cache, which the global useJobsRealtime
 * bridge keeps in sync via WebSocket JOB_PROGRESS / JOB_UPDATED / JOB_COMPLETED
 * / JOB_FAILED / JOB_CANCELLED events. When the socket is down, falls back to
 * polling the REST endpoint so progress never freezes.
 *
 * Replaces the previous useTrackJob (poll-only, stale after 30s) and unifies
 * job tracking for the generator pages (useTrackGenerationJob) and JobCard.
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { jobsApi } from '../api';
import * as ws from '../api/websocket';

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'error', 'cancelled']);

export function useJobStatus(jobId, { pollInterval = 2000, enabled = true } = {}) {
    const [wsConnected, setWsConnected] = useState(() => ws.getConnectionStatus());

    useEffect(() => {
        const unsub = ws.on('connection', ({ connected }) => setWsConnected(connected));
        return unsub;
    }, []);

    return useQuery({
        queryKey: ['jobs', jobId],
        queryFn: async () => {
            if (!jobId) return null;
            const data = await jobsApi.get(jobId);
            return data?.job || data;
        },
        enabled: !!jobId && enabled,
        staleTime: 30_000,
        refetchInterval: (query) => {
            if (!jobId || wsConnected) return false;
            const job = query.state.data;
            if (!job || TERMINAL_STATUSES.has(job.status)) return false;
            return pollInterval;
        },
    });
}

export default useJobStatus;
