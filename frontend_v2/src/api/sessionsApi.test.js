import { beforeEach, describe, expect, it, vi } from 'vitest';

const getMock = vi.hoisted(() => vi.fn());
const postMock = vi.hoisted(() => vi.fn());
const patchMock = vi.hoisted(() => vi.fn());
const deleteMock = vi.hoisted(() => vi.fn());

vi.mock('./client', () => ({
    default: { get: getMock, post: postMock, patch: patchMock, delete: deleteMock },
}));

import {
    addSessionAssets,
    createSession,
    deleteSession,
    detectSessions,
    getSession,
    listSessionAssets,
    listSessions,
    mergeSession,
    removeSessionAsset,
    splitSession,
    updateSession,
} from './sessionsApi';

describe('sessionsApi', () => {
    beforeEach(() => {
        [getMock, postMock, patchMock, deleteMock].forEach((mock) => mock.mockReset());
        [getMock, postMock, patchMock, deleteMock].forEach((mock) => mock.mockResolvedValue({}));
    });

    it('lists sessions with every filter forwarded verbatim', () => {
        listSessions({
            workspace: 'main',
            auto_detected: false,
            locked: true,
            search: 'portrait',
            limit: 24,
            offset: 48,
        });

        expect(getMock).toHaveBeenCalledWith('/api/v2/sessions', {
            params: {
                workspace: 'main',
                auto_detected: false,
                locked: true,
                search: 'portrait',
                limit: 24,
                offset: 48,
            },
        });
    });

    it('omits unset filters rather than sending them as undefined', () => {
        listSessions();
        expect(getMock).toHaveBeenCalledWith('/api/v2/sessions', {
            params: {
                workspace: undefined,
                auto_detected: undefined,
                locked: undefined,
                search: undefined,
                limit: undefined,
                offset: undefined,
            },
        });
    });

    it('reads one session and its members', () => {
        getSession('abc');
        listSessionAssets('abc', { limit: 200, offset: 0 });

        expect(getMock).toHaveBeenNthCalledWith(1, '/api/v2/sessions/abc');
        expect(getMock).toHaveBeenNthCalledWith(2, '/api/v2/sessions/abc/assets', {
            params: { limit: 200, offset: 0 },
        });
    });

    it('creates with the body unchanged', () => {
        createSession({ name: 'Winter run', asset_ids: ['a1', 'a2'] });
        expect(postMock).toHaveBeenCalledWith('/api/v2/sessions', {
            name: 'Winter run',
            asset_ids: ['a1', 'a2'],
        });
    });

    it('patches with PATCH, not PUT, so a partial edit is not a full replace', () => {
        updateSession('abc', { name: 'Renamed' });
        expect(patchMock).toHaveBeenCalledWith('/api/v2/sessions/abc', { name: 'Renamed' });
    });

    it('soft deletes', () => {
        deleteSession('abc');
        expect(deleteMock).toHaveBeenCalledWith('/api/v2/sessions/abc');
    });

    it('adds and removes members', () => {
        addSessionAssets('abc', ['a1', 'a2']);
        removeSessionAsset('abc', 'a/2026/09/27/a1.png');

        expect(postMock).toHaveBeenCalledWith('/api/v2/sessions/abc/assets', {
            asset_ids: ['a1', 'a2'],
        });
        expect(deleteMock).toHaveBeenCalledWith('/api/v2/sessions/abc/assets/a%2F2026%2F09%2F27%2Fa1.png');
    });

    it('splits by posting keep_asset_ids, not a move list', () => {
        splitSession('abc', ['keep-1', 'keep-2']);
        expect(postMock).toHaveBeenCalledWith('/api/v2/sessions/abc/split', {
            keep_asset_ids: ['keep-1', 'keep-2'],
        });
    });

    it('merges by posting target_session_id on the source session', () => {
        mergeSession('abc', 'target-1');
        expect(postMock).toHaveBeenCalledWith('/api/v2/sessions/abc/merge', {
            target_session_id: 'target-1',
        });
    });

    it('posts detect to the sessions-detect route with its own timeout', () => {
        detectSessions({ dry_run: false });

        expect(postMock).toHaveBeenCalledWith(
            '/api/v2/sessions/detect',
            { min_size: undefined, time_gap_minutes: undefined, dry_run: false },
            { timeout: 300000 },
        );
    });

    it('passes detector parameters through when given', () => {
        detectSessions({ min_size: 3, time_gap_minutes: 45, dry_run: true });
        expect(postMock).toHaveBeenCalledWith(
            '/api/v2/sessions/detect',
            { min_size: 3, time_gap_minutes: 45, dry_run: true },
            { timeout: 300000 },
        );
    });
});
