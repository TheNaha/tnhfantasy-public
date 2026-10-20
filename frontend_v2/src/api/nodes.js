import client from './client';

// object_info is served from the Modal worker through the backend proxy and
// can take 35-70s on cold/warm invocations — far beyond the 30s client default.
//
// `options` is forwarded so `useObjectInfo`'s queryFn can pass React Query's
// `AbortSignal`: the request is long enough that leaving one in flight after
// the Advanced Workflow page is closed is a real cost, and the 120s budget is still
// honoured because the client arms the timeout alongside a caller's signal
// rather than instead of it.
export const fetchObjectInfo = async (providerId, options = {}) => {
    return await client.get(`/api/nodes/object_info?provider_id=${encodeURIComponent(providerId)}`, {
        ...options,
        timeout: 120000,
    });
};

// The capabilities answer comes from the same cached `object_info` the node
// palette reads, so it costs nothing the palette has not already paid - but
// the FIRST call still has to spin the provider up to introspect itself,
// which is the same 35-70s the object_info fetch can take. So the same
// generous timeout.
export const fetchProviderCapabilities = async (providerId, options = {}) => {
    return await client.get(
        `/api/nodes/capabilities?provider_id=${encodeURIComponent(providerId)}`,
        {
            ...options,
            timeout: 120000,
        }
    );
};
