import { useInfiniteQuery } from '@tanstack/react-query';
import { assetsApi, jobsApi } from '../api';

const LIMIT = 20;

export function useGallery(filters = {}) {
    return useInfiniteQuery({
        queryKey: ['gallery', filters],
        queryFn: async ({ pageParam = null }) => {
            // Build params (cursor-based keyset pagination)
            const params = {
                limit: LIMIT,
                cursor: pageParam || undefined,
                search: filters.search,
                workspace: filters.workspace,
                character_id: filters.character_id,
                story_id: filters.story_id,
            };

            // Remove undefined/null filters
            Object.keys(params).forEach(key => {
                if (params[key] === undefined || params[key] === null || params[key] === '') {
                    delete params[key];
                }
            });

            // Fetch Assets and Jobs using API client
            const [assetsData, jobsData] = await Promise.all([
                assetsApi.list(params),
                jobsApi.list({ limit: LIMIT, sort: 'created_at_desc' }).catch(() => ({ jobs: [] })) // fallback if jobs fails
            ]);

            return {
                files: assetsData.items || [],
                jobs: jobsData.jobs || [],
                nextPage: assetsData.has_more ? assetsData.next_cursor : undefined
            };
        },
        getNextPageParam: (lastPage) => lastPage.nextPage,
        initialPageParam: null,
        staleTime: 1 * 60 * 1000, // 1 minute
    });
}
