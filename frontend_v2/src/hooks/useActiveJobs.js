import { useQuery } from '@tanstack/react-query';
import { jobsApi } from '../api';

export function useActiveJobs() {
    return useQuery({
        queryKey: ['jobs', 'active'],
        queryFn: async () => {
            const data = await jobsApi.getActive();
            return data?.jobs || [];
        },
        staleTime: 30000, // 30 seconds
    });
}
