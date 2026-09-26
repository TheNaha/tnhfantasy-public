import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { normalizeReconciliationStatus as normalizeRealtimeReconciliationStatus } from '../utils/providerStatus';
import { unwrapPayload, normalizeObject } from '../utils/providerUtils';

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
        status: normalizeRealtimeReconciliationStatus(statusSource.status ?? source.status),
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

// Add model to providers
export function useAddModelToProviders() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({ directory, modelData, providerIds }) => {
            return api.post('/api/v2/providers/models/custom', {
                directory,
                model_data: modelData,
                provider_ids: providerIds,
            });
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['providers-page', 'providers'] });
            // These three keys did not exist, so nothing was ever refetched and
            // the generator's model dropdowns kept showing a stale list after a
            // model was added to a provider. Real keys are
            // ['installed-models', ...] (InstalledTab.jsx) and
            // ['model-directory', directory] (useModelDirectories.js);
            // both are invalidated by prefix. There is no ['provider-models']
            // query.
            queryClient.invalidateQueries({ queryKey: ['installed-models'] });
            queryClient.invalidateQueries({ queryKey: ['model-directory'] });
        },
    });
}
