/**
 * Date/time helpers for mixed backend timestamp formats.
 *
 * Backends can send either:
 * - UNIX timestamps (seconds)
 * - ISO strings with timezone ("...Z" or "+07:00")
 * - Naive datetime strings without timezone (interpreted as UTC)
 */

const HAS_EXPLICIT_TIMEZONE = /(Z|[+-]\d{2}:?\d{2})$/i;

/**
 * Parse mixed timestamp input into a Date in local time.
 *
 * Naive datetime strings are assumed to be UTC to avoid timezone drift
 * when users are not in UTC.
 */
export function parseGalleryDate(value) {
    if (value instanceof Date) {
        return value;
    }

    if (typeof value === 'number') {
        // Distinguish seconds vs milliseconds: values > 1e12 are milliseconds
        return new Date(value > 1e12 ? value : value * 1000);
    }

    if (typeof value === 'string') {
        const trimmed = value.trim();
        if (!trimmed) return new Date(0);

        // If no timezone exists, treat as UTC by appending Z.
        const normalized = HAS_EXPLICIT_TIMEZONE.test(trimmed) ? trimmed : `${trimmed}Z`;
        return new Date(normalized);
    }

    return new Date(0);
}

export function getItemTimelineDate(item) {
    if (!item || typeof item !== 'object') {
        return new Date(0);
    }

    return parseGalleryDate(item.timelineDate || item.date || item.mtime || 0);
}

export function getLocalDateKey(dateObj) {
    const year = dateObj.getFullYear();
    const month = String(dateObj.getMonth() + 1).padStart(2, '0');
    const day = String(dateObj.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

export function getLatestDate(dates = []) {
    let latest = new Date(0);

    dates.forEach((value) => {
        const parsed = parseGalleryDate(value);
        if (parsed > latest) latest = parsed;
    });

    return latest;
}

export function formatElapsed(startIso, endIso) {
    if (startIso === null || startIso === undefined || startIso === '') return null;
    const start = parseGalleryDate(startIso);
    const end = endIso !== null && endIso !== undefined && endIso !== ''
        ? parseGalleryDate(endIso)
        : new Date();
    const startMs = start.getTime();
    const endMs = end.getTime();
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return null;
    const elapsed = Math.floor((endMs - startMs) / 1000);
    if (elapsed < 0) return '0s';
    if (elapsed < 60) return `${elapsed}s`;
    if (elapsed < 3600) return `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;
    return `${Math.floor(elapsed / 3600)}h ${Math.floor((elapsed % 3600) / 60)}m`;
}

export function formatTimestamp(value) {
    const date = parseGalleryDate(value);
    return isNaN(date.getTime()) ? 'Unknown date' : date.toLocaleString();
}
