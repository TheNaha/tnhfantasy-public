/**
 * Utility to extract PNG Info and generation parameters from image files.
 * Uses the backend's `/api/generate/interrogate` endpoint.
 */
import { api } from '../api/client';

export async function extractPngInfo(file) {
    if (!file) throw new Error('No file provided');

    const formData = new FormData();
    formData.append('file', file);

    const data = await api.post('/api/generate/interrogate', formData);
    return {
        prompt: data.prompt || '',
        negativePrompt: data.negative_prompt || '',
        tags: data.tags || [],
        source: data.source,
        metadata: data.metadata || {},
    };
}
