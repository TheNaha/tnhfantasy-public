import { api } from './client';

const worldVaultApi = {
    characters: {
        list: () => api.get('/api/v2/characters'),
        get: (id) => api.get(`/api/v2/characters/${id}`),
        create: (data) => api.post('/api/v2/characters', data),
        update: (id, data) => api.put(`/api/v2/characters/${id}`, data),
        delete: (id) => api.delete(`/api/v2/characters/${id}`),
    },
    chats: {
        list: () => api.get('/api/v2/chats'),
        get: (id) => api.get(`/api/v2/chats/${id}`),
        create: (data) => api.post('/api/v2/chats', data),
        update: (id, data) => api.put(`/api/v2/chats/${id}`, data),
        delete: (id) => api.delete(`/api/v2/chats/${id}`),
        listMessages: (chatId) => api.get(`/api/v2/chats/${chatId}/messages`),
        sendMessage: (chatId, message) => api.post(`/api/v2/chats/${chatId}/messages`, message),
        deleteMessage: (chatId, msgId) => api.delete(`/api/v2/chats/${chatId}/messages/${msgId}`),
    },
    lorebooks: {
        list: () => api.get('/api/v2/lorebooks'),
        get: (id) => api.get(`/api/v2/lorebooks/${id}`),
        create: (data) => api.post('/api/v2/lorebooks', data),
        update: (id, data) => api.put(`/api/v2/lorebooks/${id}`, data),
        delete: (id) => api.delete(`/api/v2/lorebooks/${id}`),
        search: (id, q) => api.get(`/api/v2/lorebooks/${id}/search`, { params: { q } }),
        listEntries: (id) => api.get(`/api/v2/lorebooks/${id}/entries`),
        createEntry: (id, data) => api.post(`/api/v2/lorebooks/${id}/entries`, data),
        updateEntry: (id, eid, data) => api.put(`/api/v2/lorebooks/${id}/entries/${eid}`, data),
        deleteEntry: (id, eid) => api.delete(`/api/v2/lorebooks/${id}/entries/${eid}`),
    },
    scenarios: {
        list: () => api.get('/api/v2/scenarios'),
        get: (id) => api.get(`/api/v2/scenarios/${id}`),
        create: (data) => api.post('/api/v2/scenarios', data),
        update: (id, data) => api.put(`/api/v2/scenarios/${id}`, data),
        delete: (id) => api.delete(`/api/v2/scenarios/${id}`),
    },
    stories: {
        list: () => api.get('/api/v2/stories'),
        get: (id) => api.get(`/api/v2/stories/${id}`),
        create: (data) => api.post('/api/v2/stories', data),
        update: (id, data) => api.put(`/api/v2/stories/${id}`, data),
        delete: (id) => api.delete(`/api/v2/stories/${id}`),
        listChapters: (storyId) => api.get(`/api/v2/stories/${storyId}/chapters`),
        createChapter: (storyId, data) => api.post(`/api/v2/stories/${storyId}/chapters`, data),
        getChapter: (storyId, cid) => api.get(`/api/v2/stories/${storyId}/chapters/${cid}`),
        updateChapter: (storyId, cid, data) => api.put(`/api/v2/stories/${storyId}/chapters/${cid}`, data),
        deleteChapter: (storyId, cid) => api.delete(`/api/v2/stories/${storyId}/chapters/${cid}`),
        continue: (storyId, cid, data) => api.post(`/api/v2/stories/${storyId}/chapters/${cid}/continue`, data),
        addBeat: (storyId, cid, data) => api.post(`/api/v2/stories/${storyId}/chapters/${cid}/beats`, data),
    },
};

export default worldVaultApi;
