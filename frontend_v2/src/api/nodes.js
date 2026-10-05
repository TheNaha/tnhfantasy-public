import client from './client';

// object_info is served from the Modal worker through the backend proxy and
// can take 35-70s on cold/warm invocations — far beyond the 30s client default.
//
// `options` is forwarded so `useObjectInfo`'s queryFn can pass React Query's
// `AbortSignal`: the request is long enough that leaving one in flight after the
// Advanced Workflow page is closed is a real cost, and the 120s budget is still
// honoured because the client arms the timeout alongside a caller's signal
// rather than instead of it.
export const fetchObjectInfo = async (providerId, options = {}) => {
    return await client.get(`/api/nodes/object_info?provider_id=${encodeURIComponent(providerId)}`, {
        ...options,
        timeout: 120000,
    });
};
