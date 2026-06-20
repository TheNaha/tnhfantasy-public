import { useQuery } from '@tanstack/react-query';
import { jobsApi } from '../api';

export function useTrackJob(jobId) {
    return useQuery({
        queryKey: ['jobs', jobId],
        queryFn: async () => {
            if (!jobId) return null;
            const data = await jobsApi.get(jobId);
            return data?.job || data;
        },
        enabled: !!jobId,
        staleTime: 30_000,
    });
}

export default useTrackJob;
