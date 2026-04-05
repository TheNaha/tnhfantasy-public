import { useMemo } from 'react';
import {
    Circle,
    Edit2,
    Loader2,
    Power,
    PowerOff,
    Server,
    Trash2,
    ChevronRight,
} from 'lucide-react';
import {
    providerBadgeToneClass,
    summarizeProviderStatus,
} from '../../utils/providerStatus';

const EMPTY_OBJECT = Object.freeze({});

function statusColorByTone(tone) {
    const map = {
        online: 'text-green-400',
        offline: 'text-gray-500',
        deploying: 'text-purple-400',
        syncing: 'text-blue-400',
        downloading: 'text-cyan-400',
        warning: 'text-amber-300',
        failed: 'text-red-400',
        working: 'text-sky-300',
    };
    return map[tone] || map.offline;
}

function deployBadgeText(capabilities) {
    if (capabilities?.managed_deploy) return 'Managed';
    if (capabilities?.manual_deploy) return 'Manual';
    if (capabilities?.runtime_only) return 'Runtime Only';
    return 'Provider';
}

export default function ProviderListItem({
    provider,
    loading,
    actionLabel = null,
    isSelected,
    onSelect,
    onToggleEnabled,
    onEdit,
    onDelete,
    providerFailures = 0,
    jobsAssigned = 0,
}) {
    const runtime = provider.runtime_state ?? EMPTY_OBJECT;
    const capabilities = provider.capabilities ?? EMPTY_OBJECT;
    const credentialSummary = provider.credential_summary ?? EMPTY_OBJECT;
    const diagnostics = provider.diagnostics ?? EMPTY_OBJECT;
    const reconciliation = provider.reconciliation_state ?? EMPTY_OBJECT;

    const runtimeStatus = runtime.status || (runtime.connected ? 'active' : 'stopped');
    const deployBadge = useMemo(() => deployBadgeText(capabilities), [capabilities]);
    const currentAction = actionLabel || loading || null;

    const statusSummary = useMemo(
        () => summarizeProviderStatus(provider, {
            actionLabel: currentAction,
            jobsAssigned,
            providerFailures,
        }),
        [currentAction, jobsAssigned, provider, providerFailures],
    );

    const hasIssues = (diagnostics.warnings?.length || 0) > 0
        || (diagnostics.errors?.length || 0) > 0
        || providerFailures > 0;

    const isReconciling = reconciliation.status === 'reconciling' || reconciliation.status === 'queued';

    return (
        <div
            className={`row-interactive rounded-xl border px-5 py-4 ${
                isSelected
                    ? 'border-blue-500/30 bg-blue-500/5 glow-border'
                    : provider.enabled
                        ? 'border-gray-800 bg-gray-950/60'
                        : 'border-gray-800/60 bg-gray-950/30 opacity-60'
            }`}
            onClick={() => onSelect?.(provider.id)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && onSelect?.(provider.id)}
        >
            <div className="flex items-center gap-4">
                {/* Status indicator + icon */}
                <div className="relative flex-shrink-0">
                    <div className={`flex h-10 w-10 items-center justify-center rounded-xl border ${
                        runtimeStatus === 'running' || runtimeStatus === 'active'
                            ? 'border-green-500/20 bg-green-500/10'
                            : runtimeStatus === 'failed'
                                ? 'border-red-500/20 bg-red-500/10'
                                : 'border-gray-700 bg-gray-800/60'
                    }`}>
                        <Server
                            size={18}
                            className={
                                runtimeStatus === 'running' || runtimeStatus === 'active'
                                    ? 'text-green-400'
                                    : runtimeStatus === 'failed'
                                        ? 'text-red-400'
                                        : 'text-gray-500'
                            }
                        />
                    </div>
                    {/* Tiny status dot */}
                    <Circle
                        size={8}
                        className={`fill-current absolute -right-0.5 -top-0.5 ${statusColorByTone(statusSummary.dotTone)}`}
                    />
                </div>

                {/* Provider info — name + subtitle */}
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-0.5">
                        <h3 className="truncate text-sm font-semibold text-white">
                            {provider.id}
                        </h3>
                        <span className="flex-shrink-0 rounded-md bg-indigo-500/10 border border-indigo-500/20 px-1.5 py-0.5 text-[10px] font-medium text-indigo-300">
                            P{provider.priority}
                        </span>
                        <span className="flex-shrink-0 rounded-md bg-purple-500/10 border border-purple-500/20 px-1.5 py-0.5 text-[10px] font-medium text-purple-300">
                            {deployBadge}
                        </span>
                        {!provider.enabled && (
                            <span className="flex-shrink-0 rounded-md bg-gray-700/50 border border-gray-600/30 px-1.5 py-0.5 text-[10px] font-medium text-gray-400">
                                Disabled
                            </span>
                        )}
                        {!['online', 'offline', 'configured', 'disabled'].includes(statusSummary.stage) && (
                            <span className={`flex-shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${providerBadgeToneClass(statusSummary.stage)}`}>
                                {statusSummary.label}
                            </span>
                        )}
                        {hasIssues && (
                            <span className="flex-shrink-0 rounded-md bg-amber-500/10 border border-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium text-amber-300">
                                ⚠
                            </span>
                        )}
                        {isReconciling && (
                            <span className="flex-shrink-0 rounded-md bg-blue-500/10 border border-blue-500/20 px-1.5 py-0.5 text-[10px] font-medium text-blue-300 animate-pulse">
                                Syncing
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                        <span>{provider.type} provider</span>
                        {credentialSummary.account_label && (
                            <>
                                <span className="text-gray-700">·</span>
                                <span className="truncate">{credentialSummary.account_label}</span>
                            </>
                        )}
                    </div>
                    {statusSummary.message && (
                        <p className="mt-1 truncate text-[11px] text-gray-400" title={statusSummary.message}>
                            {statusSummary.message}
                        </p>
                    )}
                </div>

                {/* Metrics */}
                <div className="hidden items-center gap-2 md:flex">
                    <span className="metric-chip">
                        <Circle size={6} className={`fill-current ${statusColorByTone(statusSummary.dotTone)}`} />
                        {statusSummary.label}
                    </span>
                    {runtime.connected !== undefined && (
                        <span className={`metric-chip ${runtime.connected ? 'text-green-400' : 'text-gray-500'}`}>
                            {runtime.connected ? 'Connected' : 'Offline'}
                        </span>
                    )}
                    {statusSummary.downloadsActive > 0 && (
                        <span className="metric-chip text-cyan-300 border-cyan-500/20">
                            {statusSummary.downloadsActive} downloading
                        </span>
                    )}
                    {statusSummary.downloadsQueued > 0 && (
                        <span className="metric-chip text-blue-300 border-blue-500/20">
                            {statusSummary.downloadsQueued} queued
                        </span>
                    )}
                    <span className="metric-chip">
                        {jobsAssigned} job{jobsAssigned !== 1 ? 's' : ''}
                    </span>
                    {providerFailures > 0 && (
                        <span className="metric-chip text-red-400 border-red-500/20">
                            {providerFailures} fail{providerFailures !== 1 ? 's' : ''}
                        </span>
                    )}
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                    <button
                        type="button"
                        onClick={(e) => {
                            e.stopPropagation();
                            onToggleEnabled?.(provider.id, provider.enabled);
                        }}
                        className="rounded-lg p-2 text-gray-500 transition-colors hover:bg-gray-800 hover:text-gray-300"
                        title={provider.enabled ? 'Disable' : 'Enable'}
                        aria-label={provider.enabled ? 'Disable Provider' : 'Enable Provider'}
                    >
                        {provider.enabled ? <Power size={14} /> : <PowerOff size={14} />}
                    </button>
                    <button
                        type="button"
                        onClick={(e) => {
                            e.stopPropagation();
                            onEdit?.(provider);
                        }}
                        className="rounded-lg p-2 text-gray-500 transition-colors hover:bg-gray-800 hover:text-gray-300"
                        title="Edit"
                        aria-label="Edit Provider"
                    >
                        <Edit2 size={14} />
                    </button>
                    <button
                        type="button"
                        onClick={(e) => {
                            e.stopPropagation();
                            onDelete?.(provider.id);
                        }}
                        className="rounded-lg p-2 text-gray-500 transition-colors hover:bg-gray-800 hover:text-red-400"
                        title="Delete"
                        aria-label="Delete Provider"
                    >
                        <Trash2 size={14} />
                    </button>
                    {currentAction && (
                        <Loader2 className="ml-1 animate-spin text-blue-400" size={14} />
                    )}
                    <ChevronRight
                        size={16}
                        className={`ml-1 text-gray-600 transition-transform duration-200 ${
                            isSelected ? 'rotate-90' : ''
                        }`}
                    />
                </div>
            </div>

            {/* Mobile-only metrics row */}
            <div className="mt-3 flex flex-wrap items-center gap-2 md:hidden">
                <span className="metric-chip">
                    <Circle size={6} className={`fill-current ${statusColorByTone(statusSummary.dotTone)}`} />
                    {statusSummary.label}
                </span>
                <span className="metric-chip">
                    {jobsAssigned} jobs
                </span>
                {statusSummary.downloadsActive > 0 && (
                    <span className="metric-chip text-cyan-300 border-cyan-500/20">
                        {statusSummary.downloadsActive} downloading
                    </span>
                )}
                {providerFailures > 0 && (
                    <span className="metric-chip text-red-400 border-red-500/20">
                        {providerFailures} fails
                    </span>
                )}
            </div>
        </div>
    );
}
