import { useEffect, useMemo } from 'react';
import { useQueries } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { filesApi } from '../api';

const MODEL_DIRECTORY_STALE_TIME_MS = 5 * 60 * 1000;
const MODEL_DIRECTORY_GC_TIME_MS = 30 * 60 * 1000;

/** One identity for "no models", so a consumer's memo holds while a directory loads. */
const NO_MODELS = [];

async function fetchModelDirectory(directory, signal) {
    const response = await filesApi.list({ directory, limit: 500 }, { signal });
    return response?.files || [];
}

export function useModelDirectories(requests) {
    const requestsKey = useMemo(() => JSON.stringify(requests), [requests]);
    const stableRequests = useMemo(() => JSON.parse(requestsKey), [requestsKey]);

    /**
     * `combine` is what gives the consumers a stable object.
     *
     * Without it, `useQueries` returns the optimistic result array unchanged —
     * a fresh array identity on every render — so a `useMemo` that depended on
     * it could never hit, and all six consumers received a new `modelsByKey`
     * on every render of the page holding them. Five of the standing
     * `exhaustive-deps` warnings existed because of it: BatchGenerate reads
     * `modelsByKey.checkpoints` into two memos and two callbacks.
     *
     * query-core runs a combined value through `replaceEqualDeep` and returns
     * the previous object when it is structurally equal, which is what holds
     * this one's identity. Its leaves are the query `data` arrays, and that
     * comparison short-circuits on `===` for identical references — so a render
     * that changed nothing costs eight reference comparisons, and the deep
     * comparison only runs for the one directory whose data actually moved.
     */
    const { modelsByKey, failed, loading } = useQueries({
        queries: stableRequests.map(({ directory }) => ({
            queryKey: ['model-directory', directory],
            queryFn: ({ signal }) => fetchModelDirectory(directory, signal),
            staleTime: MODEL_DIRECTORY_STALE_TIME_MS,
            gcTime: MODEL_DIRECTORY_GC_TIME_MS,
            refetchOnWindowFocus: false,
        })),
        combine: (results) => ({
            modelsByKey: Object.fromEntries(
                stableRequests.map((request, index) => [request.key, results[index]?.data ?? NO_MODELS])
            ),
            failed: results.map((result) => result.isError),
            loading: results.some((result) => result.isLoading),
        }),
    });

    const failedLabels = useMemo(() => {
        const failures = [];
        stableRequests.forEach(({ label, directory }, index) => {
            if (failed[index]) failures.push(label || directory);
        });
        return failures;
    }, [failed, stableRequests]);

    const error = failedLabels.length > 0
        ? `Some model directories failed to load: ${failedLabels.join(', ')}`
        : null;

    useEffect(() => {
        if (!error) {
            return;
        }

        toast.error(error, { id: 'model-directories-load-failed' });
    }, [error]);

    return { modelsByKey, loading, error };
}