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
                limit: LIMIT,
                offset: offset,
                ...filters
            };

            // Remove undefined/null filters
            Object.keys(params).forEach(key => {
                if (params[key] === undefined || params[key] === null || params[key] === '') {
                    delete params[key];
                }
            });

            // Fetch Files and Jobs using API client
            const [filesData, jobsData] = await Promise.all([
                filesApi.list({ ...params, directory: 'output', sort: 'date_desc' }),
                jobsApi.list({ ...params, sort: 'created_at_desc' }).catch(() => ({ jobs: [] })) // fallback if jobs fails
            ]);

            return {
                files: filesData.files || [],
                jobs: jobsData.jobs || [],
                nextPage: filesData.files?.length === LIMIT ? pageParam + 1 : undefined
            };
        },
        getNextPageParam: (lastPage) => lastPage.nextPage,
        initialPageParam: 0,
        staleTime: 1 * 60 * 1000, // 1 minute
    });
}

