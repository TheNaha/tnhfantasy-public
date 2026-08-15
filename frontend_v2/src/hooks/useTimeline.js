import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey } from '../constants/queryKeys';

export const useTimeline = (filters = {}) => {
    return useQuery({
        queryKey: buildQueryKey('timeline', filters),
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
