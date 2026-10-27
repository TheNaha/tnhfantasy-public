import { useState, useMemo } from 'react';
import { RefreshCw, RotateCcw, Server, Download, Circle, Loader2, Search, Check, AlertCircle, ArrowDownToLine } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { useProviderReconciliationState } from '../../../hooks/useProvidersPageData';
import { providersApi } from '../../../api';
import { formatBytes, KB } from '../../../utils/bytes';
import ReconciliationStatus from '../ReconciliationStatus';
import { ActionBtn, Notice } from './Shared';
import { STATUS_TONE, statusDotClass, humanize, capitalize } from './utils';

export default function SyncTab({
    modelSync, storage, storageLoaded, reconciliation, capabilities, loading,
    onReconcile, onQuickSync, onResetStatus, providerId,
}) {
    const queryClient = useQueryClient();
    const dbModels = modelSync.total_models || 0;
    const storageModels = storage.total || 0;
    const reconciliationStatus = reconciliation.status || 'idle';
    const storageEntries = Object.entries(storage.by_directory || {});
    const modelDelta = Math.abs(dbModels - storageModels);

    const [inventorySearch, setInventorySearch] = useState('');
    const [statusFilter, setStatusFilter] = useState('all');
    const [directoryFilter, setDirectoryFilter] = useState('all');
    const [downloadingIds, setDownloadingIds] = useState(new Set());

    const barStyles = [
        'from-cyan-500 to-blue-500',
        'from-fuchsia-500 to-violet-500',
        'from-emerald-500 to-teal-500',
        'from-amber-500 to-orange-500',
        'from-rose-500 to-pink-500',
    ];

    const { reconciliationState } = useProviderReconciliationState(providerId);
    
    // Use realtime state if available, otherwise fallback to provider.reconciliation_state
    const currentRecon = reconciliationState || reconciliation;
    const isReconciling = currentRecon.status === 'reconciling';
    const stats = currentRecon.stats || {};
    const queued = stats.downloads_queued || 0;
    const completed = stats.downloads_completed || 0;
    const failed = stats.downloads_failed || 0;
    const progress = queued > 0 ? ((completed + failed) / queued) * 100 : 0;

    // Fetch live manifest showing sync status of every library model on this provider
    const { data: manifestData, isLoading: manifestLoading, refetch: refetchManifest } = useQuery({
        queryKey: ['provider-sync-manifest', providerId],
        queryFn: () => providersApi.getSyncManifest(providerId),
        enabled: !!providerId,
        staleTime: 15_000,
    });

    const models = useMemo(() => manifestData?.models || [], [manifestData]);
    const missingCount = useMemo(() => models.filter(m => m.needs_download || m.status === 'missing').length, [models]);
    const readyCount = useMemo(() => models.filter(m => m.status === 'ready').length, [models]);

    const uniqueDirectories = useMemo(() => {
        const dirs = new Set();
        models.forEach(m => { if (m.directory) dirs.add(m.directory); });
        return Array.from(dirs).sort();
    }, [models]);

    const filteredModels = useMemo(() => {
        return models.filter(m => {
            const q = inventorySearch.trim().toLowerCase();
            const matchesSearch = !q || (
                (m.model_name && m.model_name.toLowerCase().includes(q)) ||
                (m.version_name && m.version_name.toLowerCase().includes(q)) ||
                (m.storage_filename && m.storage_filename.toLowerCase().includes(q))
            );

            const isMissing = m.needs_download || m.status === 'missing';
            const matchesStatus = (
                statusFilter === 'all' ||
                (statusFilter === 'missing' && isMissing) ||
                (statusFilter === 'ready' && m.status === 'ready') ||
                (statusFilter === 'downloading' && (m.status === 'downloading' || downloadingIds.has(m.file_id))) ||
                (statusFilter === 'failed' && m.status === 'failed')
            );

            const matchesDir = directoryFilter === 'all' || m.directory === directoryFilter;
            return matchesSearch && matchesStatus && matchesDir;
        });
    }, [models, inventorySearch, statusFilter, directoryFilter, downloadingIds]);

    const handleDownloadOne = async (fileId, modelName) => {
        setDownloadingIds(prev => new Set(prev).add(fileId));
        try {
            await providersApi.downloadModels(providerId, { file_ids: [fileId] });
            toast.success(`Queued download for ${modelName || 'model'}`);
            queryClient.invalidateQueries({ queryKey: ['provider-sync-manifest', providerId] });
        } catch (err) {
            toast.error(`Download failed: ${err.message}`);
            setDownloadingIds(prev => {
                const next = new Set(prev);
                next.delete(fileId);
                return next;
            });
        }
    };

    const handleDownloadAllMissing = async () => {
        const missingFileIds = models
            .filter(m => m.needs_download || m.status === 'missing' || m.status === 'failed')
            .map(m => m.file_id);

        if (missingFileIds.length === 0) {
            toast.success('All models are already up to date!');
            return;
        }

        try {
            await providersApi.downloadModels(providerId, { file_ids: missingFileIds });
            toast.success(`Queued ${missingFileIds.length} missing models for download`);
            setDownloadingIds(new Set(missingFileIds));
            queryClient.invalidateQueries({ queryKey: ['provider-sync-manifest', providerId] });
        } catch (err) {
            toast.error(`Failed to trigger downloads: ${err.message}`);
        }
    };

    return (
        <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 mb-4">
                <div className="rounded-xl border border-blue-500/15 bg-blue-500/8 p-4">
                    <div className="mb-2 flex items-center justify-between">
                        <span className="text-xs uppercase tracking-wide text-blue-200/75">DB Sync</span>
                        <Server size={14} className="text-blue-300" />
                    </div>
                    <div className="text-xl font-semibold text-white">{dbModels} models</div>
                </div>

                <div className="rounded-xl border border-purple-500/15 bg-purple-500/8 p-4">
                    <div className="mb-2 flex items-center justify-between">
                        <span className="text-xs uppercase tracking-wide text-purple-200/75">Provider Storage</span>
                        <Download size={14} className="text-purple-300" />
                    </div>
                    <div className="text-xl font-semibold text-white">{storageModels} models</div>
                </div>

                <div className="rounded-xl border border-white/[0.08] bg-gray-900/60 p-4 flex flex-col justify-between relative overflow-hidden">
                    <div className="mb-2 flex items-center justify-between relative z-10">
                        <span className="text-xs uppercase tracking-wide text-gray-500">Reconciliation</span>
                        <Circle className={`fill-current ${statusDotClass(STATUS_TONE[reconciliationStatus])} ${isReconciling ? 'animate-pulse' : ''}`} size={8} />
                    </div>
                    <div className="text-lg font-medium text-white relative z-10">
                        {isReconciling && currentRecon.phase ? capitalize(currentRecon.phase) : humanize(reconciliationStatus)}
                    </div>
                    {isReconciling && queued > 0 && (
                        <div className="absolute bottom-0 left-0 h-1 bg-blue-500/30 w-full">
                            <div className="h-full bg-blue-500 transition-all duration-300" style={{ width: `${progress}%` }} />
                        </div>
                    )}
                </div>
            </div>

            {isReconciling && (
                <div className="mb-4">
                    <ReconciliationStatus providerId={providerId} inline={true} />
                </div>
            )}

            <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 p-4">
                <div className="mb-3 flex items-center justify-between gap-4">
                    <span className="text-xs uppercase tracking-wide text-gray-500">Directory Breakdown</span>
                    <span className="text-xs text-gray-500">{storageLoaded ? `${storageEntries.length} directories` : 'Loading…'}</span>
                </div>

                {storageLoaded ? (
                    storageEntries.length > 0 ? (
                        <div className="flex flex-wrap gap-2">
                            {storageEntries.map(([dir, count]) => (
                                <span
                                    key={dir}
                                    className="rounded-full border border-gray-700 bg-gray-800/70 px-2.5 py-1 text-xs text-gray-300"
                                >
                                    {capitalize(dir)}: {count}
                                </span>
                            ))}
                        </div>
                    ) : (
                        <div className="text-sm text-gray-500">No storage data yet</div>
                    )
                ) : (
                    <div className="flex items-center gap-2 text-sm text-gray-500">
                        <Loader2 size={14} className="animate-spin" />
                        Loading storage data…
                    </div>
                )}
            </div>

            {dbModels === 0 && storageModels > 0 && !isReconciling && (
                <Notice
                    tone="yellow"
                    message={`Provider storage contains ${storageModels} models, but DB sync has not been registered yet. Click Reconcile to synchronize models with the database.`}
                />
            )}
            {dbModels > 0 && modelDelta > 0 && !isReconciling && reconciliationStatus !== 'completed' && (
                <Notice
                    tone="yellow"
                    message={`Model count mismatch detected: DB reports ${dbModels} while provider storage reports ${storageModels}. Run reconciliation to align state.`}
                />
            )}

            <div className="flex flex-wrap gap-2 mb-4 mt-4">
                {capabilities.reconcile && (
                    <>
                        <ActionBtn onClick={onReconcile} disabled={Boolean(loading) || isReconciling} tone="orange" icon={RefreshCw} label={isReconciling ? "Reconciling..." : "Reconcile"} />
                        <ActionBtn onClick={onQuickSync} disabled={Boolean(loading) || isReconciling} tone="blue" icon={RefreshCw} label="Quick Sync" />
                    </>
                )}
                {capabilities.reset_status && (
                    <ActionBtn onClick={onResetStatus} disabled={Boolean(loading) || isReconciling} tone="red" icon={RotateCcw} label="Reset DB Sync" />
                )}
            </div>

            {storageEntries.length > 0 && (
                <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 p-4 mb-4">
                    <div className="text-xs font-medium uppercase tracking-wide text-gray-500 mb-3">Storage by Directory</div>
                    <div className="space-y-2">
                        {storageEntries.map(([dir, count], index) => {
                            const total = storageModels || 1;
                            const pct = Math.round((count / total) * 100);
                            const barTone = barStyles[index % barStyles.length];
                            return (
                                <div key={dir}>
                                    <div className="flex items-center justify-between text-xs mb-1">
                                        <span className="text-gray-300">{capitalize(dir)}</span>
                                        <span className="text-gray-500">{count} ({pct}%)</span>
                                    </div>
                                    <div className="h-1.5 rounded-full bg-gray-800 overflow-hidden">
                                        <div
                                            className={`h-full rounded-full bg-gradient-to-r ${barTone}`}
                                            style={{ width: `${pct}%` }}
                                        />
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* Model Inventory & Sync Matrix */}
            <div className="rounded-xl border border-white/[0.08] bg-gray-900/50 p-4 space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div>
                        <h4 className="text-sm font-bold text-white flex items-center gap-2">
                            <span>Provider Model Inventory</span>
                            <span className="text-xs font-normal text-gray-400">
                                ({readyCount}/{models.length} ready)
                            </span>
                        </h4>
                        <p className="text-xs text-gray-400 mt-0.5">
                            Detailed catalog of models and their synchronization status on this provider
                        </p>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                        {missingCount > 0 && (
                            <button
                                onClick={handleDownloadAllMissing}
                                disabled={Boolean(loading) || isReconciling}
                                className="px-3 py-1.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-bold flex items-center gap-1.5 shadow-md transition-all active:scale-95"
                                title="Queue download of all missing models to this provider"
                            >
                                <ArrowDownToLine size={13} />
                                <span>Download Missing ({missingCount})</span>
                            </button>
                        )}
                        <button
                            onClick={() => refetchManifest()}
                            disabled={manifestLoading}
                            className="p-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg transition-colors border border-white/5"
                            title="Refresh Model Inventory"
                        >
                            <RefreshCw size={13} className={manifestLoading ? 'animate-spin' : ''} />
                        </button>
                    </div>
                </div>

                {/* Filters */}
                <div className="flex flex-wrap gap-2.5 items-center">
                    <div className="relative flex-1 min-w-[180px]">
                        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                        <input
                            type="text"
                            placeholder="Filter models or files..."
                            value={inventorySearch}
                            onChange={(e) => setInventorySearch(e.target.value)}
                            className="w-full bg-black/40 border border-white/10 rounded-lg pl-8 pr-3 py-1.5 text-xs text-white placeholder-gray-500 outline-none focus:border-blue-500/50"
                        />
                    </div>

                    <select
                        value={statusFilter}
                        onChange={(e) => setStatusFilter(e.target.value)}
                        className="bg-black/40 border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-gray-300 outline-none focus:border-blue-500/50"
                    >
                        <option value="all">All Statuses ({models.length})</option>
                        <option value="missing">Missing Only ({missingCount})</option>
                        <option value="ready">Ready ({readyCount})</option>
                        <option value="downloading">Downloading</option>
                        <option value="failed">Failed</option>
                    </select>

                    {uniqueDirectories.length > 0 && (
                        <select
                            value={directoryFilter}
                            onChange={(e) => setDirectoryFilter(e.target.value)}
                            className="bg-black/40 border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-gray-300 outline-none focus:border-blue-500/50"
                        >
                            <option value="all">All Directories</option>
                            {uniqueDirectories.map(dir => (
                                <option key={dir} value={dir}>{capitalize(dir)}</option>
                            ))}
                        </select>
                    )}
                </div>

                {/* Inventory Table */}
                {manifestLoading && models.length === 0 ? (
                    <div className="py-8 text-center text-gray-500 flex items-center justify-center gap-2">
                        <Loader2 size={16} className="animate-spin text-blue-400" />
                        <span className="text-xs">Loading provider model catalog...</span>
                    </div>
                ) : filteredModels.length === 0 ? (
                    <div className="py-8 text-center text-gray-500 text-xs border border-dashed border-white/5 rounded-xl">
                        {models.length === 0
                            ? 'No registered models found in database manifest.'
                            : 'No models matched the current filters.'}
                    </div>
                ) : (
                    <div className="max-h-80 overflow-y-auto custom-scrollbar border border-white/5 rounded-xl divide-y divide-white/5 bg-black/20">
                        {filteredModels.map((item) => {
                            const isItemDownloading = item.status === 'downloading' || downloadingIds.has(item.file_id);
                            const isItemReady = item.status === 'ready' && !isItemDownloading;
                            const isItemFailed = item.status === 'failed';

                            return (
                                <div key={item.file_id || item.storage_filename} className="p-2.5 flex items-center justify-between gap-3 hover:bg-white/[0.02] transition-colors">
                                    <div className="min-w-0 flex-1">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="text-xs font-bold text-white truncate max-w-xs" title={item.model_name}>
                                                {item.model_name}
                                            </span>
                                            {item.version_name && (
                                                <span className="text-2xs px-1.5 py-0.5 rounded bg-white/5 text-gray-300 border border-white/10">
                                                    {item.version_name}
                                                </span>
                                            )}
                                            {item.directory && (
                                                <span className="text-2xs px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-300 border border-blue-500/20">
                                                    {item.directory}
                                                </span>
                                            )}
                                        </div>
                                        <div className="text-2xs text-gray-500 truncate mt-0.5 font-mono">
                                            {item.storage_filename} • {formatBytes((item.size_kb || 0) * KB)}
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-2 shrink-0">
                                        {isItemDownloading ? (
                                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-semibold bg-blue-500/20 text-blue-300 border border-blue-500/30 animate-pulse">
                                                <Loader2 size={10} className="animate-spin" />
                                                <span>Downloading</span>
                                            </span>
                                        ) : isItemReady ? (
                                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                                                <Check size={11} strokeWidth={3} />
                                                <span>Ready</span>
                                            </span>
                                        ) : isItemFailed ? (
                                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-semibold bg-red-500/15 text-red-400 border border-red-500/30">
                                                <AlertCircle size={11} />
                                                <span>Failed</span>
                                            </span>
                                        ) : (
                                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-semibold bg-amber-500/15 text-amber-300 border border-amber-500/30">
                                                <span>Missing</span>
                                            </span>
                                        )}

                                        {(!isItemReady && !isItemDownloading) && (
                                            <button
                                                onClick={() => handleDownloadOne(item.file_id, item.model_name)}
                                                className="px-2 py-1 bg-blue-600/80 hover:bg-blue-500 text-white rounded text-2xs font-medium flex items-center gap-1 transition-colors active:scale-95 shadow-sm"
                                                title={`Download ${item.model_name} to this provider`}
                                            >
                                                <Download size={11} />
                                                <span>Download</span>
                                            </button>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </>
    );
}
