import { useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Play, Square, Settings, Rocket, Server, Circle, Loader2, FileText, RefreshCw, Edit2, Trash2, Power, PowerOff, AlertTriangle, RotateCcw } from 'lucide-react';
import SyncStatusBadge from './SyncStatusBadge';
import ReconciliationStatus from './ReconciliationStatus';
import { useProviderSyncStatus, useModalStats } from '../../hooks/useProviderModels';
import useReconciliationStore from '../../store/reconciliationStore';
import { providersApi } from '../../api';

const STATUS_COLORS = {
    active: 'text-green-400',
    running: 'text-green-400',
    stopped: 'text-gray-400',
    building: 'text-yellow-400',
    error: 'text-red-400',
};

export default function ProviderCard({
    provider,
    loading,
    onStart,
    onStop,
    onRestart,
    onDeploy,
    onReconcile,
    onResetStatus,
    onSetup,
    onConfigure,
    onEdit,
    onDelete,
    onToggleEnabled,
    providerFailures,
    jobsAssigned = 0
}) {
    const { data: syncStatus } = useProviderSyncStatus(provider.id);
    const { data: modalStats } = useModalStats(provider.id);
    // Get reconciliation state from global store (WebSocket updates happen globally now)
    const reconciliation = useReconciliationStore(state => state.activeReconciliations[provider.id]);
    const [showLogs, setShowLogs] = useState(false);
    const [showReconciliation, setShowReconciliation] = useState(false);
    const [logs, setLogs] = useState('');
    const [loadingLogs, setLoadingLogs] = useState(false);

    // Invalidate queries when reconciliation completes
    const queryClient = useQueryClient();
    
    useEffect(() => {
        // Invalidate sync status when reconciliation completes or fails
        if (reconciliation?.status === 'completed' || reconciliation?.status === 'failed') {
            queryClient.invalidateQueries(['providerSyncStatus', provider.id]);
        }
    }, [reconciliation?.status, provider.id, queryClient]);

    // Determine if this is a DIRECT mode provider (no container)
    const isDirect = !provider.container_config;

    // For DIRECT mode, use 'active' status; for containerized, use actual container status
    const status = isDirect ? 'active' : (provider.container_status || 'stopped');
    const statusColor = STATUS_COLORS[status] || 'text-gray-400';
    const isLoading = !!loading;

    const fetchLogs = async () => {
        setLoadingLogs(true);
        try {
            const data = await providersApi.getContainerLogs(provider.id);
            setLogs(data.logs || 'No logs available');
            setShowLogs(true);
        } catch (error) {
            console.error('Failed to fetch logs:', error);
            setLogs('Failed to fetch logs: ' + error.message);
            setShowLogs(true);
        } finally {
            setLoadingLogs(false);
        }
    };

    return (
        <div className={`bg-gray-800/50 backdrop-blur-sm border rounded-xl p-6 transition-all card-elevated hover:border-gray-500 ${provider.enabled ? 'border-gray-700' : 'border-gray-800 opacity-60'
            }`}>
            {/* Header */}
            <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3 flex-1">
                    <div className="p-2 bg-blue-500/10 rounded-lg border border-blue-500/20">
                        <Server className="text-blue-400" size={20} />
                    </div>
                    <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                            <h3 className="text-lg font-semibold text-white flex items-center gap-2">
                                {provider.id}
                                <Circle className={`${statusColor} fill-current`} size={8} />
                            </h3>
                            {provider.priority !== undefined && provider.priority !== null && (
                                <span className="text-xs px-2 py-0.5 bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded font-mono">
                                    P{provider.priority}
                                </span>
                            )}
                            <span className="text-xs px-2 py-0.5 bg-purple-500/10 text-purple-400 border border-purple-500/20 rounded font-mono" title="Jobs assigned (for least-connections)">
                                {jobsAssigned} jobs
                            </span>
                            {!provider.enabled && (
                                <span className="text-xs px-2 py-0.5 bg-gray-500/20 text-gray-400 border border-gray-500/30 rounded">
                                    Disabled
                                </span>
                            )}
                        </div>
                        <div className="text-sm text-gray-400">
                            Type: {provider.type || 'Unknown'}
                        </div>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    {/* Enable/Disable Toggle */}
                    <button
                        onClick={() => onToggleEnabled?.(provider.id, provider.enabled)}
                        className="p-2 bg-gray-700/50 hover:bg-gray-700 border border-gray-600 rounded-lg text-gray-300 hover:text-white transition-colors"
                        title={provider.enabled ? 'Disable Provider' : 'Enable Provider'}
                        aria-label={provider.enabled ? 'Disable Provider' : 'Enable Provider'}
                        aria-pressed={provider.enabled}
                    >
                        {provider.enabled ? <Power size={14} /> : <PowerOff size={14} />}
                    </button>

                    {/* Edit Button */}
                    <button
                        onClick={() => onEdit?.(provider)}
                        className="p-2 bg-gray-700/50 hover:bg-gray-700 border border-gray-600 rounded-lg text-gray-300 hover:text-white transition-colors"
                        title="Edit Provider"
                        aria-label="Edit Provider"
                    >
                        <Edit2 size={14} />
                    </button>

                    {/* Delete Button */}
                    <button
                        onClick={() => onDelete?.(provider.id)}
                        className="p-2 bg-gray-700/50 hover:bg-red-500/20 border border-gray-600 hover:border-red-500/50 rounded-lg text-gray-300 hover:text-red-400 transition-colors"
                        title="Delete Provider"
                        aria-label="Delete Provider"
                    >
                        <Trash2 size={14} />
                    </button>

                    {/* Status Badge */}
                    {isLoading && (
                        <Loader2 className="animate-spin text-blue-400" size={16} />
                    )}
                    <span className={`text-xs px-2 py-1 rounded-full ${status === 'running' || status === 'active'
                        ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                        : status === 'building'
                            ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
                            : status === 'error'
                                ? 'bg-red-500/20 text-red-400 border border-red-500/30'
                                : 'bg-gray-500/20 text-gray-400 border border-gray-500/30'
                        }`}>
                        {loading || (isDirect ? 'Direct' : status.charAt(0).toUpperCase() + status.slice(1))}
                    </span>
                </div>
            </div>

            {/* Connection Info */}
            {provider.container_config && (
                <div className="mb-4 pb-4 border-b border-gray-700">
                    <div className="grid grid-cols-2 gap-3 text-sm">
                        {provider.container_config.port && (
                            <div>
                                <span className="text-gray-500">Port:</span>
                                <span className="ml-2 text-gray-300">{provider.container_config.port}</span>
                            </div>
                        )}
                        {provider.credentials?.username && (
                            <div>
                                <span className="text-gray-500">User:</span>
                                <span className="ml-2 text-gray-300">{provider.credentials.username}</span>
                            </div>
                        )}
                        {provider.config?.app_name && (
                            <div>
                                <span className="text-gray-500">App:</span>
                                <span className="ml-2 text-gray-300">{provider.config.app_name}</span>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Sync Status / Reconciliation Progress */}
            <div className="mb-4">
                <SyncStatusBadge
                    providerId={provider.id}
                    stats={syncStatus?.stats}
                    modalStats={modalStats}
                    reconciliation={reconciliation}
                    onReconciliationClick={() => setShowReconciliation(true)}
                />
            </div>



            {/* Consecutive Failure Warning */}
            {providerFailures && providerFailures > 0 && (
                <div className="mt-4 px-4 py-3 bg-orange-500/15 border-l-4 border-orange-500 rounded-lg flex items-center gap-2 text-orange-400 text-sm font-medium">
                    <AlertTriangle size={16} />
                    {providerFailures} consecutive failures
                </div>
            )}

            {/* Actions */}
            <div className="flex items-center gap-2 mt-4 pt-4 border-t border-gray-700 flex-wrap">
                {(provider.type === 'modal' || provider.type === 'beam') && (
                    <button
                        onClick={onDeploy}
                        disabled={isLoading}
                        className="flex items-center gap-2 px-3 py-2 bg-purple-500/20 hover:bg-purple-500/30 text-purple-400 rounded-lg border border-purple-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        <Rocket size={14} />
                        Deploy
                    </button>
                )}

                {/* Only show container controls for containerized providers */}
                {!isDirect && (
                    <>
                        {status === 'running' ? (
                            <>
                                <button
                                    onClick={onStop}
                                    disabled={isLoading}
                                    className="flex items-center gap-2 px-3 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg border border-red-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    <Square size={14} />
                                    Stop
                                </button>
                                <button
                                    onClick={onRestart}
                                    disabled={isLoading}
                                    className="flex items-center gap-2 px-3 py-2 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded-lg border border-blue-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                                    title="Restart Container"
                                >
                                    <RefreshCw size={14} />
                                    Restart
                                </button>
                            </>
                        ) : (
                            <button
                                onClick={onStart}
                                disabled={isLoading}
                                className="flex items-center gap-2 px-3 py-2 bg-green-500/20 hover:bg-green-500/30 text-green-400 rounded-lg border border-green-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <Play size={14} />
                                Start
                            </button>
                        )}

                        <button
                            onClick={fetchLogs}
                            disabled={loadingLogs}
                            className="flex items-center gap-2 px-3 py-2 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded-lg border border-blue-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                            title="View Docker logs"
                        >
                            <FileText size={14} />
                            Logs
                        </button>
                    </>
                )}

                <button
                    onClick={onResetStatus}
                    disabled={isLoading}
                    className="flex items-center gap-2 px-3 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg border border-red-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                    title="Reset all file statuses - forces complete re-download on next reconcile"
                >
                    <RotateCcw size={14} />
                    Reset
                </button>

                <button
                    onClick={onReconcile}
                    disabled={isLoading}
                    className="flex items-center gap-2 px-3 py-2 bg-orange-500/20 hover:bg-orange-500/30 text-orange-400 rounded-lg border border-orange-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                    title="Sync models with provider storage"
                >
                    <RefreshCw size={14} />
                    Reconcile
                </button>

                <button
                    onClick={onSetup}
                    disabled={isLoading}
                    className="flex items-center gap-2 px-3 py-2 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded-lg border border-blue-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                    title="Initialize Modal directories and download default models"
                >
                    <Rocket size={14} />
                    Setup
                </button>

                <button
                    onClick={onConfigure}
                    disabled={isLoading}
                    className="flex items-center gap-2 px-3 py-2 bg-gray-700/50 hover:bg-gray-700 text-gray-300 rounded-lg border border-gray-600 transition-colors text-sm ml-auto disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <Settings size={14} />
                    Configure
                </button>
            </div>

            {/* Logs Modal */}
            {showLogs && (
                <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={() => setShowLogs(false)}>
                    <div className="bg-gray-800 rounded-xl border border-gray-700 max-w-4xl w-full max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
                        <div className="border-b border-gray-700 px-6 py-4 flex items-center justify-between">
                            <h3 className="text-lg font-semibold text-white">Container Logs - {provider.id}</h3>
                            <button
                                onClick={() => setShowLogs(false)}
                                className="text-gray-400 hover:text-white transition-colors"
                            >
                                ×
                            </button>
                        </div>
                        <div className="p-4 overflow-y-auto custom-scrollbar flex-1">
                            <pre className="text-xs text-gray-300 font-mono bg-gray-900 p-4 rounded border border-gray-700 whitespace-pre-wrap break-words">
                                {logs}
                            </pre>
                        </div>
                        <div className="border-t border-gray-700 px-6 py-3 flex items-center justify-end gap-3">
                            <button
                                onClick={fetchLogs}
                                className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors"
                            >
                                Refresh
                            </button>
                            <button
                                onClick={() => setShowLogs(false)}
                                className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded transition-colors"
                            >
                                Close
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Reconciliation Status Modal */}
            {showReconciliation && (
                <ReconciliationStatus
                    providerId={provider.id}
                    onClose={() => setShowReconciliation(false)}
                />
            )}
        </div>
    );
}
