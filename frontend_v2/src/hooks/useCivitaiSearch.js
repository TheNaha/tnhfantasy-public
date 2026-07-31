import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { api } from '../api';

export function useCivitaiEnums() {
    return useQuery({
        queryKey: ['civitai', 'enums'],
        queryFn: async () => {
            try {
                const data = await api.get('/api/v2/models/external/civitai/enums');
                return {
                    ModelType: data.ModelType || [],
                    BaseModel: data.BaseModel || []
                };
            } catch (err) {
                console.warn("Failed to fetch CivitAI enums:", err);
                return {
                    ModelType: ['Checkpoint', 'LORA', 'VAE', 'Controlnet', 'Upscaler', 'TextualInversion', 'Hypernetwork', 'MotionModule'],
                    BaseModel: ['SD 1.5', 'SDXL 1.0', 'SD 3', 'SD 3.5', 'Flux.1 D', 'Pony', 'Illustrious']
                };
            }
        },
        staleTime: 1000 * 60 * 60, // 1 hour
    });
}

export function useCivitaiTags() {
    return useQuery({
        queryKey: ['civitai', 'tags'],
        queryFn: async () => {
            const data = await api.get('/api/v2/models/external/civitai/tags?limit=20');
            return data.items || [];
        },
        staleTime: 1000 * 60 * 60,
    });
}

export function useCivitaiSearch(filters, options = {}) {
    return useInfiniteQuery({
        queryKey: ['civitai', 'search', filters],
        queryFn: async ({ pageParam }) => {
            const params = new URLSearchParams({ limit: '20' });
            
            if (filters.query) params.append('query', filters.query);
            
            if (filters.source === 'civitai') {
                if (filters.types?.length > 0) params.append('types', filters.types.join(','));
                if (filters.sort) params.append('sort', filters.sort);
                if (filters.baseModels?.length > 0) params.append('baseModels', filters.baseModels.join(','));
                if (filters.nsfw) params.append('nsfw', filters.nsfw);
                if (filters.period) params.append('period', filters.period);
                if (filters.username) params.append('username', filters.username);
                if (filters.tag) params.append('tag', filters.tag);
                
                if (pageParam?.cursor) {
                    params.append('cursor', pageParam.cursor);
                } else if (!filters.query && pageParam?.page) {
                    params.append('page', pageParam.page);
                } else if (pageParam?.page) {
                    params.append('page', pageParam.page);
                }
            } else {
                if (pageParam?.page) {
                    params.append('page', pageParam.page);
                }
            }
            
            const source = filters.source || 'civitai';
            const endpoint = `/api/v2/models/external/${source}`;
            const url = `${endpoint}?${params.toString()}`;
            
            return await api.get(url);
        },
        initialPageParam: { page: 1, cursor: null },
        getNextPageParam: (lastPage, allPages) => {
            if (lastPage.metadata?.nextCursor) {
                return { cursor: lastPage.metadata.nextCursor, page: allPages.length + 1 };
            }
            if (lastPage.metadata?.nextPage) {
                return { page: allPages.length + 1, cursor: null };
            }
            return null;
        },
        enabled: options.enabled !== false,
    });
}

export function useBatchAutopopulateCandidates(modelIds, options = {}) {
    return useQuery({
        queryKey: ['autopopulate', 'candidates', 'batch', modelIds],
        queryFn: async () => {
            if (!modelIds || modelIds.length === 0) return [];
            const data = await api.post('/api/v2/models/autopopulate-candidates/batch', { model_ids: modelIds });
            return data.results || [];
        },
        enabled: options.enabled !== false && modelIds?.length > 0,
        staleTime: 1000 * 60 * 5,
    });
}

export function useAutopopulatePending() {
    return useQuery({
        queryKey: ['autopopulate', 'pending'],
        queryFn: async () => {
            const data = await api.get('/api/v2/models/autopopulate-pending');
            return data.pending || [];
        }
    });
}

export function useAutopopulateCandidates(modelId) {
    return useQuery({
        queryKey: ['autopopulate', 'candidates', modelId],
        queryFn: async () => {
            if (!modelId) return null;
            const res = await api.get(`/api/v2/models/${modelId}/autopopulate-candidates`);
            return res;
        },
        enabled: !!modelId,
    });
}

export function useCheckInstalledVersions(modelId) {
    return useQuery({
        queryKey: ['model', 'installed', modelId],
        queryFn: async () => {
            if (!modelId) return [];
            const data = await api.get(`/api/v2/models/check-installed/${modelId}`);
            return data.installed_versions || [];
        },
        enabled: !!modelId,
    });
}
