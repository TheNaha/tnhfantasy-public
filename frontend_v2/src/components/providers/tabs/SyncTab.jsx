import { HardDrive, RefreshCw, RotateCcw, Server, Download, Circle, Loader2 } from 'lucide-react';
import ReconciliationStatus from '../ReconciliationStatus';
import { ActionBtn, Notice } from './Shared';
import { STATUS_TONE, statusDotClass, humanize, capitalize } from './utils';

export default function SyncTab({
    modelSync, storage, storageLoaded, reconciliation, capabilities, loading,
    onReconcile, onResetStatus, providerId,
}) {
    const dbModels = modelSync.total_models || 0;
    const storageModels = storage.total || 0;
    const reconciliationStatus = reconciliation.status || 'idle';
    const storageEntries = Object.entries(storage.by_directory || {});
    const modelDelta = Math.abs(dbModels - storageModels);

    const barStyles = [
        'from-cyan-500 to-blue-500',
        'from-fuchsia-500 to-violet-500',
        'from-emerald-500 to-teal-500',
        'from-amber-500 to-orange-500',
        'from-rose-500 to-pink-500',
    ];

    return (
        <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
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

                <div className="rounded-xl border border-white/[0.08] bg-gray-900/60 p-4">
                    <div className="mb-2 flex items-center justify-between">
                        <span className="text-xs uppercase tracking-wide text-gray-500">Reconciliation</span>
                        <Circle className={`fill-current ${statusDotClass(STATUS_TONE[reconciliationStatus])}`} size={8} />
                    </div>
                    <div className="text-lg font-medium text-white">{humanize(reconciliationStatus)}</div>
                </div>
            </div>

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

            {modelDelta > 0 && (
                <Notice
                    tone="yellow"
                    message={`Model count mismatch detected: DB reports ${dbModels} while provider storage reports ${storageModels}. Run reconciliation to align state.`}
                />
            )}

            <div className="flex flex-wrap gap-2 mb-4">
                {capabilities.reconcile && (
                    <ActionBtn onClick={onReconcile} disabled={Boolean(loading)} tone="orange" icon={RefreshCw} label="Reconcile" />
                )}
                {capabilities.reset_status && (
                    <ActionBtn onClick={onResetStatus} disabled={Boolean(loading)} tone="red" icon={RotateCcw} label="Reset DB Sync" />
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

            <ReconciliationStatus providerId={providerId} inline={true} />
        </>
    );
}
