import client from './client';

// object_info is served from the Modal worker through the backend proxy and
// can take 35-70s on cold/warm invocations — far beyond the 30s client default.
export const fetchObjectInfo = async (providerId) => {
    return await client.get(`/api/nodes/object_info?provider_id=${encodeURIComponent(providerId)}`, {
        timeout: 120000,
    });
};
