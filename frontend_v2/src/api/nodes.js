import client from './client';

export const fetchObjectInfo = async (providerId) => {
    const response = await client.get(`/api/nodes/object_info`, {
        params: { provider_id: providerId }
    });
    return response.data;
};
