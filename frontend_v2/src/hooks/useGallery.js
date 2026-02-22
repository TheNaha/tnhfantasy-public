import { useInfiniteQuery } from '@tanstack/react-query';
import { filesApi, jobsApi } from '../api';

const LIMIT = 20;

export function useGallery(filters = {}) {
    return useInfiniteQuery({
        queryKey: ['gallery', filters],
        queryFn: async ({ pageParam = 0 }) => {
            const offset = pageParam * LIMIT;

            // Build params
            const params = {
                directory: 'output',
                limit: LIMIT,
                offset: offset,
                sort: 'date_desc',
                ...filters
            };

            // Remove undefined/null filters
            Object.keys(params).forEach(key => {
                if (params[key] === undefined || params[key] === null || params[key] === '') {
                    delete params[key];
                }
            });

            // Fetch Files using API client
            const filesData = await filesApi.list(params);

            // Fetch Jobs (only for the first page and if no complex filters are active)
            const hasComplexFilters = filters.start_date || filters.end_date || filters.model || filters.sampler || filters.aspect_ratio;
            let jobsData = { jobs: [] };

            if (!hasComplexFilters) {
                jobsData = await jobsApi.list({ limit: LIMIT, offset });
            }

            return {
                files: filesData.files || [],
                jobs: jobsData.jobs || [],
                nextPage: (filesData.files?.length === LIMIT || jobsData.jobs?.length === LIMIT) ? pageParam + 1 : undefined
            };
        },
        getNextPageParam: (lastPage) => lastPage.nextPage,
        initialPageParam: 0,
        staleTime: 1 * 60 * 1000, // 1 minute

    });
}

