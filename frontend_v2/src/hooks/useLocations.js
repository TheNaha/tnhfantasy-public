import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { useCreateResource, useDeleteResource, useUpdateResource } from './useWorldVaultResource';

const LOCATIONS_KEY = buildQueryKey(QUERY_KEYS.LOCATIONS);
const LOCATION_DETAIL_KEY = (id) => buildQueryKey(QUERY_KEYS.LOCATIONS, id);

export const useLocations = () => {
    return useQuery({
        queryKey: LOCATIONS_KEY,
        queryFn: () => api.get('/api/v2/locations'),
    });
};

export const useLocation = (locationId) => {
    return useQuery({
        queryKey: LOCATION_DETAIL_KEY(locationId),
        queryFn: () => api.get(`/api/v2/locations/${locationId}`),
        enabled: !!locationId,
    });
};

export const useCreateLocation = () => useCreateResource({ basePath: '/api/v2/locations', listQueryKey: LOCATIONS_KEY });

export const useUpdateLocation = () => useUpdateResource({
    basePath: '/api/v2/locations',
    listQueryKey: LOCATIONS_KEY,
    detailQueryKey: LOCATION_DETAIL_KEY,
});

export const useDeleteLocation = () => useDeleteResource({ basePath: '/api/v2/locations', listQueryKey: LOCATIONS_KEY });

export const useSearchLocations = (query) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.LOCATIONS, 'search', query),
        queryFn: () => api.get('/api/v2/locations/search', { params: { q: query } }),
        enabled: !!query && query.length >= 2,
    });
};


