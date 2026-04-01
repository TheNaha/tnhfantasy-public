import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import { filesApi } from '../api';

async function loadModelDirectories(requests) {
    const results = await Promise.allSettled(
        requests.map(({ directory }) => filesApi.list({ directory }))
    );

    const data = {};
    const failures = [];

    results.forEach((result, index) => {
        const request = requests[index];
        if (result.status === 'fulfilled') {
            data[request.key] = result.value.files || [];
            return;
        }

        data[request.key] = [];
        failures.push(request.label || request.directory);
    });

    return { data, failures };
}

export function useModelDirectories(requests) {
    const stableRequests = useMemo(() => requests, [requests]);
    const [modelsByKey, setModelsByKey] = useState({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        let cancelled = false;

        const fetchDirectories = async () => {
            setLoading(true);
            setError(null);

            try {
                const { data, failures } = await loadModelDirectories(stableRequests);
                if (cancelled) {
                    return;
                }

                setModelsByKey(data);
                if (failures.length > 0) {
                    const message = `Some model directories failed to load: ${failures.join(', ')}`;
                    setError(message);
                    toast.error(message);
                }
            } catch (fetchError) {
                if (cancelled) {
                    return;
                }

                setError(fetchError.message);
                toast.error('Failed to load models');
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        };

        fetchDirectories();

        return () => {
            cancelled = true;
        };
    }, [stableRequests]);

    return { modelsByKey, loading, error };
}
