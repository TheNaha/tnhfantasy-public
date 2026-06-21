import { useMemo, useState } from 'react';
import {
    AlertTriangle,
    CheckCircle,
    Circle,
    Download,
    Eye,
    Loader2,
    RefreshCw,
    Rocket,
    RotateCcw,
    Server,
    Wrench,
    X,
    XCircle,
} from 'lucide-react';
import { motion } from 'framer-motion';
import ReconciliationStatus from './ReconciliationStatus';
import { providerBadgeToneClass, summarizeProviderStatus } from '../../utils/providerStatus';
import JobCard from '../dashboard/JobCard';
import useJobStore from '../../store/jobStore';

const EMPTY_OBJECT = Object.freeze({});

const TABS = [
    { id: 'runtime', label: 'Runtime' },
    { id: 'jobs', label: 'Active Jobs' },
    { id: 'deploy', label: 'Deploy' },
    { id: 'sync', label: 'Model Sync' },
    { id: 'diagnostics', label: 'Diagnostics' },
];

const STATUS_TONE = {
    running: 'green', active: 'green', connected: 'green',
    stopped: 'gray', idle: 'gray',
    queued: 'blue', reconciling: 'blue', completed: 'green',
    deploying: 'purple', failed: 'red',
};

function statusDotClass(status) {
    const map = {
        green: 'text-green-400', running: 'text-green-400', active: 'text-green-400',
        blue: 'text-blue-400', queued: 'text-blue-400', reconciling: 'text-blue-400',
        purple: 'text-purple-400', deploying: 'text-purple-400',
        red: 'text-red-400', failed: 'text-red-400',
        yellow: 'text-yellow-400', orange: 'text-orange-400',
        gray: 'text-gray-500', stopped: 'text-gray-500', idle: 'text-gray-500',
    };
    return map[status] || map.gray;
}

