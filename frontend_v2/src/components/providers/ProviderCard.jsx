import { useMemo, useState } from 'react';
import {
    AlertTriangle,
    Circle,
    Edit2,
    Eye,
    FileText,
    Loader2,
    Play,
    Power,
    PowerOff,
    RefreshCw,
    Rocket,
    RotateCcw,
    Server,
    Settings,
    Square,
    Trash2,
    Wrench,
} from 'lucide-react';
import SyncStatusBadge from './SyncStatusBadge';
import ReconciliationStatus from './ReconciliationStatus';
import { providersApi } from '../../api';

const STATUS_COLORS = {
    active: 'text-green-400',
    running: 'text-green-400',
    stopped: 'text-gray-400',
    restarting: 'text-yellow-400',
    deploying: 'text-purple-400',
    reconciling: 'text-blue-400',
    error: 'text-red-400',
};

const DEPLOY_LABELS = {
    idle: 'Deploy idle',
    deploying: 'Deploying',
    succeeded: 'Deploy ready',
    failed: 'Deploy failed',
};

const RECON_LABELS = {
    idle: 'Reconcile idle',
    queued: 'Queued',
    reconciling: 'Reconciling',
    completed: 'Reconciled',
    failed: 'Reconcile failed',
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
    jobsAssigned = 0,
}) {
    const statusCard = provider.status_card || {};
    const modelSync = statusCard.model_sync || statusCard.sync || {};
    const storage = statusCard.storage || {};
    const reconciliation = statusCard.reconciliation || {};
    const deploy = statusCard.deploy || {};
    const diagnostics = statusCard.diagnostics || {};
    const runtime = statusCard.runtime || {};

    const [showLogs, setShowLogs] = useState(false);
    const [showReconciliation, setShowReconciliation] = useState(false);
    const [showDeployDetails, setShowDeployDetails] = useState(false);
    const [showDiagnostics, setShowDiagnostics] = useState(false);
    const [logs, setLogs] = useState('');
    const [loadingLogs, setLoadingLogs] = useState(false);

    const capabilities = getProviderCapabilities(provider, runtime);
    const isDirect = !capabilities.canManageContainer;
    const runtimeStatus = isDirect ? 'active' : (provider.container_status || 'stopped');
    const statusColor = STATUS_COLORS[runtimeStatus] || 'text-gray-400';
    const isLoading = Boolean(loading);
    const warningCount = diagnostics.warnings?.length || 0;
    const errorCount = diagnostics.errors?.length || 0;

    const activitySummary = useMemo(() => {
        if (isLoading && loading) {
            return loading;
        }
        if (deploy.status === 'deploying') {
            return DEPLOY_LABELS.deploying;
        }
        if (reconciliation.status === 'queued' || reconciliation.status === 'reconciling') {
            return RECON_LABELS[reconciliation.status];
        }
        if (deploy.status === 'failed') {
            return DEPLOY_LABELS.failed;
        }
        if (reconciliation.status === 'failed') {
            return RECON_LABELS.failed;
        }
        if (runtimeStatus === 'running' || runtimeStatus === 'active') {
            return isDirect ? 'Direct runtime' : 'Runtime healthy';
        }
        return isDirect ? 'Direct runtime' : runtimeStatus.charAt(0).toUpperCase() + runtimeStatus.slice(1);
    }, [deploy.status, isDirect, isLoading, loading, reconciliation.status, runtimeStatus]);

    const fetchLogs = async () => {
        setLoadingLogs(true);
        try {
            const data = await providersApi.getContainerLogs(provider.id);
            setLogs(data.logs || 'No logs available');
            setShowLogs(true);
        } catch (error) {
            console.error('Failed to fetch logs:', error);
            setLogs(`Failed to fetch logs: ${error.message}`);
            setShowLogs(true);
        } finally {
            setLoadingLogs(false);
        }
    };

    return (
        <div className={`bg-gray-800/50 backdrop-blur-sm border rounded-xl p-6 transition-all card-elevated hover:border-gray-500 ${provider.enabled ? 'border-gray-700' : 'border-gray-800 opacity-60'}`}>
            <div className="flex items-start justify-between gap-4 mb-5">
                <div className="flex items-start gap-3 flex-1">
                    <div className="p-2 bg-blue-500/10 rounded-lg border border-blue-500/20">
                        <Server className="text-blue-400" size={20} />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2 mb-2">
                            <h3 className="text-lg font-semibold text-white flex items-center gap-2 min-w-0">
                                <span className="truncate">{provider.id}</span>
                                <Circle className={`${statusColor} fill-current`} size={8} />
                            </h3>
                            {provider.priority !== undefined && provider.priority !== null && (
                                <span className="text-xs px-2 py-0.5 bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded font-mono">
                                    P{provider.priority}
                                </span>
                            )}
                            <span className="text-xs px-2 py-0.5 bg-purple-500/10 text-purple-400 border border-purple-500/20 rounded font-mono">
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
                        <div className="flex flex-wrap items-center gap-2 mt-3">
                            <StatusPill tone={runtimeStatus === 'running' || runtimeStatus === 'active' ? 'green' : 'gray'}>
                                {activitySummary}
                            </StatusPill>
                            <StatusPill tone={deploy.status === 'failed' ? 'red' : deploy.status === 'deploying' ? 'purple' : 'gray'}>
                                {DEPLOY_LABELS[deploy.status] || 'Deploy idle'}
                            </StatusPill>
                            <StatusPill tone={reconciliation.status === 'failed' ? 'red' : reconciliation.status === 'completed' ? 'green' : reconciliation.status === 'idle' ? 'gray' : 'blue'}>
                                {RECON_LABELS[reconciliation.status] || 'Reconcile idle'}
                            </StatusPill>
                            {diagnostics.updated_at && (
                                <span className="text-xs text-gray-500">
                                    Updated {formatRelativeTime(diagnostics.updated_at)}
                                </span>
                            )}
                        </div>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <button
                        onClick={() => onToggleEnabled?.(provider.id, provider.enabled)}
                        className="p-2 bg-gray-700/50 hover:bg-gray-700 border border-gray-600 rounded-lg text-gray-300 hover:text-white transition-colors"
                        title={provider.enabled ? 'Disable Provider' : 'Enable Provider'}
                        aria-label={provider.enabled ? 'Disable Provider' : 'Enable Provider'}
                        aria-pressed={provider.enabled}
                    >
                        {provider.enabled ? <Power size={14} /> : <PowerOff size={14} />}
                    </button>
                    <button
                        onClick={() => onEdit?.(provider)}
                        className="p-2 bg-gray-700/50 hover:bg-gray-700 border border-gray-600 rounded-lg text-gray-300 hover:text-white transition-colors"
                        title="Edit Provider"
                        aria-label="Edit Provider"
                    >
                        <Edit2 size={14} />
                    </button>
                    <button
                        onClick={() => onDelete?.(provider.id)}
                        className="p-2 bg-gray-700/50 hover:bg-red-500/20 border border-gray-600 hover:border-red-500/50 rounded-lg text-gray-300 hover:text-red-400 transition-colors"
                        title="Delete Provider"
                        aria-label="Delete Provider"
                    >
                        <Trash2 size={14} />
                    </button>
                    {isLoading && (
                        <Loader2 className="animate-spin text-blue-400" size={16} />
                    )}
                </div>
            </div>

            {provider.container_config && (
                <div className="mb-5 grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
                    {provider.container_config.port && (
                        <InfoField label="Port" value={provider.container_config.port} />
                    )}
                    {provider.credentials?.username && (
                        <InfoField label="User" value={provider.credentials.username} />
                    )}
                    {provider.config?.app_name && (
                        <InfoField label="App" value={provider.config.app_name} />
                    )}
                </div>
            )}

            <div className="mb-4">
                <SyncStatusBadge
                    providerId={provider.id}
                    modelSync={modelSync}
                    storage={storage}
                    reconciliation={reconciliation}
                    diagnostics={diagnostics}
                    onReconciliationClick={() => setShowReconciliation(true)}
                />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                <ActionStateCard
                    label="Deploy"
                    value={DEPLOY_LABELS[deploy.status] || 'Deploy idle'}
                    tone={deploy.status === 'failed' ? 'red' : deploy.status === 'deploying' ? 'purple' : deploy.status === 'succeeded' ? 'green' : 'gray'}
                    detail={deploy.message || 'Backend orchestrated deploy state'}
                    onClick={deploy.status !== 'idle' || deploy.steps?.length ? () => setShowDeployDetails(true) : null}
                />
                <ActionStateCard
                    label="Reconcile"
                    value={RECON_LABELS[reconciliation.status] || 'Reconcile idle'}
                    tone={reconciliation.status === 'failed' ? 'red' : reconciliation.status === 'completed' ? 'green' : reconciliation.status === 'idle' ? 'gray' : 'blue'}
                    detail={reconciliation.message || 'Canonical reconciliation session'}
                    onClick={() => setShowReconciliation(true)}
                />
                <ActionStateCard
                    label="Diagnostics"
                    value={`${warningCount} warning${warningCount === 1 ? '' : 's'} · ${errorCount} error${errorCount === 1 ? '' : 's'}`}
                    tone={errorCount > 0 ? 'red' : warningCount > 0 ? 'yellow' : 'green'}
                    detail={errorCount > 0 ? diagnostics.errors[0] : diagnostics.warnings?.[0] || 'Runtime diagnostics look healthy'}
                    onClick={() => setShowDiagnostics(true)}
                />
            </div>

            {providerFailures && providerFailures > 0 && (
                <div className="mt-4 px-4 py-3 bg-orange-500/15 border-l-4 border-orange-500 rounded-lg flex items-center gap-2 text-orange-400 text-sm font-medium">
                    <AlertTriangle size={16} />
                    {providerFailures} consecutive failures
                </div>
            )}

            {(warningCount > 0 || errorCount > 0) && (
                <div className="mt-4 space-y-2">
                    {diagnostics.errors?.slice(0, 2).map((message) => (
                        <Notice key={`error-${message}`} tone="red" message={message} />
                    ))}
                    {diagnostics.warnings?.slice(0, 2).map((message) => (
                        <Notice key={`warning-${message}`} tone="yellow" message={message} />
                    ))}
                </div>
            )}

            <div className="flex items-center gap-2 mt-5 pt-4 border-t border-gray-700 flex-wrap">
                {capabilities.canDeploy && (
                    <button
                        onClick={onDeploy}
                        disabled={isLoading}
                        className="flex items-center gap-2 px-3 py-2 bg-purple-500/20 hover:bg-purple-500/30 text-purple-400 rounded-lg border border-purple-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        <Rocket size={14} />
                        Deploy
                    </button>
                )}

                {capabilities.canManageContainer && (
                    <>
                        {runtimeStatus === 'running' ? (
                            <>
                                {capabilities.canStop && (
                                    <button
                                        onClick={onStop}
                                        disabled={isLoading}
                                        className="flex items-center gap-2 px-3 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg border border-red-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        <Square size={14} />
                                        Stop
                                    </button>
                                )}
                                {capabilities.canRestart && (
                                    <button
                                        onClick={onRestart}
                                        disabled={isLoading}
                                        className="flex items-center gap-2 px-3 py-2 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded-lg border border-blue-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        <RefreshCw size={14} />
                                        Restart
                                    </button>
                                )}
                            </>
                        ) : capabilities.canStart ? (
                            <button
                                onClick={onStart}
                                disabled={isLoading}
                                className="flex items-center gap-2 px-3 py-2 bg-green-500/20 hover:bg-green-500/30 text-green-400 rounded-lg border border-green-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <Play size={14} />
                                Start
                            </button>
                        ) : null}

                        {capabilities.canLogs && (
                            <button
                                onClick={fetchLogs}
                                disabled={loadingLogs}
                                className="flex items-center gap-2 px-3 py-2 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded-lg border border-blue-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <FileText size={14} />
                                Logs
                            </button>
                        )}
                    </>
                )}

                {capabilities.canResetStatus && (
                    <button
                        onClick={onResetStatus}
                        disabled={isLoading}
                        className="flex items-center gap-2 px-3 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg border border-red-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        <RotateCcw size={14} />
                        Reset DB Sync
                    </button>
                )}

                {capabilities.canReconcile && (
                    <button
                        onClick={onReconcile}
                        disabled={isLoading}
                        className="flex items-center gap-2 px-3 py-2 bg-orange-500/20 hover:bg-orange-500/30 text-orange-400 rounded-lg border border-orange-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        <RefreshCw size={14} />
                        Reconcile
                    </button>
                )}

                {capabilities.canSetup && (
                    <button
                        onClick={onSetup}
                        disabled={isLoading}
                        className="flex items-center gap-2 px-3 py-2 bg-blue-500/20 hover:bg-blue-500/30 text-blue-400 rounded-lg border border-blue-500/30 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        <Wrench size={14} />
                        Setup
                    </button>
                )}

                <button
                    onClick={() => setShowDiagnostics(true)}
                    className="flex items-center gap-2 px-3 py-2 bg-gray-700/50 hover:bg-gray-700 text-gray-300 rounded-lg border border-gray-600 transition-colors text-sm"
                >
                    <Eye size={14} />
                    Diagnostics
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

            {showLogs && (
                <ModalShell title={`Container Logs - ${provider.id}`} onClose={() => setShowLogs(false)} maxWidth="max-w-4xl">
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
                </ModalShell>
            )}

            {showDeployDetails && (
                <ModalShell title={`Deploy Details - ${provider.id}`} onClose={() => setShowDeployDetails(false)}>
                    <div className="p-6 space-y-4">
                        <div className="space-y-1">
                            <div className="text-sm text-gray-400">Status</div>
                            <div className="text-white font-medium">{DEPLOY_LABELS[deploy.status] || deploy.status || 'Deploy idle'}</div>
                            {deploy.message && <div className="text-sm text-gray-400">{deploy.message}</div>}
                        </div>
                        <div className="space-y-2">
                            {(deploy.steps?.length ? deploy.steps : [{ name: 'No deploy steps recorded yet', success: true, output: '' }]).map((step) => (
                                <div key={step.name} className="rounded-lg border border-gray-700 bg-gray-900/60 p-3">
                                    <div className="flex items-center justify-between gap-3">
                                        <div className="text-sm font-medium text-white">{step.name}</div>
                                        <StatusPill tone={step.success ? 'green' : step.skipped ? 'gray' : 'red'}>
                                            {step.skipped ? 'Skipped' : step.success ? 'Success' : 'Failed'}
                                        </StatusPill>
                                    </div>
                                    {step.output && (
                                        <pre className="mt-2 text-xs text-gray-400 whitespace-pre-wrap break-words">{step.output}</pre>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                </ModalShell>
            )}

            {showDiagnostics && (
                <ModalShell title={`Diagnostics - ${provider.id}`} onClose={() => setShowDiagnostics(false)}>
                    <div className="p-6 space-y-4">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                            <InfoField label="Backend URL" value={diagnostics.worker?.backend_url || 'Unavailable'} />
                            <InfoField label="Worker URL" value={diagnostics.worker?.worker_url || 'Unavailable'} />
                            <InfoField label="Runtime Mode" value={diagnostics.worker?.mode || 'Unknown'} />
                            <InfoField label="Connected" value={diagnostics.worker?.connected ? 'Yes' : 'No'} />
                        </div>
                        <div>
                            <div className="text-sm font-medium text-white mb-2">Warnings</div>
                            <div className="space-y-2">
                                {(diagnostics.warnings?.length ? diagnostics.warnings : ['No active warnings']).map((message) => (
                                    <Notice key={`diag-warning-${message}`} tone="yellow" message={message} compact />
                                ))}
                            </div>
                        </div>
                        <div>
                            <div className="text-sm font-medium text-white mb-2">Errors</div>
                            <div className="space-y-2">
                                {(diagnostics.errors?.length ? diagnostics.errors : ['No active errors']).map((message) => (
                                    <Notice key={`diag-error-${message}`} tone={diagnostics.errors?.length ? 'red' : 'green'} message={message} compact />
                                ))}
                            </div>
                        </div>
                    </div>
                </ModalShell>
            )}

            {showReconciliation && (
                <ReconciliationStatus
                    providerId={provider.id}
                    onClose={() => setShowReconciliation(false)}
                />
            )}
        </div>
    );
}

function getProviderCapabilities(provider, runtime) {
    const runtimeCapabilities = runtime?.capabilities;
    const explicitCapabilities = runtimeCapabilities || provider.capabilities || provider.features || {};
    const boolOr = (...values) => values.find((value) => value !== undefined);
    const containerSupport = Boolean(provider.container_config);

    return {
        canManageContainer: boolOr(explicitCapabilities.container, containerSupport) ?? false,
        canStart: boolOr(explicitCapabilities.start_container, explicitCapabilities.start, containerSupport) ?? false,
        canStop: boolOr(explicitCapabilities.stop_container, explicitCapabilities.stop, containerSupport) ?? false,
        canRestart: boolOr(explicitCapabilities.restart_container, explicitCapabilities.restart, containerSupport) ?? false,
        canLogs: boolOr(explicitCapabilities.view_logs, explicitCapabilities.logs, containerSupport) ?? false,
        canDeploy: boolOr(explicitCapabilities.deploy, false) ?? false,
        canSetup: boolOr(explicitCapabilities.setup, false) ?? false,
        canResetStatus: boolOr(explicitCapabilities.reset_status, explicitCapabilities.reset_model_status, true) ?? true,
        canReconcile: boolOr(explicitCapabilities.reconcile, true) ?? true,
    };
}

function StatusPill({ children, tone = 'gray' }) {
    const classes = {
        gray: 'bg-gray-500/15 text-gray-300 border border-gray-500/25',
        green: 'bg-green-500/15 text-green-400 border border-green-500/25',
        blue: 'bg-blue-500/15 text-blue-400 border border-blue-500/25',
        purple: 'bg-purple-500/15 text-purple-400 border border-purple-500/25',
        yellow: 'bg-yellow-500/15 text-yellow-400 border border-yellow-500/25',
        red: 'bg-red-500/15 text-red-400 border border-red-500/25',
    };

    return (
        <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${classes[tone] || classes.gray}`}>
            {children}
        </span>
    );
}

function InfoField({ label, value }) {
    return (
        <div className="rounded-lg border border-gray-700 bg-gray-900/40 px-3 py-2">
            <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
            <div className="text-sm text-gray-200 break-all">{value}</div>
        </div>
    );
}

function ActionStateCard({ label, value, detail, tone, onClick }) {
    return (
        <button
            type="button"
            onClick={onClick || undefined}
            className={`text-left rounded-xl border p-3 transition-colors ${onClick ? 'hover:border-gray-500 cursor-pointer' : 'cursor-default'} ${cardTone(tone)}`}
        >
            <div className="flex items-center justify-between gap-2">
                <span className="text-xs uppercase tracking-wide text-gray-500">{label}</span>
                {onClick && <Eye size={14} className="text-gray-500" />}
            </div>
            <div className="mt-2 text-sm font-medium text-white">{value}</div>
            <div className="mt-1 text-xs text-gray-400 line-clamp-2">{detail}</div>
        </button>
    );
}

function Notice({ tone, message, compact = false }) {
    const classes = {
        red: 'bg-red-500/12 border-red-500/35 text-red-300',
        yellow: 'bg-yellow-500/12 border-yellow-500/35 text-yellow-300',
        green: 'bg-green-500/12 border-green-500/35 text-green-300',
    };
    return (
        <div className={`rounded-lg border px-3 ${compact ? 'py-2' : 'py-3'} text-sm ${classes[tone] || classes.yellow}`}>
            {message}
        </div>
    );
}

function ModalShell({ title, onClose, children, maxWidth = 'max-w-3xl' }) {
    return (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onClose}>
            <div className={`bg-gray-800 rounded-xl border border-gray-700 w-full ${maxWidth} max-h-[80vh] flex flex-col`} onClick={(event) => event.stopPropagation()}>
                <div className="border-b border-gray-700 px-6 py-4 flex items-center justify-between">
                    <h3 className="text-lg font-semibold text-white">{title}</h3>
                    <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
                        ×
                    </button>
                </div>
                <div className="overflow-y-auto custom-scrollbar flex-1">{children}</div>
            </div>
        </div>
    );
}

function cardTone(tone) {
    const classes = {
        gray: 'border-gray-700 bg-gray-900/40',
        green: 'border-green-500/20 bg-green-500/5',
        blue: 'border-blue-500/20 bg-blue-500/5',
        purple: 'border-purple-500/20 bg-purple-500/5',
        yellow: 'border-yellow-500/20 bg-yellow-500/5',
        red: 'border-red-500/20 bg-red-500/5',
    };
    return classes[tone] || classes.gray;
}

function formatRelativeTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return 'recently';
    }

    const diffMs = Date.now() - date.getTime();
    const diffMinutes = Math.max(0, Math.round(diffMs / 60000));
    if (diffMinutes < 1) {
        return 'just now';
    }
    if (diffMinutes < 60) {
        return `${diffMinutes}m ago`;
    }
    const diffHours = Math.round(diffMinutes / 60);
    if (diffHours < 24) {
        return `${diffHours}h ago`;
    }
    return `${Math.round(diffHours / 24)}d ago`;
}
