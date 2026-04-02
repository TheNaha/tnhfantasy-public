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
    Square,
    Trash2,
    Wrench,
} from 'lucide-react';
import { useProviderLogs } from '../../hooks/useProvidersPageData';
import ReconciliationStatus from './ReconciliationStatus';

const EMPTY_OBJECT = Object.freeze({});

const STATUS_TONE = {
    running: 'green',
    active: 'green',
    connected: 'green',
    stopped: 'gray',
    idle: 'gray',
    queued: 'blue',
    reconciling: 'blue',
    completed: 'green',
    deploying: 'purple',
    failed: 'red',
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
    onEdit,
    onDelete,
    onToggleEnabled,
    providerFailures = 0,
    jobsAssigned = 0,
}) {
    const runtime = provider.runtime_state ?? EMPTY_OBJECT;
    const deploy = provider.deploy_state ?? EMPTY_OBJECT;
    const reconciliation = provider.reconciliation_state ?? EMPTY_OBJECT;
    const modelSync = provider.model_sync ?? EMPTY_OBJECT;
    const storage = provider.storage ?? EMPTY_OBJECT;
    const diagnostics = provider.diagnostics ?? EMPTY_OBJECT;
    const capabilities = provider.capabilities ?? EMPTY_OBJECT;
    const capabilityReasons = provider.capability_reasons ?? EMPTY_OBJECT;
    const credentialSummary = provider.credential_summary ?? EMPTY_OBJECT;

    const [showLogs, setShowLogs] = useState(false);
    const [showDeployDetails, setShowDeployDetails] = useState(false);
    const [showDiagnostics, setShowDiagnostics] = useState(false);
    const [showReconciliation, setShowReconciliation] = useState(false);
    const [logsError, setLogsError] = useState('');
    const {
        logs,
        fetchLogs,
        isLoading: loadingLogs,
    } = useProviderLogs(provider.id);

    const runtimeStatus = runtime.status || (runtime.connected ? 'active' : 'stopped');
    const loadingLabel = loading ? loading.charAt(0).toUpperCase() + loading.slice(1) : null;
    const deployBadge = useMemo(() => {
        if (capabilities.managed_deploy) {
            return 'Managed Deploy';
        }
        if (capabilities.manual_deploy) {
            return 'Manual Deploy';
        }
        if (capabilities.runtime_only) {
            return 'Runtime Only';
        }
        return 'Provider';
    }, [capabilities]);

    const fetchProviderLogs = async () => {
        try {
            await fetchLogs();
            setLogsError('');
            setShowLogs(true);
        } catch (error) {
            setLogsError(`Failed to fetch logs: ${error.message}`);
            setShowLogs(true);
        }
    };

    return (
        <div className={`rounded-2xl border p-6 backdrop-blur-sm transition-colors ${provider.enabled ? 'border-gray-700 bg-gray-900/70' : 'border-gray-800 bg-gray-900/40 opacity-75'}`}>
            <div className="mb-6 flex items-start justify-between gap-4">
                <div className="flex min-w-0 items-start gap-3">
                    <div className="rounded-xl border border-blue-500/25 bg-blue-500/10 p-3">
                        <Server className="text-blue-400" size={20} />
                    </div>
                    <div className="min-w-0">
                        <div className="mb-2 flex flex-wrap items-center gap-2">
                            <h3 className="flex items-center gap-2 text-lg font-semibold text-white">
                                <span className="truncate">{provider.id}</span>
                                <Circle className={`fill-current ${statusDot(runtimeStatus)}`} size={8} />
                            </h3>
                            <Badge tone="blue">P{provider.priority}</Badge>
                            <Badge tone="purple">{deployBadge}</Badge>
                            {!provider.enabled && <Badge tone="gray">Disabled</Badge>}
                        </div>
                        <div className="text-sm text-gray-400">
                            {provider.type} provider
                            {credentialSummary.account_label ? ` · ${credentialSummary.account_label}` : ''}
                        </div>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <button
                        onClick={() => onToggleEnabled?.(provider.id, provider.enabled)}
                        className="rounded-lg border border-gray-700 bg-gray-800/70 p-2 text-gray-300 transition-colors hover:bg-gray-700 hover:text-white"
                        title={provider.enabled ? 'Disable Provider' : 'Enable Provider'}
                        aria-label={provider.enabled ? 'Disable Provider' : 'Enable Provider'}
                    >
                        {provider.enabled ? <Power size={14} /> : <PowerOff size={14} />}
                    </button>
                    <button
                        onClick={() => onEdit?.(provider)}
                        className="rounded-lg border border-gray-700 bg-gray-800/70 p-2 text-gray-300 transition-colors hover:bg-gray-700 hover:text-white"
                        title="Edit Provider"
                        aria-label="Edit Provider"
                    >
                        <Edit2 size={14} />
                    </button>
                    <button
                        onClick={() => onDelete?.(provider.id)}
                        className="rounded-lg border border-gray-700 bg-gray-800/70 p-2 text-gray-300 transition-colors hover:border-red-500/40 hover:bg-red-500/15 hover:text-red-300"
                        title="Delete Provider"
                        aria-label="Delete Provider"
                    >
                        <Trash2 size={14} />
                    </button>
                    {loadingLabel && <Loader2 className="animate-spin text-blue-400" size={16} />}
                </div>
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
                <Section title="Overview">
                    <div className="grid gap-3 md:grid-cols-2">
                        <InfoField label="Provider Type" value={provider.type} />
                        <InfoField label="Jobs Assigned" value={String(jobsAssigned)} />
                        <InfoField label="Configured Secrets" value={String(credentialSummary.configured_fields?.length || 0)} />
                        <InfoField label="Provider Failures" value={String(providerFailures)} />
                    </div>
                    {(diagnostics.warnings?.length || diagnostics.errors?.length || providerFailures > 0) ? (
                        <div className="mt-4 space-y-2">
                            {providerFailures > 0 && (
                                <Notice tone="yellow" message={`${providerFailures} consecutive failures recorded for this provider.`} />
                            )}
                            {diagnostics.errors?.slice(0, 2).map((message) => (
                                <Notice key={`error-${message}`} tone="red" message={message} />
                            ))}
                            {diagnostics.warnings?.slice(0, 2).map((message) => (
                                <Notice key={`warning-${message}`} tone="yellow" message={message} />
                            ))}
                        </div>
                    ) : (
                        <Notice tone="green" message="No active diagnostics issues." />
                    )}
                </Section>

                <Section title="Runtime">
                    <div className="grid gap-3 md:grid-cols-2">
                        <StatusField label="Runtime Status" value={humanizeStatus(runtimeStatus)} tone={STATUS_TONE[runtimeStatus]} />
                        <StatusField label="Connectivity" value={runtime.connected ? 'Connected' : 'Unavailable'} tone={runtime.connected ? 'green' : 'gray'} />
                        <InfoField label="Worker URL" value={runtime.worker_url || 'Unavailable'} />
                        <InfoField label="Container Port" value={String(provider.runtime_config?.port || 'n/a')} />
                    </div>

                    <div className="mt-4 flex flex-wrap gap-2">
                        {capabilities.start_container && runtimeStatus !== 'running' && (
                            <ActionButton onClick={onStart} disabled={Boolean(loading)} tone="green" icon={Play} label="Start" />
                        )}
                        {capabilities.stop_container && runtimeStatus === 'running' && (
                            <ActionButton onClick={onStop} disabled={Boolean(loading)} tone="red" icon={Square} label="Stop" />
                        )}
                        {capabilities.restart_container && runtimeStatus === 'running' && (
                            <ActionButton onClick={onRestart} disabled={Boolean(loading)} tone="blue" icon={RefreshCw} label="Restart" />
                        )}
                        {capabilities.view_logs && (
                            <ActionButton onClick={fetchProviderLogs} disabled={loadingLogs} tone="blue" icon={FileText} label="Logs" />
                        )}
                        {capabilities.setup && (
                            <ActionButton onClick={onSetup} disabled={Boolean(loading)} tone="blue" icon={Wrench} label="Setup" />
                        )}
                    </div>
                </Section>

                <Section title="Deployment">
                    <div className="grid gap-3 md:grid-cols-2">
                        <StatusField label="Deploy Status" value={humanizeStatus(deploy.status || 'idle')} tone={STATUS_TONE[deploy.status || 'idle']} />
                        <InfoField label="Deploy Mode" value={deployBadge} />
                        <InfoField label="Deploy Message" value={deploy.message || capabilityReasons.deploy || 'No deploy activity recorded'} />
                        <InfoField label="Completed Steps" value={String(deploy.completed_steps?.length || deploy.steps?.filter((step) => step.success)?.length || 0)} />
                    </div>

                    <div className="mt-4 flex flex-wrap gap-2">
                        {capabilities.deploy && (
                            <ActionButton onClick={onDeploy} disabled={Boolean(loading)} tone="purple" icon={Rocket} label="Deploy" />
                        )}
                        {!capabilities.deploy && capabilityReasons.deploy && (
                            <Notice tone="yellow" message={capabilityReasons.deploy} compact />
                        )}
                        {(deploy.steps?.length || deploy.status !== 'idle') ? (
                            <ActionButton onClick={() => setShowDeployDetails(true)} tone="gray" icon={Eye} label="Details" />
                        ) : null}
                    </div>
                </Section>

                <Section title="Model Sync">
                    <div className="grid gap-3 md:grid-cols-2">
                        <InfoField label="DB Sync" value={`${modelSync.total_models || 0} models`} />
                        <InfoField label="Provider Storage" value={`${storage.total || 0} models`} />
                        <StatusField label="Reconciliation" value={humanizeStatus(reconciliation.status || 'idle')} tone={STATUS_TONE[reconciliation.status || 'idle']} />
                        <InfoField
                            label="Directory Breakdown"
                            value={formatDirectoryBreakdown(storage.by_directory)}
                        />
                    </div>

                    <div className="mt-4 flex flex-wrap gap-2">
                        {capabilities.reconcile && (
                            <ActionButton onClick={onReconcile} disabled={Boolean(loading)} tone="orange" icon={RefreshCw} label="Reconcile" />
                        )}
                        {capabilities.reset_status && (
                            <ActionButton onClick={onResetStatus} disabled={Boolean(loading)} tone="red" icon={RotateCcw} label="Reset DB Sync" />
                        )}
                        <ActionButton onClick={() => setShowReconciliation(true)} tone="gray" icon={Eye} label="Progress" />
                        <ActionButton onClick={() => setShowDiagnostics(true)} tone="gray" icon={AlertTriangle} label="Diagnostics" />
                    </div>
                </Section>
            </div>

            {showLogs && (
                <ModalShell title={`Container Logs - ${provider.id}`} onClose={() => setShowLogs(false)} maxWidth="max-w-4xl">
                    <div className="flex-1 overflow-y-auto p-4">
                        <pre className="whitespace-pre-wrap break-words rounded-lg border border-gray-700 bg-gray-950 p-4 text-xs text-gray-300">
                            {logsError && !logs ? logsError : logs || 'No logs available'}
                        </pre>
                    </div>
                </ModalShell>
            )}

            {showDeployDetails && (
                <ModalShell title={`Deploy Details - ${provider.id}`} onClose={() => setShowDeployDetails(false)}>
                    <div className="space-y-3 p-6">
                        {(deploy.steps?.length ? deploy.steps : [{ name: 'No deploy steps recorded', success: true, output: '' }]).map((step) => (
                            <div key={step.name} className="rounded-xl border border-gray-700 bg-gray-950/70 p-4">
                                <div className="mb-2 flex items-center justify-between gap-3">
                                    <div className="font-medium text-white">{step.name}</div>
                                    <Badge tone={step.skipped ? 'gray' : step.success ? 'green' : 'red'}>
                                        {step.skipped ? 'Skipped' : step.success ? 'Success' : 'Failed'}
                                    </Badge>
                                </div>
                                {step.entrypoint && (
                                    <div className="mb-2 text-xs text-gray-500">{step.entrypoint}</div>
                                )}
                                <pre className="whitespace-pre-wrap break-words text-xs text-gray-400">
                                    {step.output || 'No output'}
                                </pre>
                            </div>
                        ))}
                    </div>
                </ModalShell>
            )}

            {showDiagnostics && (
                <ModalShell title={`Diagnostics - ${provider.id}`} onClose={() => setShowDiagnostics(false)}>
                    <div className="space-y-4 p-6">
                        <div className="grid gap-3 md:grid-cols-2">
                            <InfoField label="Backend URL" value={diagnostics.worker?.backend_url || 'Unavailable'} />
                            <InfoField label="Worker URL" value={diagnostics.worker?.worker_url || 'Unavailable'} />
                            <InfoField label="Runtime Mode" value={diagnostics.worker?.mode || runtime.mode || 'Unknown'} />
                            <InfoField label="Credential Readiness" value={credentialSummary.ready ? 'Ready' : 'Missing requirements'} />
                        </div>
                        <div className="space-y-2">
                            {(diagnostics.warnings?.length ? diagnostics.warnings : ['No active warnings']).map((message) => (
                                <Notice key={`warn-${message}`} tone={diagnostics.warnings?.length ? 'yellow' : 'green'} message={message} compact />
                            ))}
                            {(diagnostics.errors?.length ? diagnostics.errors : ['No active errors']).map((message) => (
                                <Notice key={`err-${message}`} tone={diagnostics.errors?.length ? 'red' : 'green'} message={message} compact />
                            ))}
                        </div>
                    </div>
                </ModalShell>
            )}

            {showReconciliation && (
                <ReconciliationStatus providerId={provider.id} onClose={() => setShowReconciliation(false)} />
            )}
        </div>
    );
}

