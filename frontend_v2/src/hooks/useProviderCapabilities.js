import { useQuery } from '@tanstack/react-query';
import { fetchProviderCapabilities } from '../api';

/**
 * What a provider can actually do.
 *
 * The answer is which node classes it has, and which files it has for each
 * of them. The Enhancements panel needs it because the panel used to
 * hardcode the provider's node vocabulary in Python and offer a FreeU toggle
 * to a provider with no FreeU node - and the request failed at dispatch with
 * "node type not found", after the user had picked the enhancement and
 * waited for the job.
 *
 * `capabilities` is null while it is loading, and null when the provider
 * could not be introspected. That is NOT the same as "the provider cannot
 * do this": a provider that is down must not be read as a provider that
 * cannot do FreeU, so the panel leaves the control live and claims nothing.
 */
export function useProviderCapabilities(providerId, { enabled = true } = {}) {
    const { data, isLoading, isError } = useQuery({
        queryKey: ['nodes', 'capabilities', providerId],
        queryFn: ({ signal }) => fetchProviderCapabilities(providerId, { signal }),
        enabled: Boolean(providerId) && enabled,
        // The provider's node graph does not change while it is up, and the
        // answer is expensive to produce the first time.
        staleTime: 5 * 60 * 1000,
        retry: false,
    });

    return {
        capabilities: data || null,
        isLoading,
        isError,
    };
}

export default useProviderCapabilities;
