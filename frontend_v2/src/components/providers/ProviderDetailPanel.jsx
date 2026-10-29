import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
    Circle,
    Loader2,
    Server,
    StopCircle,
    X,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { providerBadgeToneClass, summarizeProviderStatus } from '../../utils/providerStatus';
import JobCard from '../dashboard/JobCard';

import { useActiveJobs } from '../../hooks/useActiveJobs';

import RuntimeTab from './tabs/RuntimeTab';
import SyncTab from './tabs/SyncTab';
import DiagnosticsTab from './tabs/DiagnosticsTab';
import CredentialsTab from './tabs/CredentialsTab';
import LogsTab from './tabs/LogsTab';
import DeployTab from './tabs/DeployTab';
import { statusDotClass, humanize } from './tabs/utils';
import { useEscapeKey } from '../../hooks/useEscapeKey';
import { getDeployTargetForProvider } from '../../utils/providerStatus';
import { providersApi } from '../../api';

const EMPTY_OBJECT = Object.freeze({});

const TABS = [
    { id: 'runtime', label: 'Runtime' },
    { id: 'jobs', label: 'Active Jobs' },
    { id: 'logs', label: 'Activity & Logs' },
    { id: 'deploy', label: 'Deploy Worker' },
    { id: 'sync', label: 'Model Sync' },
    { id: 'credentials', label: 'Credentials' },
    { id: 'diagnostics', label: 'Diagnostics' },
];

