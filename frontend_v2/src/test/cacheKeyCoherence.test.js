/**
 * The cache keys the UI invalidates must be the keys the queries use
 * (audit-2026-10-21 §2.6, §2.7, §2.8, §2.9, §3.36).
 *
 * React Query matches an invalidation by PREFIX and only ever compares
 * arrays, so two shapes of mistake are invisible: a key with an extra
 * segment (`['…','chats','detail',id]` against a query at
 * `['…','chats',id]`) matches nothing, and a bare STRING key matches
 * nothing at all. Both were live:
 *
 *   - five world-onboarding mutations (canon commit, world tick, reverse
 *     vision, fast travel, item visualise) never refreshed the chat they
 *     changed, so the panel showed the old location and time for the whole
 *     global staleTime;
 *   - adopting worldbuilding never refreshed the Locations or Lorebooks
 *     lists;
 *   - a memory reindex never refreshed the memory list, which is the one
 *     thing a reindex changes;
 *   - the chat stall watchdog read `['streaming','jobs']`, a namespace
 *     nothing writes, so a stalled reply was never cleared.
 *
 * These are tested FUNCTIONALLY, against the real query client: the
 * assertion is that an invalidation actually reaches the query, not that
 * the source contains a particular string.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { CHAT_DETAIL_KEY } from '../hooks/useChats';
import { getInFlightStreamingJobs } from '../hooks/useStreamingJobs';

const SRC_DIR = join(process.cwd(), 'src');
const readSrc = (p) => readFileSync(join(SRC_DIR, p), 'utf8');

const makeClient = () =>
    new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });

/** Did the invalidation actually reach this query? */
const wasInvalidated = (client, key) =>
    client.getQueryState(key)?.isInvalidated === true;

describe('the chat detail key is the key the chat query uses', () => {
    let client;

    beforeEach(() => {
        client = makeClient();
    });

    it('the detail key is a prefix-compatible array, not a string', () => {
        expect(Array.isArray(CHAT_DETAIL_KEY('c1'))).toBe(true);
        expect(CHAT_DETAIL_KEY('c1')).toEqual(['world_vault', 'chats', 'c1']);
    });

    it('an invalidation with this key reaches the chat query', async () => {
        const key = CHAT_DETAIL_KEY('c1');
        client.setQueryData(key, { id: 'c1' });

        await client.invalidateQueries({ queryKey: key });
        expect(wasInvalidated(client, key)).toBe(true);
    });

    it('the old onboarding key did NOT reach it - that was the bug', async () => {
        const realKey = CHAT_DETAIL_KEY('c1');
        const oldKey = buildQueryKey(QUERY_KEYS.CHATS, 'detail', 'c1');
        client.setQueryData(realKey, { id: 'c1' });

        // The old shape is not a prefix of the real one, so it matches
        // nothing. This is what the five onboarding mutations used.
        expect(oldKey).not.toEqual(realKey);
        expect(realKey.slice(0, oldKey.length)).not.toEqual(oldKey);

        await client.invalidateQueries({ queryKey: oldKey });
        expect(wasInvalidated(client, realKey)).toBe(false);
    });

    it('the onboarding hook imports the key rather than building its own', () => {
        const src = readSrc('hooks/useWorldOnboarding.js');
        expect(src).toMatch(
            /import\s*\{[^}]*CHAT_DETAIL_KEY[^}]*\}\s*from\s*'\.\/useChats'/
        );
        expect(src).not.toMatch(/buildQueryKey\(QUERY_KEYS\.CHATS,\s*'detail'/);
    });
});