function humanize(status) {
    if (!status) return 'Unknown';
    return status.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function capitalize(v) {
    return v ? v.charAt(0).toUpperCase() + v.slice(1) : v;
}

export default function ProviderDetailPanel({
    provider,
    onClose,
    loading,
    onDeploy, onReconcile,
    onResetStatus, onSetup,
    providerFailures = 0,
    jobsAssigned = 0,
}) {
    const [activeTab, setActiveTab] = useState('runtime');
    const allJobs = useJobStore(state => state.jobs);
    const activeJobs = useMemo(() => {
        return Object.values(allJobs).filter(j => 
            j.provider_id === provider.id && 
            !['completed', 'failed', 'cancelled', 'error'].includes(j.status)
        );
    }, [allJobs, provider.id]);

    const runtime = provider.runtime_state ?? EMPTY_OBJECT;
    const deploy = provider.deploy_state ?? EMPTY_OBJECT;
    const reconciliation = provider.reconciliation_state ?? EMPTY_OBJECT;
    const modelSync = provider.model_sync ?? EMPTY_OBJECT;
    const storage = provider.storage ?? EMPTY_OBJECT;
    const storageLoaded = provider.storage != null;
    const diagnostics = provider.diagnostics ?? EMPTY_OBJECT;
    const capabilities = provider.capabilities ?? EMPTY_OBJECT;
    const capabilityReasons = provider.capability_reasons ?? EMPTY_OBJECT;
    const credentialSummary = provider.credential_summary ?? EMPTY_OBJECT;

    const runtimeStatus = runtime.status ?? (runtime.connected ? 'active' : 'stopped');

    const deployBadge = useMemo(() => {
        if (capabilities.managed_deploy) return 'Managed Deploy';
        if (capabilities.manual_deploy) return 'Manual Deploy';
        if (capabilities.runtime_only) return 'Runtime Only';
        return 'Provider';
    }, [capabilities]);

    const statusSummary = useMemo(
        () => summarizeProviderStatus(provider, {
            actionLabel: loading || null,
            jobsAssigned,
            providerFailures,
        }),
        [jobsAssigned, loading, provider, providerFailures],
    );

    return (
        <>
            {/* Overlay */}
            <motion.div
                className="side-drawer-overlay"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
                onClick={onClose}
            />

            {/* Drawer */}
            <motion.div
                className="side-drawer surface-elevated"
                initial={{ x: '100%' }}
                animate={{ x: 0 }}
                exit={{ x: '100%' }}
                transition={{ type: 'spring', damping: 30, stiffness: 300 }}
            >
                {/* Header */}
                <div className="sticky top-0 z-10 border-b border-white/[0.06] bg-gray-950/90 backdrop-blur-xl px-6 py-5">
                    <div className="flex items-start justify-between mb-4">
                        <div className="flex items-start gap-3 min-w-0">
                            <div className={`flex h-11 w-11 items-center justify-center rounded-xl border flex-shrink-0 ${
                                runtimeStatus === 'running' || runtimeStatus === 'active'
                                    ? 'border-green-500/20 bg-green-500/10'
                                    : 'border-gray-700 bg-gray-800/60'
                            }`}>
                                <Server
                                    size={20}
                                    className={
                                        runtimeStatus === 'running' || runtimeStatus === 'active'
                                            ? 'text-green-400'
                                            : 'text-gray-500'
                                    }
                                />
                            </div>
                            <div className="min-w-0">
                                <h2 className="text-lg font-semibold text-white truncate">
                                    {provider.id}
                                </h2>
                                <p className="text-xs text-gray-500 mt-0.5">
                                    {provider.type} provider
                                    {credentialSummary.account_label && ` · ${credentialSummary.account_label}`}
                                </p>
                            </div>
                        </div>
                        <button
                            onClick={onClose}
                            className="rounded-lg p-2 text-gray-500 transition-colors hover:bg-gray-800 hover:text-white"
                            aria-label="Close"
                        >
                            <X size={18} />
                        </button>
                    </div>

                    {/* Status summary chips */}
                    <div className="flex flex-wrap items-center gap-2 mb-4">
                        <span className={`metric-chip border ${providerBadgeToneClass(statusSummary.stage)}`}>
                            {statusSummary.label}
                        </span>
                        <span className="metric-chip">
                            <Circle size={6} className={`fill-current ${statusDotClass(runtimeStatus)}`} />
                            {humanize(runtimeStatus)}
                        </span>
                        <span className={`metric-chip ${runtime.connected ? 'text-green-400' : 'text-gray-500'}`}>
                            {runtime.connected ? '● Connected' : '○ Offline'}
                        </span>
                        <span className="metric-chip">
                            P{provider.priority}
                        </span>
                        <span className="metric-chip">
                            {deployBadge}
                        </span>
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
                        {(statusSummary.warningCount > 0 || statusSummary.errorCount > 0) && (
                            <span className="metric-chip text-amber-300 border-amber-500/20">
                                {statusSummary.errorCount + statusSummary.warningCount} alerts
                            </span>
                        )}
                        {!provider.enabled && (
                            <span className="metric-chip text-amber-400 border-amber-500/20">
                                Disabled
                            </span>
                        )}
                    </div>
                    {statusSummary.message && (
                        <p className="text-xs text-gray-400 mb-3">{statusSummary.message}</p>
                    )}

                    {/* Tab bar */}
                    <div className="tab-bar -mx-6 px-6">
                        {TABS.map((tab) => (
                            <button
                                key={tab.id}
                                type="button"
                                className={activeTab === tab.id ? 'active' : ''}
                                onClick={() => setActiveTab(tab.id)}
                            >
                                {tab.label}
                            </button>
                        ))}
                    </div>
                </div>

                {/* Tab content */}
                <div className="p-6 space-y-5">
                    {activeTab === 'runtime' && (
                        <RuntimeTab
                            runtime={runtime}
                            runtimeStatus={runtimeStatus}
                            provider={provider}
                            capabilities={capabilities}
                            loading={loading}
                            onSetup={onSetup}
                            jobsAssigned={jobsAssigned}
                            providerFailures={providerFailures}
                        />
                    )}
                    {activeTab === 'jobs' && (
                        <div className="space-y-4">
                            {activeJobs.length === 0 ? (
                                <div className="text-center py-8 text-gray-500">
                                    <Rocket size={32} className="mx-auto mb-3 opacity-20" />
                                    <p>No active jobs running on this provider.</p>
                                </div>
                            ) : (
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                    {activeJobs.map(job => (
                                        <JobCard key={job.id} job={job} />
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                    {activeTab === 'deploy' && (
                        <DeployTab
                            deploy={deploy}
                            deployBadge={deployBadge}
                            capabilities={capabilities}
                            capabilityReasons={capabilityReasons}
                            loading={loading}
                            onDeploy={onDeploy}
                            provider={provider}
                        />
                    )}
                    {activeTab === 'sync' && (
                        <SyncTab
                            modelSync={modelSync}
                            storage={storage}
                            storageLoaded={storageLoaded}
                            reconciliation={reconciliation}
                            capabilities={capabilities}
                            loading={loading}
                            onReconcile={onReconcile}
                            onResetStatus={onResetStatus}
                            providerId={provider.id}
                        />
                    )}
                    {activeTab === 'diagnostics' && (
                        <DiagnosticsTab
                            diagnostics={diagnostics}
                            runtime={runtime}
                            credentialSummary={credentialSummary}
                            providerFailures={providerFailures}
                        />
                    )}
                </div>
            </motion.div>
        </>
    );
}

/* ── Shared sub-components ── */

function DataRow({ label, value, mono = false }) {
    return (
        <div className="flex items-start justify-between gap-4 py-2.5 border-b border-white/[0.03] last:border-0">
            <span className="text-xs uppercase tracking-wide text-gray-500 flex-shrink-0">{label}</span>
            <span className={`text-sm text-right text-gray-200 break-all ${mono ? 'font-mono text-xs' : ''}`}>
                {value || 'n/a'}
            </span>
        </div>
    );
}

function StatusRow({ label, value, tone = 'gray' }) {
    return (
        <div className="flex items-center justify-between gap-4 py-2.5 border-b border-white/[0.03] last:border-0">
            <span className="text-xs uppercase tracking-wide text-gray-500">{label}</span>
            <span className="flex items-center gap-2">
                <Circle className={`fill-current ${statusDotClass(tone)}`} size={7} />
                <span className="text-sm text-gray-200">{value}</span>
            </span>
        </div>
    );
}

function ActionBtn({ onClick, disabled = false, tone = 'gray', icon: Icon, label }) {
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

function Notice({ tone, message }) {
    const tones = {
        red: 'border-red-500/20 bg-red-500/8 text-red-200',
        yellow: 'border-yellow-500/20 bg-yellow-500/8 text-yellow-200',
        green: 'border-green-500/20 bg-green-500/8 text-green-200',
    };
    return (
        <div className={`rounded-lg border px-4 py-2.5 text-sm ${tones[tone] || tones.yellow}`}>
            {message}
        </div>
    );
}

/* ── Tab content panels ── */

function RuntimeTab({
    runtime, runtimeStatus, provider, capabilities, loading,
    onSetup,
    jobsAssigned, providerFailures,
}) {
    return (
        <>
            <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
                <StatusRow label="Runtime Status" value={humanize(runtimeStatus)} tone={STATUS_TONE[runtimeStatus]} />
                <StatusRow label="Connectivity" value={runtime.connected ? 'Connected' : 'Unavailable'} tone={runtime.connected ? 'green' : 'gray'} />
                <DataRow label="Worker URL" value={runtime.worker_url} mono />
                <DataRow label="Container Port" value={String(provider.runtime_config?.port ?? 'n/a')} />
                <DataRow label="Jobs Assigned" value={String(jobsAssigned)} />
                <DataRow label="Failures" value={String(providerFailures)} />
                <DataRow label="Last Seen" value={runtime.last_seen_at ? new Date(runtime.last_seen_at).toLocaleString() : 'N/A'} />
                <DataRow label="Container ID" value={runtime.container_id ? runtime.container_id.slice(0, 12) : 'N/A'} mono />
                <DataRow label="Uptime" value={runtime.uptime ? Math.floor(runtime.uptime / 60) + 'm' : 'N/A'} />
            </div>

            <div className="flex flex-wrap gap-2">
                {capabilities.setup && (
                    <ActionBtn onClick={onSetup} disabled={Boolean(loading)} tone="blue" icon={Wrench} label="Setup" />
                )}
            </div>
        </>
    );
}

function DeployTab({ deploy, deployBadge, capabilities, capabilityReasons, loading, onDeploy, provider }) {
    const [showSteps, setShowSteps] = useState(false);

    return (
        <>
            <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
                <StatusRow label="Deploy Status" value={humanize(deploy.status || 'idle')} tone={STATUS_TONE[deploy.status || 'idle']} />
                <DataRow label="Deploy Mode" value={deployBadge} />
                <DataRow label="Message" value={deploy.message || capabilityReasons.deploy || 'No deploy activity'} />
                <DataRow label="Provider Type" value={deploy.mode || provider.type} />
                <DataRow label="Last Deployed" value={deploy.finished_at ? new Date(deploy.finished_at).toLocaleString() : 'Never'} />
                <DataRow
                    label="Completed Steps"
                    value={String(deploy.completed_steps?.length || deploy.steps?.filter((s) => s.success)?.length || 0)}
                />
            </div>

            <div className="flex flex-wrap gap-2 mb-4">
                {capabilities.deploy && (
                    <ActionBtn onClick={onDeploy} disabled={Boolean(loading)} tone="purple" icon={Rocket} label="Deploy" />
                )}
                {!capabilities.deploy && capabilityReasons.deploy && (
                    <Notice tone="yellow" message={capabilityReasons.deploy} />
                )}
            </div>

            {(deploy.logs || deploy.steps?.length || deploy.status !== 'idle') && (
                <div className="space-y-3">
                    {deploy.logs ? (
                        <div className="rounded-xl border border-gray-800 bg-gray-950/70 p-4">
                            <div className="mb-2 flex items-center justify-between gap-3">
                                <span className="font-medium text-sm text-white">Console Logs</span>
                                {deploy.status === 'deploying' && <Loader2 size={14} className="text-blue-400 animate-spin" />}
                            </div>
                            <div className="h-[400px] overflow-y-auto font-mono text-[11px] leading-relaxed text-gray-300 whitespace-pre-wrap break-words rounded bg-black/40 p-3 ring-1 ring-inset ring-white/5 scrollbar-thin flex flex-col-reverse">
                                <div>{deploy.logs}</div>
                            </div>
                        </div>
                    ) : (
                        (deploy.steps?.length ? deploy.steps : [{ name: 'No steps recorded', success: true, output: '' }]).map((step) => (
                            <div key={step.name} className="rounded-xl border border-gray-800 bg-gray-950/70 p-4">
                                <div className="mb-2 flex items-center justify-between gap-3">
                                    <span className="font-medium text-sm text-white">{step.name}</span>
                                    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${
                                        step.skipped
                                            ? 'border-gray-600 text-gray-400'
                                            : step.success
                                                ? 'border-green-500/25 text-green-300'
                                                : 'border-red-500/25 text-red-300'
                                    }`}>
                                        {step.skipped ? 'Skipped' : step.success ? 'Success' : 'Failed'}
                                    </span>
                                </div>
                                {step.entrypoint && <div className="mb-2 text-xs text-gray-500">{step.entrypoint}</div>}
                                <pre className="whitespace-pre-wrap break-words text-xs text-gray-400">
                                    {step.output || 'No output'}
                                </pre>
                            </div>
                        ))
                    )}
                    
                    {deploy.test_results?.length > 0 && (
                        <div className="mt-6 border-t border-white/[0.06] pt-6">
                            <h4 className="text-sm font-semibold text-white mb-3">Deployment Tests</h4>
                            <div className="space-y-2">
                                {deploy.test_results.map((test, i) => (
                                    <div key={i} className="flex items-center justify-between p-3 rounded-lg border border-gray-800 bg-gray-950/50">
                                        <div className="flex items-center gap-3">
                                            {test.success ? (
                                                <div className="h-2 w-2 rounded-full bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]" />
                                            ) : (
                                                <div className="h-2 w-2 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.6)]" />
                                            )}
                                            <span className="text-sm font-medium text-gray-200">{test.name}</span>
                                        </div>
                                        <span className={`text-xs ${test.success ? 'text-gray-400' : 'text-red-400'}`}>
                                            {test.message}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </>
    );
}

function SyncTab({
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

            {/* Inline storage breakdown */}
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

function DiagnosticsTab({ diagnostics, runtime, credentialSummary, providerFailures }) {
    const warnings = diagnostics.warnings || [];
    const errors = diagnostics.errors || [];
    const hasIssues = warnings.length > 0 || errors.length > 0 || providerFailures > 0;

    return (
        <>
            <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
                <DataRow label="Backend URL" value={diagnostics.worker?.backend_url} mono />
                <DataRow label="Worker URL" value={diagnostics.worker?.worker_url} mono />
                <DataRow label="Runtime Mode" value={diagnostics.worker?.mode || runtime.mode} />
                <DataRow label="Credential Ready" value={credentialSummary.ready ? 'Yes' : 'Missing'} />
                <DataRow label="GPU" value={diagnostics.worker?.gpu || runtime.gpu || 'N/A'} />
                <DataRow label="Version" value={diagnostics.worker?.version || runtime.version || 'N/A'} />
                {credentialSummary.configured_fields?.length > 0 && (
                    <DataRow label="Configured Secrets" value={credentialSummary.configured_fields.join(', ')} />
                )}
            </div>

            {/* Health status */}
            <div className="space-y-2">
                {providerFailures > 0 && (
                    <div className="flex items-start gap-3 rounded-lg border border-amber-500/20 bg-amber-500/8 p-3">
                        <AlertTriangle size={16} className="text-amber-400 mt-0.5 flex-shrink-0" />
                        <span className="text-sm text-amber-200">{providerFailures} consecutive failure{providerFailures !== 1 ? 's' : ''} recorded</span>
                    </div>
                )}
                {errors.map((msg) => (
                    <div key={`e-${msg}`} className="flex items-start gap-3 rounded-lg border border-red-500/20 bg-red-500/8 p-3">
                        <XCircle size={16} className="text-red-400 mt-0.5 flex-shrink-0" />
                        <span className="text-sm text-red-200">{msg}</span>
                    </div>
                ))}
                {warnings.map((msg) => (
                    <div key={`w-${msg}`} className="flex items-start gap-3 rounded-lg border border-yellow-500/20 bg-yellow-500/8 p-3">
                        <AlertTriangle size={16} className="text-yellow-400 mt-0.5 flex-shrink-0" />
                        <span className="text-sm text-yellow-200">{msg}</span>
                    </div>
                ))}
                {!hasIssues && (
                    <div className="flex items-center gap-3 rounded-lg border border-green-500/20 bg-green-500/8 p-3">
                        <CheckCircle size={16} className="text-green-400 flex-shrink-0" />
                        <span className="text-sm text-green-200">All diagnostics clear — no issues detected</span>
                    </div>
                )}
            </div>
        </>
    );
}
