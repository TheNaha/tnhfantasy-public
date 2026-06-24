import client from './client';

export const fetchObjectInfo = async (providerId) => {
    return await client.get(`/api/nodes/object_info?provider_id=${encodeURIComponent(providerId)}`);
};
