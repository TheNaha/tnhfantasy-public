export function getOptimizedImageUrl(url, width = 450) {
    if (!url) return url;
    
    // Handle Civitai images
    if (url.includes('image.civitai.com')) {
        // If it already has a width parameter, replace it
        if (url.match(/\/width=\d+\//)) {
            return url.replace(/\/width=\d+\//, `/width=${width}/`);
        }
        // Otherwise inject width before the filename (last segment)
        const parts = url.split('/');
        const fileName = parts.pop();
        return [...parts, `width=${width}`, fileName].join('/');
    }

    // Handle local backend proxy previews
    if (url.includes('/api/v2/models/preview/')) {
        try {
            // It could be an absolute or relative URL
            const urlObj = new URL(url, window.location.origin);
            urlObj.searchParams.set('width', width);
            return url.startsWith('http') ? urlObj.toString() : urlObj.pathname + urlObj.search;
        } catch (e) {
            // Fallback for extremely malformed URLs
            const separator = url.includes('?') ? '&' : '?';
            return `${url}${separator}width=${width}`;
        }
    }
    
    // Fallback: return original url
    return url;
}
