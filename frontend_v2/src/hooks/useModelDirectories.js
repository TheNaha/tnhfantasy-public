import { useEffect, useMemo } from 'react';
import { useQueries } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { filesApi } from '../api';

const MODEL_DIRECTORY_STALE_TIME_MS = 5 * 60 * 1000;
const MODEL_DIRECTORY_GC_TIME_MS = 30 * 60 * 1000;

async function fetchModelDirectory(directory) {
    const response = await filesApi.list({ directory });
    return response?.files || [];
}

export function useModelDirectories(requests) {
    const stableRequests = useMemo(() => requests, [requests]);
    const directoryQueries = useQueries({
        queries: stableRequests.map(({ directory }) => ({
            queryKey: ['model-directory', directory],
            queryFn: () => fetchModelDirectory(directory),
            staleTime: MODEL_DIRECTORY_STALE_TIME_MS,
            gcTime: MODEL_DIRECTORY_GC_TIME_MS,
            refetchOnWindowFocus: false,
        })),
    });

    const modelsByKey = useMemo(() => {
        const next = {};
        stableRequests.forEach((request, index) => {
            next[request.key] = directoryQueries[index]?.data || [];
        });
        return next;
    }, [stableRequests, directoryQueries]);

    const failedLabels = useMemo(() => {
        const failures = [];
        stableRequests.forEach((request, index) => {
            if (directoryQueries[index]?.isError) {
                failures.push(request.label || request.directory);
            }
        });
        return failures;
    }, [stableRequests, directoryQueries]);

    const error = failedLabels.length > 0
        ? `Some model directories failed to load: ${failedLabels.join(', ')}`
        : null;

    const loading = directoryQueries.some((query) => query.isLoading);

    useEffect(() => {
        if (!error) {
            return;
        }

        toast.error(error, { id: 'model-directories-load-failed' });
    }, [error]);

    return { modelsByKey, loading, error };
}
