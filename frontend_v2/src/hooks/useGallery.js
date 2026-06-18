import { useInfiniteQuery } from '@tanstack/react-query';
import { filesApi } from '../api';

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

            return {
                files: filesData.files || [],
                nextPage: filesData.files?.length === LIMIT ? pageParam + 1 : undefined
            };
        },
        getNextPageParam: (lastPage) => lastPage.nextPage,
        initialPageParam: 0,
        staleTime: 1 * 60 * 1000, // 1 minute

    });
}

