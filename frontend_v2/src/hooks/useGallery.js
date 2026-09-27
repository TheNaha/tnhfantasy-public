import { useInfiniteQuery } from '@tanstack/react-query';
import { assetsApi, jobsApi } from '../api';
import useSettingsStore from '../store/settingsStore';

export function useGallery(filters = {}) {
    // Settings > Gallery > "Items Per Page" writes this; it used to be a
    // hardcoded 20, which left the control dead.
    const limit = useSettingsStore((s) => s.settings?.gallery?.itemsPerPage) || 20;

    return useInfiniteQuery({
        // The limit is in the key so changing "Items Per Page" in Settings takes
        // effect on the next render instead of the next refetch. Everything that
        // invalidates the gallery uses `['gallery', filters]` as a prefix.
        queryKey: ['gallery', filters, limit],
        queryFn: async ({ pageParam = null }) => {
            // Build params (cursor-based keyset pagination)
            const params = {
                limit,
                cursor: pageParam || undefined,
                search: filters.search,
                workspace: filters.workspace,
                character_id: filters.character_id,
                story_id: filters.story_id,
                sort: filters.sort,
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
                pageParam
                    ? Promise.resolve({ jobs: [] })
                    : jobsApi.list({ limit, sort: 'created_at_desc' }).catch(() => ({ jobs: [] })),
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
