import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
    addSessionAssets,
    createSession,
    deleteSession,
    detectSessions,
    listSessionAssets,
    listSessions,
    MAX_SESSIONS_PAGE_SIZE,
    mergeSession,
    removeSessionAsset,
    splitSession,
    updateSession,
} from '../api/sessionsApi';
import { reportError } from './useWorldVaultResource';

export const SESSIONS_ROOT_KEY = ['sessions'];

export const sessionsKeys = {
    all: SESSIONS_ROOT_KEY,
    list: (filters = {}) => ['sessions', 'list', filters],
    members: (sessionId) => ['sessions', 'detail', sessionId, 'assets'],
};

export const SESSIONS_PAGE_SIZE = MAX_SESSIONS_PAGE_SIZE;

/**
 * One invalidation root for every session read.
 *
 * Every query this module owns sits under `['sessions', ...]`, so a membership
 * edit — which rewrites `image_count`, `start_at`, `end_at` and `thumbnail` on
 * the row, and which session view mode groups by — is covered by invalidating
 * the root rather than by naming each key. `['gallery', ...]` is deliberately
 * not touched: a split or merge moves rows in `session_assets` only, and no
 * `assets` column or gallery group key depends on them.
 */
function invalidateSessions(queryClient) {
    queryClient.invalidateQueries({ queryKey: SESSIONS_ROOT_KEY });
}

/** Collapses an infinite-query result into a flat session list. */
export function flattenSessionPages(data) {
    if (!data?.pages) return [];
    return data.pages.flatMap((page) => page?.sessions || []);
}

/**
 * Paginated session list. The server pages with `limit`/`offset` and reports
 * `total`, so the next page starts where the previous one ended rather than
 * being inferred.
 */
export function useSessions(filters = {}, { enabled = true, pageSize = SESSIONS_PAGE_SIZE } = {}) {
    const limit = Math.max(1, Math.min(Number(pageSize) || SESSIONS_PAGE_SIZE, MAX_SESSIONS_PAGE_SIZE));

    return useInfiniteQuery({
        queryKey: sessionsKeys.list({ ...filters, limit }),
        queryFn: ({ pageParam, signal }) => listSessions({ ...filters, limit, offset: pageParam }, { signal }),
        initialPageParam: 0,
        getNextPageParam: (lastPage) => {
            if (!lastPage) return undefined;
            const consumed = (lastPage.offset ?? 0) + (lastPage.sessions?.length ?? 0);
            return consumed < (lastPage.total ?? 0) ? consumed : undefined;
        },
        staleTime: 5 * 60 * 1000,
        enabled,
    });
}

/** The members of one session, with generation metadata. */
export function useSessionAssets(sessionId, { enabled = true } = {}) {
    return useQuery({
        queryKey: sessionsKeys.members(sessionId),
        queryFn: () => listSessionAssets(sessionId),
        enabled: enabled && Boolean(sessionId),
        staleTime: 5 * 60 * 1000,
    });
}

export function useCreateSession() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data) => createSession(data),
        onSuccess: () => invalidateSessions(queryClient),
        onError: (error) => reportError('create session', error),
    });
}

export function useRenameSession() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, name, description }) => updateSession(id, { name, description }),
        onSuccess: () => invalidateSessions(queryClient),
        onError: (error) => reportError('rename session', error),
    });
}

export function useDeleteSession() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => deleteSession(id),
        onSuccess: () => invalidateSessions(queryClient),
        onError: (error) => reportError('delete session', error),
    });
}

export function useAddSessionAssets() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, assetIds }) => addSessionAssets(id, assetIds),
        onSuccess: () => invalidateSessions(queryClient),
        onError: (error) => reportError('add session assets', error),
    });
}

export function useRemoveSessionAsset() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, assetId }) => removeSessionAsset(id, assetId),
        onSuccess: () => invalidateSessions(queryClient),
        onError: (error) => reportError('remove session asset', error),
    });
}

export function useSplitSession() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, keepAssetIds }) => splitSession(id, keepAssetIds),
        onSuccess: () => invalidateSessions(queryClient),
        onError: (error) => reportError('split session', error),
    });
}

export function useMergeSession() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, targetSessionId }) => mergeSession(id, targetSessionId),
        onSuccess: () => invalidateSessions(queryClient),
        onError: (error) => reportError('merge session', error),
    });
}

/**
 * Runs the detector. Never call this from a mount effect, a render path or a
 * poll — the component that owns it is responsible for the explicit confirm
 * and for refusing a second submit while one is in flight.
 */
export function useDetectSessions() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (params) => detectSessions(params),
        onSuccess: () => invalidateSessions(queryClient),
        onError: (error) => reportError('detect sessions', error),
    });
}
