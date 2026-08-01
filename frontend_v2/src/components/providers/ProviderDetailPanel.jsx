import { useMemo, useState } from 'react';
import {
    Circle,
    Server,
    X,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { providerBadgeToneClass, summarizeProviderStatus } from '../../utils/providerStatus';
import JobCard from '../dashboard/JobCard';

import { useActiveJobs } from '../../hooks/useActiveJobs';

import RuntimeTab from './tabs/RuntimeTab';
import DeployTab from './tabs/DeployTab';
import SyncTab from './tabs/SyncTab';
import DiagnosticsTab from './tabs/DiagnosticsTab';
import LiveConsoleTab from './tabs/LiveConsoleTab';
import { statusDotClass, humanize } from './tabs/utils';

const EMPTY_OBJECT = Object.freeze({});

const TABS = [
    { id: 'runtime', label: 'Runtime' },
    { id: 'jobs', label: 'Active Jobs' },
    { id: 'deploy', label: 'Deploy' },
    { id: 'sync', label: 'Model Sync' },
    { id: 'diagnostics', label: 'Diagnostics' },
    { id: 'console', label: 'Live Console' },
];

export default function ProviderDetailPanel({
    provider,
    onClose,
    loading,
    onDeploy, onReconcile, onQuickSync, onResetStatus, onSetup,
    providerFailures = 0,
    jobsAssigned = 0,
}) {
    const [activeTab, setActiveTab] = useState('runtime');
    const { data: baseJobs = [] } = useActiveJobs();
    const activeJobs = useMemo(() => {
        return baseJobs.filter(j => 
            j.provider_id === provider.id && 
            !['completed', 'failed', 'cancelled', 'error'].includes(j.status)
        );
    }, [baseJobs, provider.id]);

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
                            if (provider.worker_type === 'llm' && (tab.id === 'deploy' || tab.id === 'sync')) {
                                return false;
                            }
                            return true;
                        }).map((tab) => (
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
                    {activeTab === 'console' && (
                        <LiveConsoleTab providerId={provider.id} />
                    )}
                </div>
            </motion.div>
        </>
    );
}
