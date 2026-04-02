import { describe, expect, it } from 'vitest';
import {
    extractProviderId,
    mergeContainerStatus,
    mergeProviderStats,
    mergeStatusCardReconciliation,
    mergeStatusCardStorage,
    normalizeStatusCard,
    normalizeReconciliationStatus,
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

    it('normalizes reconciliation status aliases used by worker events', () => {
        expect(normalizeReconciliationStatus('started')).toBe('reconciling');
        expect(normalizeReconciliationStatus('progress')).toBe('reconciling');
        expect(normalizeReconciliationStatus('running')).toBe('reconciling');
        expect(normalizeReconciliationStatus('completed')).toBe('completed');
        expect(normalizeReconciliationStatus(undefined)).toBe('idle');
    });

    it('normalizes legacy and canonical status-card fields into one shape', () => {
        const normalized = normalizeStatusCard({
            provider_id: 'provider-a',
            sync: {
                total_models: 2,
                stats: { installed: 1, pending: 1 },
            },
            storage: {
                total: 3,
                by_directory: { checkpoints: 3 },
            },
            runtime: {
                enabled: true,
            },
        });

        expect(normalized.model_sync.total_models).toBe(2);
        expect(normalized.sync.total_models).toBe(2);
        expect(normalized.storage.total).toBe(3);
        expect(normalized.reconciliation.status).toBe('idle');
        expect(normalized.deploy.status).toBe('idle');
        expect(normalized.diagnostics.warnings).toEqual([]);
    });

    it('merges reconciliation events into provider status cards', () => {
        const merged = mergeStatusCardReconciliation(
            {
                'provider-a': {
                    provider_id: 'provider-a',
                    reconciliation: {
                        status: 'idle',
                        stats: {},
                        active_downloads: [],
                    },
                },
            },
            {
                data: {
                    provider_id: 'provider-a',
                    status: 'started',
                    phase: 'downloading',
                    message: 'Syncing',
                    stats: { downloads_queued: 3 },
                    active_downloads: [{ name: 'model-a' }],
                },
            }
        );

        expect(merged['provider-a'].reconciliation.status).toBe('reconciling');
        expect(merged['provider-a'].reconciliation.phase).toBe('downloading');
        expect(merged['provider-a'].reconciliation.stats.downloads_queued).toBe(3);
        expect(merged['provider-a'].reconciliation.active_downloads).toHaveLength(1);
    });

    it('merges provider stats storage payload into provider status cards', () => {
        const merged = mergeStatusCardStorage(
            {
                'provider-a': {
                    provider_id: 'provider-a',
                    storage: {
                        total: 1,
                        by_directory: {
                            checkpoints: 1,
                        },
                    },
                },
            },
            {
                data: {
                    provider_id: 'provider-a',
                    stats: {
                        total: 3,
                        by_directory: {
                            loras: 2,
                        },
                    },
                },
            }
        );

        expect(merged['provider-a'].storage.total).toBe(3);
        expect(merged['provider-a'].storage.by_directory).toEqual({
            checkpoints: 1,
            loras: 2,
        });
    });
});
