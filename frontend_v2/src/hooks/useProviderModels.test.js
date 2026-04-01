import { describe, expect, it } from 'vitest';
import {
    extractProviderId,
    mergeModalStats,
    mergeProviderSyncStatus,
    normalizeModalStats,
    normalizeProviderSyncStatus,
} from './useProviderModels';

describe('useProviderModels helpers', () => {
    it('normalizes reconciliation payloads from wrapped websocket data', () => {
        const payload = {
            data: {
                provider_id: 'provider-1',
                reconciliation: {
                    status: 'completed',
                    phase: 'completed',
                    stats: { downloads_completed: 3 },
                    active_downloads: [{ name: 'model.safetensors' }],
                },
            },
        };

        const normalized = normalizeProviderSyncStatus(payload);

        expect(extractProviderId(payload)).toBe('provider-1');
        expect(normalized.status).toBe('completed');
        expect(normalized.phase).toBe('completed');
        expect(normalized.stats.downloads_completed).toBe(3);
        expect(normalized.active_downloads).toHaveLength(1);
    });

    it('merges reconciliation patches without dropping existing stats', () => {
        const current = {
            provider_id: 'provider-1',
            status: 'reconciling',
            stats: { downloads_queued: 8, downloads_completed: 2 },
            active_downloads: [{ name: 'model-a' }],
        };

        const merged = mergeProviderSyncStatus(current, {
            data: {
                provider_id: 'provider-1',
                status: 'completed',
                phase: 'completed',
            },
        });

        expect(merged.status).toBe('completed');
        expect(merged.stats.downloads_queued).toBe(8);
        expect(merged.stats.downloads_completed).toBe(2);
        expect(merged.active_downloads).toHaveLength(1);
    });

    it('patches sync-status model counts from file status updates without refetching', () => {
        const merged = mergeProviderSyncStatus(
            {
                provider_id: 'provider-1',
                total_models: 2,
                stats: {
                    installed: 0,
                    pending: 2,
                    downloading: 0,
                    failed: 0,
                },
                models: [
                    {
                        file_id: 11,
                        provider_status: { status: 'pending', storage_path: null, size_bytes: null, error_message: null },
                    },
                    {
                        file_id: 12,
                        provider_status: { status: 'pending', storage_path: null, size_bytes: null, error_message: null },
                    },
                ],
            },
            {
                data: {
                    provider_id: 'provider-1',
                    file_id: 11,
                    status: 'ready',
                    storage_path: 'models/checkpoints/test.safetensors',
                },
            }
        );

        expect(merged.stats.installed).toBe(1);
        expect(merged.stats.pending).toBe(1);
        expect(merged.models[0].provider_status.status).toBe('installed');
        expect(merged.models[0].provider_status.storage_path).toBe('models/checkpoints/test.safetensors');
    });

    it('normalizes modal stats updates from provider.stats_update events', () => {
        const payload = {
            data: {
                provider_id: 'provider-1',
                stats: {
                    total: 5,
                    by_directory: {
                        checkpoints: 3,
                    },
                },
            },
        };

        expect(normalizeModalStats(payload)).toEqual({
            provider_id: 'provider-1',
            total: 5,
            by_directory: {
                checkpoints: 3,
            },
        });
    });

    it('merges modal stats updates without losing directory breakdowns', () => {
        const merged = mergeModalStats(
            {
                provider_id: 'provider-1',
                total: 2,
                by_directory: {
                    checkpoints: 1,
                },
            },
            {
                data: {
                    provider_id: 'provider-1',
                    stats: {
                        by_directory: {
                            loras: 2,
                        },
                    },
                },
            }
        );

        expect(merged.total).toBe(2);
        expect(merged.by_directory).toEqual({
            checkpoints: 1,
            loras: 2,
        });
    });

    it('aliases normalized reconciliation storage totals for old and new field names', () => {
        const normalized = normalizeProviderSyncStatus({
            provider_id: 'provider-1',
            status: 'reconciling',
            stats: {
                total_models_in_storage: 7,
            },
        });

        expect(normalized.stats.total_models_in_storage).toBe(7);
        expect(normalized.stats.total_models_in_modal).toBe(7);
    });
});
