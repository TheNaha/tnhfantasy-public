/**
 * Character card compatibility helpers.
 *
 * Covers the SillyTavern card surface the frontend depends on:
 *   - accepting `.png` and `.json` card files on import
 *   - normalizing the import response into `{ character, compatibility }`
 *   - building export URLs/filenames for the V2 / V3 / default formats
 *
 * The import endpoint answers with a bare character dict (legacy behavior) or
 * with an envelope that also carries a compatibility report. Every shape and
 * key alias produced by the backend is normalized here so the UI never has to
 * branch on which response it received, and a missing report degrades to
 * "nothing reported" instead of breaking the import flow.
 */

import { ApiError } from './client';
import { CARD_MAX_BYTES, assertUploadAllowed } from './upload';

export { CARD_MAX_BYTES };

/** Extensions accepted by the card import endpoint. */
export const CARD_FILE_EXTENSIONS = ['png', 'json', 'charx'];

/** Value for the `accept` attribute of the card file input. */
export const CARD_ACCEPT = '.png,.json,.charx,image/png,application/json,application/zip';

/** Export format id that defers to the backend default (V2 PNG). */
export const DEFAULT_CARD_EXPORT_FORMAT = 'default';

export const CARD_EXPORT_FORMATS = [
    {
        id: DEFAULT_CARD_EXPORT_FORMAT,
        label: 'Default PNG',
        extension: 'png',
        description: 'PNG carrying both the legacy chara and V3 ccv3 chunks. Widest compatibility.',
    },
    {
        id: 'v2',
        label: 'V2 PNG',
        extension: 'png',
        description: 'Explicit Character Card V2 PNG export.',
    },
    {
        id: 'v3',
        label: 'V3 PNG',
        extension: 'png',
        description: 'Canonical V3 spec in the ccv3 chunk.',
    },
    {
        id: 'json',
        label: 'JSON',
        extension: 'json',
        description: 'Plain JSON card. No avatar image.',
    },
    {
        id: 'charx',
        label: 'CHARX',
        extension: 'charx',
        description: 'ZIP card with card.json and available avatar assets.',
    },
];

const EXPORT_SUFFIXES = {
    v2: '_v2.png',
    v3: '_v3.png',
    json: '.json',
    charx: '.charx',
    default: '_v2.png',
};

function extensionOf(name) {
    const parts = String(name || '').toLowerCase().split('.');
    return parts.length > 1 ? parts.pop() : '';
}

/** True when the file looks like a card the backend can import. */
export function isCharacterCardFile(file) {
    return CARD_FILE_EXTENSIONS.includes(extensionOf(file?.name));
}

/**
 * Reject obvious client-side mistakes before spending a round trip. The
 * backend stays authoritative; its error payload always wins when it disagrees.
 */
export function assertCharacterCardFile(file) {
    if (!file) {
        throw new ApiError('No file selected', 0, { code: 'UPLOAD_INVALID', field: 'file' });
    }
    if (!isCharacterCardFile(file)) {
        throw new ApiError('Character cards must be a .png, .json, or .charx file', 0, {
            code: 'UNSUPPORTED_FILE_TYPE',
            field: 'file',
        });
    }
    assertUploadAllowed(file, 'card');
    return true;
}

function toEntry(value) {
    if (value == null) return null;
    if (typeof value === 'string' || typeof value === 'number') {
        const label = String(value).trim();
        return label ? { id: label, label, detail: '' } : null;
    }
    if (typeof value !== 'object') return null;

    const label = value.name || value.field || value.key || value.path || value.label;
    const detail = value.reason || value.note || value.detail || value.type || value.value || '';
    if (!label && !detail) return null;

    const text = String(label || detail);
    return {
        id: text,
        label: String(label || detail),
        detail: label ? String(detail || '') : '',
    };
}

function toEntries(value) {
    if (value == null) return [];
    const list = Array.isArray(value) ? value : [value];
    const seen = new Set();
    const out = [];
    for (const item of list) {
        const entry = toEntry(item);
        if (!entry || seen.has(entry.id)) continue;
        seen.add(entry.id);
        out.push(entry);
    }
    return out;
}

function pick(source, keys) {
    for (const key of keys) {
        const value = source?.[key];
        if (value !== undefined && value !== null) return value;
    }
    return undefined;
}

function truthyFlag(value) {
    if (value === undefined || value === null) return null;
    if (typeof value === 'string') return ['true', '1', 'yes'].includes(value.toLowerCase());
    return Boolean(value);
}

const COMPAT_KEYS = ['compatibility', 'import_report', 'importReport', 'report', 'card_compatibility'];
const LOST_KEYS = ['lost_fields', 'lostFields', 'lost_metadata', 'lostMetadata', 'dropped_fields', 'unmapped_fields'];
const PRESERVED_KEYS = [
    'preserved_fields',
    'preservedFields',
    'preserved_metadata',
    'preservedMetadata',
    'kept_fields',
    'stored_metadata',
];
const WARNING_KEYS = ['warnings', 'warning_messages', 'messages'];
const INERT_KEYS = [
    'preserved_but_inert',
    'preservedButInert',
    'inert_fields',
    'inertFields',
    'preserved_not_executed',
];

