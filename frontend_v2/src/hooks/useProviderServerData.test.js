import { describe, expect, it } from 'vitest';
import {
    extractProviderId,
    mergeContainerStatus,
    mergeProviderStats,
    normalizeProvidersPayload,
    unwrapEventData,
} from './useProviderServerData';

describe('useProviderServerData helpers', () => {
    it('normalizes providers payload from array and object shapes', () => {
        expect(normalizeProvidersPayload([{ id: 'provider-1' }])).toEqual([{ id: 'provider-1' }]);
        expect(normalizeProvidersPayload({ providers: [{ id: 'provider-2' }] })).toEqual([{ id: 'provider-2' }]);
        expect(normalizeProvidersPayload({})).toEqual([]);
    });

    it('unwraps and extracts provider ids from wrapped websocket payloads', () => {
        const payload = { data: { provider_id: 'provider-a' } };
        expect(unwrapEventData(payload)).toEqual({ provider_id: 'provider-a' });
        expect(extractProviderId(payload)).toBe('provider-a');
    });

    it('merges single provider container status updates', () => {
        const merged = mergeContainerStatus(
            {
                'provider-a': { status: 'running', running: true, healthy: true },
            },
            {
                provider_id: 'provider-a',
                status: 'stopped',
                running: false,
            }
        );

        expect(merged['provider-a']).toEqual({
            status: 'stopped',
            running: false,
            healthy: true,
        });
    });

    it('replaces statuses on batch updates', () => {
        const merged = mergeContainerStatus(
            { 'provider-a': { status: 'running' } },
            {
                statuses: {
                    'provider-b': { status: 'starting', running: true, healthy: false },
                },
            }
        );

        expect(merged).toEqual({
            'provider-b': { status: 'starting', running: true, healthy: false },
        });
    });

    it('merges provider stats updates into existing load balancer payload', () => {
        const merged = mergeProviderStats(
            {
                config: { strategy: 'round-robin' },
                stats: { total_providers: 1, provider_stats: [] },
            },
            {
                data: {
                    provider_id: 'provider-a',
                    stats: { total_providers: 2 },
                },
            }
        );

        expect(merged.config.strategy).toBe('round-robin');
        expect(merged.stats.total_providers).toBe(2);
    });
});
