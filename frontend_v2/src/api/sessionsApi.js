// Sessions API client - curatable groups of related images.
//
// Every payload below is shaped by backend_v2/api/routes/world_vault/sessions.py:
// SessionOut (list items), SessionDetailOut (create/split halves, adds
// `asset_ids`), SessionMembersOut (GET /assets), SessionDetectOut (detect).

import api from './client';

const API_BASE = '/api/v2/sessions';

/** Server-side ceiling for `limit` (MAX_LIST_LIMIT in sessions.py). */
export const MAX_SESSIONS_PAGE_SIZE = 100;

/**
 * The shared client aborts at 30s. The detector is a full columnar pass over
 * `assets` — on this deployment (~16.4k rows) a legitimate run can outlast that
 * and be reported as a 408 while the server is still working, so detect gets
 * its own budget.
 */
const DETECT_TIMEOUT = 5 * 60 * 1000;

/**
 * Every call takes a trailing `options` and forwards it to the client.
 *
 * That is how a React Query `queryFn` passes the `AbortSignal` from its context.
 * `listSessions` is the panel's search — keyed per keystroke — so without it
 * every superseded query ran to completion and then raced the one that
 * superseded it into the cache.
 */

/**
 * List live sessions, newest activity first. Returns
 * `{ sessions, total, limit, offset }`.
 */
export async function listSessions({
    workspace,
    auto_detected,
    locked,
    search,
    limit,
    offset,
} = {}, options = {}) {
    return api.get(API_BASE, {
        params: { workspace, auto_detected, locked, search, limit, offset },
        ...options,
    });
}

/** One session plus its member ids (SessionDetailOut). */
export async function getSession(id, options = {}) {
    return api.get(`${API_BASE}/${id}`, options);
}

/** Create a hand-made session. `name` is required; it comes back `locked: true`. */
export async function createSession(data, options = {}) {
    return api.post(API_BASE, data, options);
}

/** Rename or re-describe. A patch always locks the session against the detector. */
export async function updateSession(id, data, options = {}) {
    return api.patch(`${API_BASE}/${id}`, data, options);
}

/** Soft delete — the images themselves are untouched. */
export async function deleteSession(id, options = {}) {
    return api.delete(`${API_BASE}/${id}`, options);
}

/** Add members. Returns `{ added, already_members, session }`. */
export async function addSessionAssets(id, assetIds, options = {}) {
    return api.post(`${API_BASE}/${id}/assets`, { asset_ids: assetIds }, options);
}

/** Remove a single member. */
export async function removeSessionAsset(id, assetId, options = {}) {
    return api.delete(`${API_BASE}/${id}/assets/${encodeURIComponent(assetId)}`, options);
}

/**
 * Split the complement of `keepAssetIds` into a new session. Returns
 * `{ session, created }`, both with their own `asset_ids`.
 */
export async function splitSession(id, keepAssetIds, options = {}) {
    return api.post(`${API_BASE}/${id}/split`, { keep_asset_ids: keepAssetIds }, options);
}

/** Merge this session into `targetSessionId`, which is returned. */
export async function mergeSession(id, targetSessionId, options = {}) {
    return api.post(`${API_BASE}/${id}/merge`, { target_session_id: targetSessionId }, options);
}

/**
 * Run the detector. Returns
 * `{ min_size, time_gap_minutes, dry_run, max_assets, summary }`.
 * Expensive and writing — call it from an explicit user action only.
 */
export async function detectSessions({ min_size, time_gap_minutes, dry_run } = {}, options = {}) {
    return api.post(
        `${API_BASE}/detect`,
        { min_size, time_gap_minutes, dry_run },
        { ...options, timeout: DETECT_TIMEOUT },
    );
}

/**
 * The members of a session with generation metadata. Returns
 * `{ session_id, assets, total, limit, offset }`.
 */
export async function listSessionAssets(id, { limit, offset } = {}, options = {}) {
    return api.get(`${API_BASE}/${id}/assets`, { params: { limit, offset }, ...options });
}