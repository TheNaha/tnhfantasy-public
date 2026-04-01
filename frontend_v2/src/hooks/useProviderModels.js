import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import * as ws from '../api/websocket';

function unwrapPayload(payload) {
    return payload?.data ?? payload ?? {};
}

function normalizeObject(value) {
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

export function extractProviderId(payload) {
    const source = unwrapPayload(payload);
    return source.provider_id ?? source.providerId ?? source.id ?? null;
}

export function normalizeProviderSyncStatus(payload) {
    const source = unwrapPayload(payload);
    const statusSource = normalizeObject(source.reconciliation ?? source.sync_status ?? source);
    const statsSource = normalizeObject(statusSource.stats ?? source.stats);
    const normalizedStats = {
        ...statsSource,
        total_models_in_modal: statsSource.total_models_in_modal ?? statsSource.total_models_in_storage ?? 0,
        total_models_in_storage: statsSource.total_models_in_storage ?? statsSource.total_models_in_modal ?? 0,
    };

    return {
        ...source,
        ...statusSource,
        provider_id: statusSource.provider_id ?? source.provider_id ?? source.providerId ?? null,
        status: statusSource.status ?? source.status ?? 'idle',
        phase: statusSource.phase ?? source.phase ?? (
            statusSource.status === 'completed'
                ? 'completed'
                : statusSource.status === 'failed'
                    ? 'failed'
                    : null
        ),
        message: statusSource.message ?? source.message ?? '',
        stats: normalizedStats,
        current_download: statusSource.current_download ?? source.current_download ?? null,
        active_downloads: Array.isArray(statusSource.active_downloads)
            ? statusSource.active_downloads
            : Array.isArray(source.active_downloads)
                ? source.active_downloads
                : [],
        errors: Array.isArray(statusSource.errors)
            ? statusSource.errors
            : Array.isArray(source.errors)
                ? source.errors
                : [],
    };
}

export function mergeProviderSyncStatus(current, patch) {
    const currentStatus = normalizeProviderSyncStatus(current);
    const patchSource = unwrapPayload(patch);
    const fileId = patchSource.file_id ?? patchSource.fileId ?? null;
    const patchStatus = patchSource.provider_status?.status ?? patchSource.status ?? null;
    const normalizedPatchStatus = patchStatus === 'ready' ? 'installed' : patchStatus;
    let nextModels = currentStatus.models;
    let nextStats = currentStatus.stats;

    if (fileId && Array.isArray(currentStatus.models) && normalizedPatchStatus) {
        const previousModel = currentStatus.models.find((model) => model.file_id === fileId);
        const previousStatus = previousModel?.provider_status?.status;

        if (previousModel && previousStatus !== normalizedPatchStatus) {
            nextModels = currentStatus.models.map((model) => (
                model.file_id === fileId
                    ? {
                        ...model,
                        provider_status: {
                            ...model.provider_status,
                            status: normalizedPatchStatus,
                            storage_path: patchSource.storage_path ?? model.provider_status?.storage_path ?? null,
                            size_bytes: patchSource.size_bytes ?? model.provider_status?.size_bytes ?? null,
                            error_message: patchSource.error_message ?? model.provider_status?.error_message ?? null,
                        },
                    }
                    : model
            ));

            const statuses = ['installed', 'pending', 'downloading', 'failed'];
            nextStats = { ...currentStatus.stats };
            if (statuses.includes(previousStatus)) {
                nextStats[previousStatus] = Math.max((nextStats[previousStatus] ?? 0) - 1, 0);
            }
            if (statuses.includes(normalizedPatchStatus)) {
                nextStats[normalizedPatchStatus] = (nextStats[normalizedPatchStatus] ?? 0) + 1;
            }
        }
    }

    return normalizeProviderSyncStatus({
        ...currentStatus,
        ...patchSource,
        models: nextModels,
        total_models: Array.isArray(nextModels) ? nextModels.length : currentStatus.total_models,
        stats: patchSource.stats ?? nextStats,
        active_downloads: patchSource.active_downloads ?? currentStatus.active_downloads,
        errors: patchSource.errors ?? currentStatus.errors,
        current_download: patchSource.current_download ?? currentStatus.current_download,
        message: patchSource.message ?? currentStatus.message,
    });
}

export const normalizeReconciliationStatus = normalizeProviderSyncStatus;

export function normalizeModalStats(payload) {
    const source = unwrapPayload(payload);
    const statsSource = normalizeObject(source.modal_stats ?? source.stats ?? source);
    const byDirectory = normalizeObject(statsSource.by_directory ?? statsSource.byDirectory);

    return {
        ...statsSource,
        provider_id: statsSource.provider_id ?? source.provider_id ?? source.providerId ?? null,
        total: Number(statsSource.total ?? statsSource.total_models ?? statsSource.total_models_in_modal ?? 0),
        by_directory: byDirectory,
    };
}

export function mergeModalStats(current, patch) {
    const currentStats = normalizeModalStats(current);
    const patchSource = unwrapPayload(patch);
    const patchStats = normalizeModalStats(patchSource);
    const rawPatchStats = normalizeObject(patchSource.modal_stats ?? patchSource.stats);
    const hasExplicitTotal = patchSource.total !== undefined
        || patchSource.total_models !== undefined
        || patchSource.total_models_in_modal !== undefined
        || rawPatchStats.total !== undefined
        || rawPatchStats.total_models !== undefined
        || rawPatchStats.total_models_in_modal !== undefined;
    const mergedDirectory = {
        ...currentStats.by_directory,
        ...patchStats.by_directory,
    };
    const mergedStats = {
        ...currentStats,
        ...patchStats,
        total: hasExplicitTotal ? patchStats.total : currentStats.total,
        by_directory: mergedDirectory,
    };

    return normalizeModalStats({
        ...currentStats,
        ...patchSource,
        stats: mergedStats,
    });
}

/**
 * Hook for provider sync status with WebSocket updates
 * Replaces polling with WebSocket event subscription
 */
export function useProviderSyncStatus(providerId) {
    const queryClient = useQueryClient();

    useEffect(() => {
        if (!providerId) return;

        ws.subscribe('model');

        const unsubscribe = ws.on(ws.EventTypes.MODEL_STATUS_UPDATE, (event) => {
            const eventProviderId = extractProviderId(event);
            if (eventProviderId === providerId) {
                queryClient.setQueryData(['providerSyncStatus', providerId], (current) => (
                    current ? mergeProviderSyncStatus(current, event) : normalizeProviderSyncStatus(event)
                ));
            }
        });

        return () => {
            unsubscribe();
            ws.unsubscribe('model');
        };
    }, [providerId, queryClient]);

    return useQuery({
        queryKey: ['providerSyncStatus', providerId],
        queryFn: async () => normalizeProviderSyncStatus(await api.get(`/api/providers/${providerId}/sync-status`)),
        enabled: !!providerId,
        staleTime: 30000,
        refetchOnWindowFocus: true,
    });
}

/**
 * Hook for Modal stats with reduced polling (backend caches this)
 * WebSocket events can trigger cache updates when stats change
 */
export function useModalStats(providerId) {
    const queryClient = useQueryClient();

    useEffect(() => {
        if (!providerId) return;

        ws.subscribe('provider');

        const unsubscribe = ws.on(ws.EventTypes.PROVIDER_STATS_UPDATE, (event) => {
            const eventProviderId = extractProviderId(event);
            if (eventProviderId === providerId) {
                queryClient.setQueryData(['modalStats', providerId], (current) => (
                    current ? mergeModalStats(current, event) : normalizeModalStats(event)
                ));
            }
        });

        return () => {
            unsubscribe();
            ws.unsubscribe('provider');
        };
    }, [providerId, queryClient]);

    return useQuery({
        queryKey: ['modalStats', providerId],
        queryFn: async () => normalizeModalStats(await api.get(`/api/providers/${providerId}/modal-stats`)),
        enabled: !!providerId,
        staleTime: 60000,
        refetchInterval: 60000,
        refetchOnWindowFocus: true,
    });
}

// Fetch models for a provider
export function useProviderModels(providerId, status = null) {
    return useQuery({
        queryKey: ['providerModels', providerId, status],
        queryFn: async () => {
            let url = `/api/providers/${providerId}/models`;
            if (status) {
                url += `?status=${status}`;
            }
            return api.get(url);
        },
        enabled: !!providerId,
    });
}

// Remove model from provider
export function useRemoveModelFromProvider() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({ directory, modelName, providerId }) => {
            return api.delete(
                `/api/providers/${providerId}/models?directory=${encodeURIComponent(directory)}&filename=${encodeURIComponent(modelName)}`
            );
        },
        onSuccess: (_, { providerId }) => {
            queryClient.invalidateQueries({ queryKey: ['providerModels', providerId] });
        },
    });
}

// Add model to providers
export function useAddModelToProviders() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({ directory, modelData, providerIds }) => {
            return api.post('/api/providers/models/custom', {
                directory,
                model_data: modelData,
                provider_ids: providerIds,
            });
        },
        onSuccess: (_, { providerIds }) => {
            providerIds.forEach((providerId) => {
                queryClient.invalidateQueries({ queryKey: ['providerModels', providerId] });
            });
        },
    });
}
