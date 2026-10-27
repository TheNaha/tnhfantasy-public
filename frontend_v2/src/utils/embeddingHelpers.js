/**
 * Utility functions for Textual Inversion Embeddings in prompts.
 *
 * Handles detection, parsing, toggling, and weight adjustments
 * for syntax like:
 *   - `embedding:lazypos`
 *   - `(embedding:lazypos:1.1)`
 *   - `embedding:lazyneg.safetensors`
 *   - `(embedding:lazyneg.safetensors:0.9)`
 */

const NEGATIVE_KEYWORDS = [
    'neg',
    'negative',
    'bad',
    'worst',
    'ugly',
    'deformed',
    'unrealistic',
    'fastneg',
    'lazyneg',
    'lazydn',
    'hand',
    'hands',
    'anatomy',
    'mutation',
    'lowres',
    'error',
    'blurry',
];

/**
 * Determine if an embedding is intended for the negative prompt based on its name.
 */
export function isNegativeEmbedding(name = '') {
    if (!name || typeof name !== 'string') return false;
    const lower = name.toLowerCase().replace(/[^a-z0-9]/g, '');
    return NEGATIVE_KEYWORDS.some((kw) => lower.includes(kw));
}

/**
 * Clean up leading/trailing/duplicate commas and extra spaces in a prompt.
 */
export function cleanPrompt(text = '') {
    if (!text || typeof text !== 'string') return '';
    return text
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
        .join(', ');
}

/**
 * Escape a string for use in a regular expression.
 */
function escapeRegex(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Base regex to match an embedding token in a prompt with optional weight and parentheses.
 * Captures:
 *  - Full token: `(embedding:name:1.1)` or `embedding:name`
 *  - Name: `name`
 *  - Weight: `1.1` (optional)
 */
export function parseActiveEmbeddings(promptText = '') {
    if (!promptText || typeof promptText !== 'string') return [];

    const results = [];
    const regex = /(?:\(\s*embedding:([a-zA-Z0-9_\-./]+?)(?::([0-9.]+))?\s*\)|embedding:([a-zA-Z0-9_\-./]+?)(?=[)\s,]|$))/g;
    let match;

    while ((match = regex.exec(promptText)) !== null) {
        const fullToken = match[0];
        const name = match[1] || match[3];
        const weight = match[2] ? parseFloat(match[2]) : 1.0;

        results.push({
            name,
            weight: Number.isFinite(weight) ? weight : 1.0,
            isWeighted: Boolean(match[2]),
            fullToken,
            index: match.index,
        });
    }

    return results;
}

/**
 * Check whether a prompt contains a specific embedding (by bare name or with extension).
 */
export function hasEmbedding(promptText = '', embeddingName = '') {
    if (!promptText || !embeddingName) return false;
    const active = parseActiveEmbeddings(promptText);
    const targetBase = embeddingName.replace(/\.[^/.]+$/, '').toLowerCase();

    return active.some((emb) => {
        const embBase = emb.name.replace(/\.[^/.]+$/, '').toLowerCase();
        return emb.name === embeddingName || embBase === targetBase;
    });
}

/**
 * Toggle an embedding on or off in a prompt string.
 * If present, removes it. If absent, appends it with default weight.
 */
export function toggleEmbeddingInPrompt(promptText = '', embeddingName = '', defaultWeight = 1.0) {
    if (!embeddingName) return promptText || '';
    const cleanText = promptText || '';

    // If already in prompt, remove all occurrences of this embedding
    if (hasEmbedding(cleanText, embeddingName)) {
        return removeEmbeddingFromPrompt(cleanText, embeddingName);
    }

    // Otherwise, append it
    const token = defaultWeight !== 1.0
        ? `(embedding:${embeddingName}:${defaultWeight.toFixed(1)})`
        : `embedding:${embeddingName}`;

    return cleanText.trim()
        ? cleanPrompt(`${cleanText.trim()}, ${token}`)
        : token;
}

/**
 * Remove an embedding from a prompt string.
 */
export function removeEmbeddingFromPrompt(promptText = '', embeddingName = '') {
    if (!promptText || !embeddingName) return promptText || '';

    const targetBase = escapeRegex(embeddingName.replace(/\.[^/.]+$/, ''));
    const targetFull = escapeRegex(embeddingName);
    const pattern = new RegExp(
        `(?:\\(\\s*embedding:(?:${targetFull}|${targetBase})(?:\\.[a-zA-Z0-9]+)?(?::[0-9.]+)?\\s*\\)|embedding:(?:${targetFull}|${targetBase})(?:\\.[a-zA-Z0-9]+)?(?=[)\\s,]|$))`,
        'gi'
    );

    const replaced = promptText.replace(pattern, '');
    return cleanPrompt(replaced);
}

/**
 * Adjust the weight of an existing embedding in a prompt, or add it with that weight.
 */
export function setEmbeddingWeightInPrompt(promptText = '', embeddingName = '', weight = 1.0) {
    if (!promptText || !embeddingName) return promptText || '';

    const roundedWeight = Math.round(weight * 10) / 10;
    const newWeightStr = roundedWeight.toFixed(1);
    const newToken = roundedWeight === 1.0
        ? `embedding:${embeddingName}`
        : `(embedding:${embeddingName}:${newWeightStr})`;

    const targetBase = escapeRegex(embeddingName.replace(/\.[^/.]+$/, ''));
    const targetFull = escapeRegex(embeddingName);
    const pattern = new RegExp(
        `(?:\\(\\s*embedding:(?:${targetFull}|${targetBase})(?:\\.[a-zA-Z0-9]+)?(?::[0-9.]+)?\\s*\\)|embedding:(?:${targetFull}|${targetBase})(?:\\.[a-zA-Z0-9]+)?(?=[)\\s,]|$))`,
        'gi'
    );

    if (pattern.test(promptText)) {
        return cleanPrompt(promptText.replace(pattern, newToken));
    }

    return promptText.trim()
        ? cleanPrompt(`${promptText.trim()}, ${newToken}`)
        : newToken;
}