function Section({ title, children }) {
    return (
        <section className="rounded-2xl border border-gray-800 bg-gray-950/60 p-5">
            <div className="mb-4 text-xs font-semibold uppercase tracking-[0.2em] text-gray-500">{title}</div>
            {children}
        </section>
    );
}

function ActionButton({ onClick, disabled = false, tone = 'gray', icon: Icon, label }) {
    const tones = {
        gray: 'border-gray-700 bg-gray-800/70 text-gray-200 hover:bg-gray-700',
        blue: 'border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/15',
        green: 'border-green-500/30 bg-green-500/10 text-green-300 hover:bg-green-500/15',
        purple: 'border-purple-500/30 bg-purple-500/10 text-purple-300 hover:bg-purple-500/15',
        orange: 'border-orange-500/30 bg-orange-500/10 text-orange-300 hover:bg-orange-500/15',
        red: 'border-red-500/30 bg-red-500/10 text-red-300 hover:bg-red-500/15',
    };

    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${tones[tone] || tones.gray}`}
        >
            <Icon size={14} />
            {label}
        </button>
    );
}

function Badge({ children, tone = 'gray' }) {
    const tones = {
        gray: 'border-gray-600 bg-gray-700/40 text-gray-200',
        blue: 'border-blue-500/25 bg-blue-500/10 text-blue-300',
        purple: 'border-purple-500/25 bg-purple-500/10 text-purple-300',
        green: 'border-green-500/25 bg-green-500/10 text-green-300',
        red: 'border-red-500/25 bg-red-500/10 text-red-300',
    };
    return (
        <span className={`inline-flex items-center rounded-full border px-2 py-1 text-xs font-medium ${tones[tone] || tones.gray}`}>
            {children}
        </span>
    );
}

function InfoField({ label, value }) {
    return (
        <div className="rounded-xl border border-gray-800 bg-gray-900/80 px-4 py-3">
            <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">{label}</div>
            <div className="break-all text-sm text-gray-200">{value || 'n/a'}</div>
        </div>
    );
}

function StatusField({ label, value, tone = 'gray' }) {
    return (
        <div className="rounded-xl border border-gray-800 bg-gray-900/80 px-4 py-3">
            <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">{label}</div>
            <div className="flex items-center gap-2">
                <Circle className={`fill-current ${statusDot(tone)}`} size={8} />
                <span className="text-sm text-gray-100">{value}</span>
            </div>
        </div>
    );
}

function Notice({ tone, message, compact = false }) {
    const tones = {
        red: 'border-red-500/30 bg-red-500/10 text-red-200',
        yellow: 'border-yellow-500/30 bg-yellow-500/10 text-yellow-200',
        green: 'border-green-500/30 bg-green-500/10 text-green-200',
    };
    return (
        <div className={`rounded-xl border px-4 ${compact ? 'py-2 text-sm' : 'py-3 text-sm'} ${tones[tone] || tones.yellow}`}>
            {message}
        </div>
    );
}

function ModalShell({ title, onClose, children, maxWidth = 'max-w-3xl' }) {
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
            <div className={`flex max-h-[85vh] w-full ${maxWidth} flex-col rounded-2xl border border-gray-700 bg-gray-900`} onClick={(event) => event.stopPropagation()}>
                <div className="flex items-center justify-between border-b border-gray-800 px-6 py-4">
                    <h3 className="text-lg font-semibold text-white">{title}</h3>
                    <button onClick={onClose} className="text-gray-400 transition-colors hover:text-white">
                        ×
                    </button>
                </div>
                {children}
            </div>
        </div>
    );
}

function statusDot(status) {
    const tones = {
        green: 'text-green-400',
        running: 'text-green-400',
        active: 'text-green-400',
        blue: 'text-blue-400',
        queued: 'text-blue-400',
        reconciling: 'text-blue-400',
        purple: 'text-purple-400',
        deploying: 'text-purple-400',
        red: 'text-red-400',
        failed: 'text-red-400',
        yellow: 'text-yellow-400',
        orange: 'text-orange-400',
        gray: 'text-gray-500',
        stopped: 'text-gray-500',
        idle: 'text-gray-500',
    };
    return tones[status] || tones.gray;
}

function humanizeStatus(status) {
    if (!status) {
        return 'Unknown';
    }
    return status
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatDirectoryBreakdown(byDirectory = {}) {
    const entries = Object.entries(byDirectory || {});
    if (entries.length === 0) {
        return 'No storage stats yet';
    }
    return entries
        .map(([directory, count]) => `${capitalize(directory)}: ${count}`)
        .join(' · ');
}

function capitalize(value) {
    return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}
