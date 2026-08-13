import { useQuery } from '@tanstack/react-query';
import { api } from '../api';

export const useLorebooks = () => {
    return useQuery({
        queryKey: ['world_vault', 'lorebooks'],
        queryFn: () => api.get('/api/v2/lorebooks')
    });
};
