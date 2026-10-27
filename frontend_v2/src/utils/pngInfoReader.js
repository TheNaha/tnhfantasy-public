/**
 * Utility to extract PNG Info and generation parameters from image files.
 * Uses the backend's `/api/generate/interrogate` endpoint.
 */

export async function extractPngInfo(file) {
    if (!file) throw new Error('No file provided');

    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch('/api/generate/interrogate', {
        method: 'POST',
        body: formData,
    });

    if (!response.ok) {
        throw new Error(`Failed to extract metadata: ${response.statusText}`);
    }

    const data = await response.json();
    return {
        prompt: data.prompt || '',
        negativePrompt: data.negative_prompt || '',
        tags: data.tags || [],
        source: data.source,
        metadata: data.metadata || {},
    };
}