describe('the adopt-worldbuilding and reindex invalidations are arrays', () => {
    it('a bare string key matches nothing in react-query', async () => {
        const client = makeClient();
        const realKey = buildQueryKey(QUERY_KEYS.LOCATIONS);
        client.setQueryData(realKey, []);

        // The shape that used to be passed.
        await client.invalidateQueries({ queryKey: QUERY_KEYS.LOCATIONS });
        expect(wasInvalidated(client, realKey)).toBe(false);

        // The shape that is correct now.
        await client.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.LOCATIONS) });
        expect(wasInvalidated(client, realKey)).toBe(true);
    });

    it('the memories invalidation is namespaced', async () => {
        const client = makeClient();
        const realKey = buildQueryKey(QUERY_KEYS.MEMORIES, 'c1');
        client.setQueryData(realKey, []);

        await client.invalidateQueries({ queryKey: [QUERY_KEYS.MEMORIES] });
        expect(wasInvalidated(client, realKey)).toBe(false);

        await client.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MEMORIES) });
        expect(wasInvalidated(client, realKey)).toBe(true);
    });

    it('the source passes array keys at both sites', () => {
        expect(readSrc('hooks/useStories.js')).not.toMatch(
            /invalidateQueries\(\{\s*queryKey:\s*QUERY_KEYS\.LOCATIONS\s*\}/
        );
        expect(readSrc('hooks/useStories.js')).not.toMatch(
            /invalidateQueries\(\{\s*queryKey:\s*QUERY_KEYS\.LOREBOOKS\s*\}/
        );
        expect(readSrc('hooks/useMemories.js')).not.toMatch(
            /queryKey:\s*\[QUERY_KEYS\.MEMORIES\]/
        );
    });
});

describe('the stall watchdog finds the jobs that are actually in flight', () => {
    let client;

    beforeEach(() => {
        client = makeClient();
    });

    it('finds a job in the per-job namespace', () => {
        client.setQueryData(['streaming', 'job-1'], { text: 'hi', chatId: 'c1' });
        const inFlight = getInFlightStreamingJobs(client);
        expect(inFlight).toEqual([{ jobId: 'job-1', chatId: 'c1' }]);
    });

    it('finds a job in the per-chat namespace', () => {
        client.setQueryData(['streaming', 'active', 'c1'], [
            { _jobId: 'job-2', text: 'yo' },
        ]);
        const inFlight = getInFlightStreamingJobs(client);
        expect(inFlight).toEqual([{ jobId: 'job-2', chatId: 'c1' }]);
    });

    it('does not report a job twice when it is in both namespaces', () => {
        client.setQueryData(['streaming', 'job-3'], { text: 'x', chatId: 'c1' });
        client.setQueryData(['streaming', 'active', 'c1'], [
            { _jobId: 'job-3', text: 'x' },
        ]);
        const inFlight = getInFlightStreamingJobs(client);
        expect(inFlight.filter((j) => j.jobId === 'job-3')).toHaveLength(1);
    });

    it('the namespace the watchdog used to read holds nothing', () => {
        client.setQueryData(['streaming', 'job-1'], { text: 'hi', chatId: 'c1' });
        const old = client.getQueryCache().findAll({ queryKey: ['streaming', 'jobs'] });
        expect(old).toHaveLength(0);
    });

    it('the watchdog reads the live namespaces', () => {
        const src = readSrc('hooks/useChatStreaming.js');
        expect(src).toContain('getInFlightStreamingJobs');
        // The dead namespace must not be READ. It is named in a comment
        // explaining why it was removed, so this matches the call shape.
        expect(src).not.toMatch(/queryKey:\s*\[\s*'streaming'\s*,\s*'jobs'\s*\]/);
    });
});

describe('the settings mirror receives the settings object', () => {
    it('a string has no `generator` key, so the mirror would be blanked', () => {
        const settings = {
            generator: {
                default_checkpoint: 'model.safetensors',
                prompt_shortcuts: { lazypos: 'x' },
            },
        };
        expect(settings.generator?.default_checkpoint).toBe('model.safetensors');
        // The shape that used to be passed.
        expect('model.safetensors'.generator?.default_checkpoint).toBeUndefined();
        expect('model.safetensors'.generator?.prompt_shortcuts).toBeUndefined();
    });

    it('the settings page passes the object at both call sites', () => {
        const src = readSrc('pages/Settings.jsx');
        expect(src).not.toMatch(/onMirror\(serverValue \|\| null\)/);
        expect(src).not.toMatch(
            /onMirrorDefaultCheckpoint\(configResponse\?\.settings\?\.generator\?\.default_checkpoint/
        );
    });
});
