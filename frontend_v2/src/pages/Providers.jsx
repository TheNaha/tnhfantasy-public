import { useCallback, useMemo, useState } from 'react';
import { Download, Plus, RefreshCw, Search, Wrench } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import toast from 'react-hot-toast';
import ProviderListItem from '../components/providers/ProviderListItem';
import ProviderDetailPanel from '../components/providers/ProviderDetailPanel';
import LoadBalancerBar from '../components/providers/LoadBalancerBar';
import ProviderModal from '../components/providers/ProviderModal';
import AddModelToProviderModal from '../components/providers/AddModelToProviderModal';
import ReconciliationStatus from '../components/providers/ReconciliationStatus';
import ConfirmationModal from '../components/ConfirmationModal';
import { providersApi } from '../api';
import useReconciliationStore from '../store/reconciliationStore';
import useProvidersPageData, { useProviderMutations } from '../hooks/useProvidersPageData';

const FILTERS = [
    { id: 'all', label: 'All' },
    { id: 'managed', label: 'Managed' },
    { id: 'manual', label: 'Manual' },
    { id: 'issues', label: 'Needs Attention' },
];

export default function Providers() {
    const [showAddModal, setShowAddModal] = useState(false);
    const [showAddModelModal, setShowAddModelModal] = useState(false);
    const [editingProvider, setEditingProvider] = useState(null);
    const [reconcilingProviderId, setReconcilingProviderId] = useState(null);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [search, setSearch] = useState('');
    const [filter, setFilter] = useState('all');
    const [selectedProviderId, setSelectedProviderId] = useState(null);
    const [resetConfirm, setResetConfirm] = useState({ isOpen: false, providerId: null });

    const { startReconciliation } = useReconciliationStore();
    const {
        providers,
        lbConfig,
        lbStats,
        isLoading,
        refreshAll: refreshProviderData,
    } = useProvidersPageData();
    const {
        actionLoading,
        startContainer,
        stopContainer,
        restartContainer,
        deployProvider,
        reconcileProvider,
        setupProvider,
        resetProviderModelStatus,
        toggleProviderEnabled,
        deleteProvider,
        updateLoadBalancerStrategy,
        saveProvider,
    } = useProviderMutations();

    const refreshAll = useCallback(async () => {
        setIsRefreshing(true);
        try {
            await refreshProviderData();
        } finally {
            setIsRefreshing(false);
        }
    }, [refreshProviderData]);

    const providerStatsMap = useMemo(() => {
        const map = new Map();
        if (lbStats?.provider_stats) {
            lbStats.provider_stats.forEach((stat) => map.set(stat.id, stat));
        }
        return map;
    }, [lbStats]);

    const filteredProviders = useMemo(() => {
        return providers.filter((provider) => {
            const query = search.trim().toLowerCase();
            const matchesSearch = !query || [
                provider.id,
                provider.type,
                provider.credential_summary?.account_label,
            ].filter(Boolean).some((value) => value.toLowerCase().includes(query));

            const hasIssues = (provider.diagnostics?.warnings?.length || 0) > 0
                || (provider.diagnostics?.errors?.length || 0) > 0
                || (provider.deploy_state?.status === 'failed')
                || (provider.reconciliation_state?.status === 'failed');

            const matchesFilter = (
                filter === 'all'
                || (filter === 'managed' && provider.capabilities?.managed_deploy)
                || (filter === 'manual' && provider.capabilities?.manual_deploy)
                || (filter === 'issues' && hasIssues)
            );

            return matchesSearch && matchesFilter;
        });
    }, [filter, providers, search]);

    const selectedProvider = useMemo(
        () => providers.find((p) => p.id === selectedProviderId) || null,
        [providers, selectedProviderId]
    );

    // ── Actions ──

    const handleStart = async (providerId) => {
        try { await startContainer(providerId); }
        catch (error) { toast.error(`Failed to start container: ${error.message}`); }
    };
    const handleStop = async (providerId) => {
        try { await stopContainer(providerId); }
        catch (error) { toast.error(`Failed to stop container: ${error.message}`); }
    };
    const handleRestart = async (providerId) => {
        try { await restartContainer(providerId); }
        catch (error) { toast.error(`Failed to restart container: ${error.message}`); }
    };
    const handleDeploy = async (providerId) => {
        try {
            const result = await deployProvider(providerId);
            const type = result.provider_type || 'provider';
            toast.success(`${type.charAt(0).toUpperCase() + type.slice(1)} deploy completed`);
        } catch (error) { toast.error(`Deploy failed: ${error.message}`); }
    };
    const handleReconcile = async (providerId) => {
        try {
            await reconcileProvider(providerId);
            startReconciliation(providerId);
            setReconcilingProviderId(providerId);
        } catch (error) { toast.error(`Reconciliation failed: ${error.message}`); }
    };
    const handleSetup = async (providerId) => {
        try {
            const result = await setupProvider(providerId);
            toast.success(result.message || 'Provider setup completed');
        } catch (error) { toast.error(`Setup failed: ${error.message}`); }
    };
    const handleDelete = async (providerId) => {
        try {
            await deleteProvider(providerId);
            if (selectedProviderId === providerId) setSelectedProviderId(null);
            toast.success('Provider deleted');
        } catch (error) { toast.error(`Delete failed: ${error.message}`); }
    };
    const handleToggleEnabled = async (providerId, currentlyEnabled) => {
        try { await toggleProviderEnabled(providerId, currentlyEnabled); }
        catch (error) { toast.error(`Toggle failed: ${error.message}`); }
    };
    const handleSaveProvider = async (provider, payload) => {
        await saveProvider(provider, payload);
    };
    const handleCleanupState = async () => {
        try {
            const result = await providersApi.cleanupState();
            await refreshAll();
            toast.success(
                `Cleanup: ${result.orphaned_statuses_removed || 0} orphaned removed, ${result.stale_downloading_reset || 0} stale reset.`,
            );
        } catch (error) { toast.error(`Cleanup failed: ${error.message}`); }
    };
    const handleUpdateLBStrategy = async (strategy) => {
        try { await updateLoadBalancerStrategy(strategy, lbConfig); }
        catch (error) { toast.error(`Strategy update failed: ${error.message}`); }
    };
    const executeResetStatus = async () => {
        const providerId = resetConfirm.providerId;
        setResetConfirm({ isOpen: false, providerId: null });
        try {
            const result = await resetProviderModelStatus(providerId);
            toast.success(`Reset complete! ${result.deleted_count || 0} entries cleared.`);
        } catch (error) { toast.error(`Reset failed: ${error.message}`); }
    };

    // ── Stats helpers ──
    const onlineCount = providers.filter((p) => {
        const s = p.runtime_state?.status;
        return p.enabled && ['running', 'active', 'connected'].includes(s);
    }).length;

    return (
        <motion.div
            className="mx-auto max-w-7xl p-6"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
        >
            {/* ── Page Header ── */}
            <div className="mb-6">
                <h1 className="mb-1 text-3xl font-bold gradient-header">Providers</h1>
                <p className="text-sm text-gray-500">
                    {providers.length} provider{providers.length !== 1 ? 's' : ''} configured
                    {onlineCount > 0 && (
                        <span className="text-green-400"> · {onlineCount} online</span>
                    )}
                </p>
            </div>

            {/* ── Toolbar ── */}
            <div className="toolbar-strip mb-6">
                <button className="primary" onClick={() => setShowAddModal(true)}>
                    <Plus size={14} />
                    Add Provider
                </button>
                <button onClick={() => setShowAddModelModal(true)} disabled={providers.length === 0}>
                    <Download size={14} />
                    Add Model
                </button>
                <button onClick={refreshAll} disabled={isRefreshing}>
                    <RefreshCw size={14} className={isRefreshing ? 'animate-spin' : ''} />
                    Refresh
                </button>
                <button className="warning" onClick={handleCleanupState}>
                    <Wrench size={14} />
                    Cleanup
                </button>
            </div>

            {/* ── Load Balancer Bar ── */}
            <LoadBalancerBar
                config={lbConfig}
                stats={lbStats}
                onUpdateStrategy={handleUpdateLBStrategy}
            />

            {/* ── Search + Filters ── */}
            <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <label className="relative block max-w-md flex-1">
                    <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
                    <input
                        type="text"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder="Search providers..."
                        className="w-full rounded-lg border border-gray-800 bg-gray-950/60 py-2.5 pl-9 pr-4 text-sm text-white outline-none transition-colors focus:border-blue-500/50 placeholder:text-gray-600"
                    />
                </label>

                <div className="flex flex-wrap gap-1.5">
                    {FILTERS.map((option) => (
                        <button
                            key={option.id}
                            onClick={() => setFilter(option.id)}
                            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                                filter === option.id
                                    ? 'border-blue-500/30 bg-blue-500/15 text-blue-300'
                                    : 'border-gray-800 bg-gray-950/40 text-gray-500 hover:text-gray-300 hover:bg-gray-900/60'
                            }`}
                        >
                            {option.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* ── Provider List ── */}
            {isLoading ? (
                <div className="flex h-48 items-center justify-center rounded-xl border border-gray-800/60 bg-gray-950/30">
                    <div className="text-sm text-gray-500">Loading providers...</div>
                </div>
            ) : filteredProviders.length > 0 ? (
                <div className="space-y-2">
                    {filteredProviders.map((provider) => (
                        <ProviderListItem
                            key={provider.id}
                            provider={provider}
                            loading={actionLoading[provider.id]}
                            isSelected={selectedProviderId === provider.id}
                            onSelect={(id) => setSelectedProviderId(selectedProviderId === id ? null : id)}
                            onToggleEnabled={handleToggleEnabled}
                            onEdit={() => setEditingProvider(provider)}
                            onDelete={() => handleDelete(provider.id)}
                            providerFailures={providerStatsMap.get(provider.id)?.failures ?? 0}
                            jobsAssigned={providerStatsMap.get(provider.id)?.jobs_assigned ?? 0}
                        />
                    ))}
                </div>
            ) : (
                <div className="flex h-48 flex-col items-center justify-center rounded-xl border border-gray-800/60 bg-gray-950/30 text-center">
                    <p className="mb-1 text-sm font-medium text-white">
                        {providers.length === 0 ? 'No providers configured' : 'No matches'}
                    </p>
                    <p className="mb-4 max-w-sm text-xs text-gray-500">
                        {providers.length === 0
                            ? 'Create a provider to start dispatching inference jobs.'
                            : 'Adjust your search or filter.'}
                    </p>
                    {providers.length === 0 && (
                        <button
                            onClick={() => setShowAddModal(true)}
                            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition-colors hover:bg-blue-700"
                        >
                            <Plus size={14} />
                            Add Provider
                        </button>
                    )}
                </div>
            )}

            {/* ── Side Drawer ── */}
            <AnimatePresence>
                {selectedProvider && (
                    <ProviderDetailPanel
                        provider={selectedProvider}
                        onClose={() => setSelectedProviderId(null)}
                        loading={actionLoading[selectedProvider.id]}
                        onStart={() => handleStart(selectedProvider.id)}
                        onStop={() => handleStop(selectedProvider.id)}
                        onRestart={() => handleRestart(selectedProvider.id)}
                        onDeploy={() => handleDeploy(selectedProvider.id)}
                        onReconcile={() => handleReconcile(selectedProvider.id)}
                        onResetStatus={() => setResetConfirm({ isOpen: true, providerId: selectedProvider.id })}
                        onSetup={() => handleSetup(selectedProvider.id)}
                        providerFailures={providerStatsMap.get(selectedProvider.id)?.failures ?? 0}
                        jobsAssigned={providerStatsMap.get(selectedProvider.id)?.jobs_assigned ?? 0}
                    />
                )}
            </AnimatePresence>

            {/* ── Modals ── */}
            {(showAddModal || editingProvider) && (
                <ProviderModal
                    provider={editingProvider}
                    onClose={() => { setShowAddModal(false); setEditingProvider(null); }}
                    onSave={async () => { setShowAddModal(false); setEditingProvider(null); await refreshAll(); }}
                    saveProvider={handleSaveProvider}
                />
            )}

            {showAddModelModal && (
                <AddModelToProviderModal
                    providers={providers}
                    onClose={() => setShowAddModelModal(false)}
                />
            )}

            {reconcilingProviderId && (
                <ReconciliationStatus
                    providerId={reconcilingProviderId}
                    onClose={async () => { setReconcilingProviderId(null); await refreshAll(); }}
                />
            )}

            <ConfirmationModal
                isOpen={resetConfirm.isOpen}
                onClose={() => setResetConfirm({ isOpen: false, providerId: null })}
                onConfirm={executeResetStatus}
                title="Reset Provider Status"
                message="This clears persisted provider sync rows and forces the next reconciliation to rebuild model state."
                isDangerous
                confirmText="Reset Provider"
            />
        </motion.div>
    );
}