/**
 * Normalize a backend compatibility report.
 *
 * Returns null-safe defaults so callers can render unconditionally:
 * `{ format, spec, specVersion, warnings, lost, preserved, inert,
 *    lorebookConverted, unknownExtensionsPreserved, hasReport, lossless }`
 *
 * `inert` is the bucket that matters and used to be missing: features the
 * card carried that are preserved and re-exported but NOT acted on here (a
 * SillyTavern `regex_scripts` extension, a lorebook entry's `position`). With
 * `lost` empty and no notion of `inert`, the report computed `lossless` and
 * the modal printed "Fully compatible. All reported card data was imported."
 */
export function normalizeCardCompatibility(raw) {
    const empty = {
        format: '',
        spec: '',
        specVersion: '',
        warnings: [],
        lost: [],
        preserved: [],
        inert: [],
        lorebookConverted: null,
        unknownExtensionsPreserved: null,
        hasReport: false,
        lossless: true,
    };
    if (!raw || typeof raw !== 'object') return empty;

    const lost = toEntries(pick(raw, LOST_KEYS));
    const preserved = toEntries(pick(raw, PRESERVED_KEYS));
    const warnings = toEntries(pick(raw, WARNING_KEYS));
    const inert = toEntries(pick(raw, INERT_KEYS));

    return {
        format: String(pick(raw, ['format', 'card_format', 'kind']) || ''),
        spec: String(pick(raw, ['spec', 'spec_name']) || ''),
        specVersion: String(pick(raw, ['spec_version', 'specVersion', 'version']) || ''),
        warnings,
        lost,
        preserved,
        inert,
        lorebookConverted: truthyFlag(pick(raw, ['lorebook_converted', 'lorebookConverted', 'lorebook_created'])),
        unknownExtensionsPreserved: truthyFlag(
            pick(raw, ['unknown_extensions_preserved', 'unknownExtensionsPreserved', 'extensions_preserved'])
        ),
        hasReport: true,
        // A card that preserved features it cannot execute is NOT lossless —
        // the data is safe, but the behaviour is not the same. The report says
        // so, and the modal says so.
        lossless: lost.length === 0 && warnings.length === 0 && inert.length === 0,
    };
}

/**
 * Normalize the import response.
 *
 * Accepts the bare character dict, `{ character, compatibility }`,
 * `{ card, import_report }` and `{ data: { ... } }` style envelopes.
 */
export function normalizeCardImportResult(raw) {
    const compatibilitySource =
        (raw && typeof raw === 'object' && pick(raw, COMPAT_KEYS)) || undefined;

    let character = null;
    if (raw && typeof raw === 'object') {
        const nested = raw.character || raw.card || raw.data;
        if (nested && typeof nested === 'object') {
            character = nested.character && typeof nested.character === 'object' ? nested.character : nested;
        } else if (raw.id || raw.name) {
            character = raw;
        }
    }

    const compatibility = normalizeCardCompatibility(
        compatibilitySource || (character ? pick(character, COMPAT_KEYS) : undefined)
    );

    return { character, compatibility };
}

/** Export URL for a character; `default` sends no `format` query param. */
export function buildCharacterCardExportUrl(characterId, format = DEFAULT_CARD_EXPORT_FORMAT) {
    if (!characterId) return null;
    const base = `/api/v2/characters/${characterId}/export`;
    if (!format || format === DEFAULT_CARD_EXPORT_FORMAT) return base;
    return `${base}?format=${encodeURIComponent(format)}`;
}

/** Download filename for an export, preserving the legacy `<name>_v2.png` default. */
export function buildCharacterCardExportFilename(character, format = DEFAULT_CARD_EXPORT_FORMAT) {
    const safe = String(character?.name || '')
        .replace(/[^a-z0-9]+/gi, '_')
        .replace(/^_+|_+$/g, '') || 'character';
    const suffix = EXPORT_SUFFIXES[format] || EXPORT_SUFFIXES[DEFAULT_CARD_EXPORT_FORMAT];
    return `${safe}${suffix}`;
}

/** Human-readable label for an export format id. */
export function cardExportFormatLabel(format) {
    if (!format || format === DEFAULT_CARD_EXPORT_FORMAT) return 'Default PNG';
    return CARD_EXPORT_FORMATS.find((f) => f.id === format)?.label || 'Default PNG';
}

/** `chara_card_v3` -> `V3`, used for compact card provenance badges. */
export function cardSpecLabel(spec, specVersion) {
    if (!spec) return '';
    const match = String(spec).match(/v(\d+)/i);
    const base = match ? `V${match[1]}` : String(spec);
    return specVersion ? `${base} · ${specVersion}` : base;
}

/**
 * Summarize a character's `card_metadata` residual blob into the groups the
 * backend preserves, so the UI can show which non-column card data survived an
 * import (and therefore survives re-export). Grouping mirrors the backend's
 * import report: `root`, then `data` minus the nested groups it reports.
 */
export function preservedCardMetadataGroups(cardMetadata) {
    if (!cardMetadata || typeof cardMetadata !== 'object') return [];

    const data = cardMetadata.data;
    const groups = [];
    const addGroup = (label, value) => {
        const keys = Object.keys(value || {});
        if (keys.length) groups.push({ id: label, label, keys });
    };

    const nested = new Set(['extensions', 'assets', 'character_book']);
    addGroup('root', cardMetadata.root);
    addGroup(
        'data',
        Object.fromEntries(Object.entries(data || {}).filter(([key]) => !nested.has(key)))
    );
    addGroup('data.extensions', data?.extensions);
    addGroup('data.assets', data?.assets);
    if (data?.character_book) {
        groups.push({ id: 'data.character_book', label: 'data.character_book', keys: ['embedded lorebook'] });
    }
    return groups;
}