export default function ProviderDetailPanel({
    provider,
    onClose,
    loading,
    onReconcile, onQuickSync, onResetStatus, onSetup, onDeploy,
    providerFailures = 0,
    jobsAssigned = 0,
    initialTab = 'runtime',
}) {
    const [activeTab, setActiveTab] = useState(initialTab);
    const [prevInitialTab, setPrevInitialTab] = useState(initialTab);
    const panelRef = useRef(null);
    if (initialTab !== prevInitialTab) {
        setPrevInitialTab(initialTab);
        setActiveTab(initialTab);
    }

    // This covers the page behind it, so it has to answer the keyboard: Escape
    // dismisses, focus lands inside on open and goes back to the trigger on
    // close. (No portal — AnimatePresence owns the mount, and unmounting it
    // early would kill the exit animation.)
    useEscapeKey(onClose);
    useEffect(() => {
        const panel = panelRef.current;
        const previouslyFocused = document.activeElement;
        panel?.focus();
        return () => {
            if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
        };
    }, []);
    const { data: baseJobs = [] } = useActiveJobs();
    const activeJobs = useMemo(() => {
        return baseJobs.filter(j => 
            j.provider_id === provider.id && 
            !['completed', 'failed', 'cancelled', 'error'].includes(j.status)
        );
    }, [baseJobs, provider.id]);

    const runtime = provider.runtime_state ?? EMPTY_OBJECT;
    const reconciliation = provider.reconciliation_state ?? EMPTY_OBJECT;
    const modelSync = provider.model_sync ?? EMPTY_OBJECT;
    const storage = provider.storage ?? EMPTY_OBJECT;
    const storageLoaded = provider.storage != null;
    const diagnostics = provider.diagnostics ?? EMPTY_OBJECT;
    const capabilities = provider.capabilities ?? EMPTY_OBJECT;
    const credentialSummary = provider.credential_summary ?? EMPTY_OBJECT;

    const runtimeStatus = runtime.status ?? (runtime.connected ? 'active' : 'stopped');

    const statusSummary = useMemo(
        () => summarizeProviderStatus(provider, {
            actionLabel: loading || null,
            jobsAssigned,
            providerFailures,
        }),
        [jobsAssigned, loading, provider, providerFailures],
    );

    const [shutdownState, setShutdownState] = useState({ shutting: false, error: null });

    const handleShutdown = async () => {
        setShutdownState({ shutting: true, error: null });
        try {
            await providersApi.shutdown(provider.id);
            setShutdownState({ shutting: false, error: null });
        } catch (err) {
            setShutdownState({ shutting: false, error: err?.message || 'Shutdown failed' });
        }
    };

    if (typeof document === 'undefined') return null;

    return createPortal(
        <motion.div
            className="fixed inset-y-0 right-0 left-0 lg:left-64 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 sm:p-6 lg:p-8"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
        >
            <motion.div
                ref={panelRef}
                role="dialog"
                aria-modal="true"
                aria-label={`${provider.id} provider`}
                tabIndex={-1}
                className="relative flex flex-col w-full max-w-5xl xl:max-w-6xl h-[88vh] max-h-[92vh] overflow-hidden rounded-2xl border border-white/10 bg-gray-950 shadow-2xl outline-none"
                initial={{ scale: 0.96, opacity: 0, y: 12 }}
                animate={{ scale: 1, opacity: 1, y: 0 }}
                exit={{ scale: 0.96, opacity: 0, y: 12 }}
                transition={{ type: 'spring', damping: 30, stiffness: 350 }}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex-shrink-0 border-b border-white/[0.06] bg-gray-950/95 backdrop-blur-xl px-6 pt-5 pb-0">
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
                                <div className="flex items-center gap-2">
                                    <h2 className="text-xl font-bold text-white truncate">
                                        {provider.id}
                                    </h2>
                                    <span className="rounded-md bg-gray-800/80 px-2 py-0.5 text-xs font-mono text-gray-400 border border-gray-700/60">
                                        {provider.type}
                                    </span>
                                </div>
                                <p className="text-xs text-gray-400 mt-0.5">
                                    {credentialSummary.account_label ? `Account: ${credentialSummary.account_label}` : `${provider.type} provider`}
                                </p>
                            </div>
                        </div>
                        {(() => {
                            const type = provider.type || '';
                            const canShutdown =
                                type.startsWith('modal_') ||
                                type.startsWith('beam_') ||
                                type.startsWith('remote_') ||
                                type === 'modal' ||
                                type === 'beam';
                            if (!canShutdown) return null;
                            return (
                                <button
                                    type="button"
                                    onClick={handleShutdown}
                                    disabled={shutdownState.shutting}
                                    className={`rounded-lg p-2 transition-all duration-300 ${
                                        shutdownState.shutting
                                            ? 'text-blue-400 bg-blue-500/10 cursor-not-allowed'
                                            : 'text-red-400 bg-red-500/10 hover:bg-red-500/20 hover:text-red-300'
                                    }`}
                                    title={shutdownState.shutting ? 'Shutting down…' : 'Shut down worker'}
                                    aria-label="Shut down Provider"
                                >
                                    {shutdownState.shutting ? (
                                        <Loader2 size={14} className="animate-spin text-blue-400" />
                                    ) : (
                                        <StopCircle size={16} />
                                    )}
                                    {shutdownState.error && (
                                        <span className="text-xs text-red-400 ml-1">{shutdownState.error}</span>
                                    )}
                                </button>
                            );
                        })()}
                        <button
                            onClick={onClose}
                            className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-800 hover:text-white"
                            aria-label="Close"
                        >
                            <X size={20} />
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
                        {provider.worker_type !== 'llm' && statusSummary.downloadsActive > 0 && (
                            <span className="metric-chip text-cyan-300 border-cyan-500/20">
                                {statusSummary.downloadsActive} downloading
                            </span>
                        )}
                        {provider.worker_type !== 'llm' && statusSummary.downloadsQueued > 0 && (
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
                        {TABS.filter(tab => {
                            if (provider.worker_type === 'llm' && tab.id === 'sync') {
                                return false;
                            }
                            if (tab.id === 'deploy' && !getDeployTargetForProvider(provider)) {
                                return false;
                            }
                            return true;
                        }).map((tab) => {
                            const label = (runtime.mode === 'in_process' && tab.id === 'runtime') ? 'Overview' : tab.label;
                            return (
                                <button
                                    key={tab.id}
                                    type="button"
                                    className={activeTab === tab.id ? 'active' : ''}
                                    onClick={() => setActiveTab(tab.id)}
                                >
                                    {label}
                                </button>
                            );
                        })}
                    </div>
                </div>

                {/* Tab content */}
                <div className="flex-1 overflow-y-auto p-6 space-y-5">
                    {activeTab === 'runtime' && (
                        <RuntimeTab
                            runtime={runtime}
                            runtimeStatus={runtimeStatus}
                            provider={provider}
                            capabilities={capabilities}
                            loading={loading}
                            onSetup={onSetup}
                            onDeploy={onDeploy || (() => setActiveTab('deploy'))}
                            jobsAssigned={jobsAssigned}
                            providerFailures={providerFailures}
                        />
                    )}
                    {activeTab === 'jobs' && (
                        <div className="space-y-4">
                            {activeJobs.length === 0 ? (
                                <div className="text-center py-8 text-gray-500">
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
                    {activeTab === 'logs' && (
                        <LogsTab providerId={provider.id} />
                    )}
                    {activeTab === 'deploy' && (
                        <DeployTab provider={provider} />
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
                            onQuickSync={onQuickSync}
                            onResetStatus={onResetStatus}
                            providerId={provider.id}
                        />
                    )}
                    {activeTab === 'diagnostics' && (
                        <DiagnosticsTab
                            providerId={provider.id}
                            diagnostics={diagnostics}
                            runtime={runtime}
                            credentialSummary={credentialSummary}
                            providerFailures={providerFailures}
                        />
                    )}
                    {activeTab === 'credentials' && (
                        <CredentialsTab
                            providerId={provider.id}
                            credentialSummary={credentialSummary}
                        />
                    )}
                </div>
            </motion.div>
        </motion.div>,
        document.body
    );
}
