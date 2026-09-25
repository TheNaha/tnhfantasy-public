const MAX_SCAN_CHARS = 20000;

/**
 * Trims a context blob down to the tail the backend would actually scan.
 * Keeps the inspector cheap on long chats.
 */
export function clipContextText(text, maxChars = MAX_SCAN_CHARS) {
    if (typeof text !== 'string' || !text) return '';
    const trimmed = text.trim();
    if (trimmed.length <= maxChars) return trimmed;
    return trimmed.slice(trimmed.length - maxChars);
}

/** Entries without trigger keys are always injected by the backend. */
export function isAlwaysOnEntry(entry) {
    if (!entry) return false;
    const keys = Array.isArray(entry.keys) ? entry.keys : [];
    return keys.every((key) => typeof key !== 'string' || !key.trim());
}

/**
 * Returns the trigger keys of `entry` that occur in `text`.
 * Case-insensitive substring matching, mirroring services/rag_pipeline.py.
 */
export function matchEntryKeys(entry, text) {
    if (!entry || !text) return [];
    const keys = Array.isArray(entry.keys) ? entry.keys : [];
    const haystack = text.toLowerCase();
    return keys.filter((key) => {
        if (typeof key !== 'string') return false;
        const needle = key.trim().toLowerCase();
        if (!needle) return false;
        return haystack.includes(needle);
    });
}

/**
 * Decides whether a lorebook entry would be injected for the given context text.
 * Returns `{ active, alwaysOn, matchedKeys }`.
 */
export function evaluateEntry(entry, text) {
    if (!entry) return { active: false, alwaysOn: false, matchedKeys: [] };
    if (isAlwaysOnEntry(entry)) return { active: true, alwaysOn: true, matchedKeys: [] };
    const matchedKeys = matchEntryKeys(entry, text);
    return { active: matchedKeys.length > 0, alwaysOn: false, matchedKeys };
}

/**
 * Splits entries into those the model would currently see and those it would not.
 * `limit` mirrors the backend per-lorebook scan cap.
 */
export function selectActivatedEntries(entries, text, { limit = 50 } = {}) {
    const list = Array.isArray(entries) ? entries : [];
    const context = clipContextText(text);
    const activated = [];
    const idle = [];

    for (const entry of list) {
        const result = evaluateEntry(entry, context);
        if (result.active) {
            activated.push({ ...entry, _alwaysOn: result.alwaysOn, _matchedKeys: result.matchedKeys });
        } else {
            idle.push(entry);
        }
        if (activated.length >= limit) break;
    }

    return { activated, idle, total: list.length };
}

/** Aggregate counts used for collapsed summary rows. */
export function summarizeActivation(entries, text) {
    const { activated, total } = selectActivatedEntries(entries, text);
    return { active: activated.length, total };
}
