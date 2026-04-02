import { useCallback, useMemo, useState } from 'react';
import { Download, Plus, RefreshCw, Search, Wrench } from 'lucide-react';
import { motion } from 'framer-motion';
import toast from 'react-hot-toast';
import ProviderCard from '../components/providers/ProviderCard';
import ProviderModal from '../components/providers/ProviderModal';
import AddModelToProviderModal from '../components/providers/AddModelToProviderModal';
import ReconciliationStatus from '../components/providers/ReconciliationStatus';
import ConfirmationModal from '../components/ConfirmationModal';
import { providersApi } from '../api';
import useReconciliationStore from '../store/reconciliationStore';
import useProvidersPageData, { useProviderMutations } from '../hooks/useProvidersPageData';

const FILTERS = [
    { id: 'all', label: 'All' },
    { id: 'managed', label: 'Managed Deploy' },
    { id: 'manual', label: 'Manual Deploy' },
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

    const handleStart = async (providerId) => {
        try {
            await startContainer(providerId);
        } catch (error) {
            console.error('Failed to start container:', error);
            toast.error(`Failed to start container: ${error.message}`);
        }
    };

    const handleStop = async (providerId) => {
        try {
            await stopContainer(providerId);
        } catch (error) {
            console.error('Failed to stop container:', error);
            toast.error(`Failed to stop container: ${error.message}`);
        }
    };

    const handleRestart = async (providerId) => {
        try {
            await restartContainer(providerId);
        } catch (error) {
            console.error('Failed to restart container:', error);
            toast.error(`Failed to restart container: ${error.message}`);
        }
    };

    const handleDeploy = async (providerId) => {
        try {
            const result = await deployProvider(providerId);
            const providerType = result.provider_type || 'provider';
            toast.success(`${providerType.charAt(0).toUpperCase() + providerType.slice(1)} deploy completed`);
        } catch (error) {
            console.error('Failed to deploy provider:', error);
            toast.error(`Failed to deploy: ${error.message}`);
        }
    };

    const handleReconcile = async (providerId) => {
        try {
            await reconcileProvider(providerId);
            startReconciliation(providerId);
            setReconcilingProviderId(providerId);
        } catch (error) {
            console.error('Failed to trigger reconciliation:', error);
            toast.error(`Failed to trigger reconciliation: ${error.message}`);
        }
    };

    const handleSetup = async (providerId) => {
        try {
            const result = await setupProvider(providerId);
            toast.success(result.message || 'Provider setup completed');
        } catch (error) {
            console.error('Failed to setup provider:', error);
            toast.error(`Failed to setup provider: ${error.message}`);
        }
    };

    const handleDelete = async (providerId) => {
        try {
            await deleteProvider(providerId);
            toast.success('Provider deleted');
        } catch (error) {
            console.error('Failed to delete provider:', error);
            toast.error(`Failed to delete provider: ${error.message}`);
        }
    };

    const handleToggleEnabled = async (providerId, currentlyEnabled) => {
        try {
            await toggleProviderEnabled(providerId, currentlyEnabled);
        } catch (error) {
            console.error('Failed to toggle provider:', error);
            toast.error(`Failed to toggle provider: ${error.message}`);
        }
    };

    const handleSaveProvider = async (provider, payload) => {
        await saveProvider(provider, payload);
    };

    const handleCleanupState = async () => {
        try {
            const result = await providersApi.cleanupState();
            await refreshAll();
            toast.success(
                `Cleanup complete: ${result.orphaned_statuses_removed || 0} orphaned rows removed, ${result.stale_downloading_reset || 0} stale downloads reset.`,
            );
        } catch (error) {
            console.error('Failed to cleanup provider state:', error);
            toast.error(`Failed to cleanup provider state: ${error.message}`);
        }
    };

    const executeResetStatus = async () => {
        const providerId = resetConfirm.providerId;
        setResetConfirm({ isOpen: false, providerId: null });

        try {
            const result = await resetProviderModelStatus(providerId);
            toast.success(`Reset complete! ${result.deleted_count || 0} entries cleared.`);
        } catch (error) {
            console.error('Failed to reset provider state:', error);
            toast.error(`Failed to reset: ${error.message}`);
        }
    };

    const handleUpdateLBStrategy = async (strategy) => {
        try {
            await updateLoadBalancerStrategy(strategy, lbConfig);
        } catch (error) {
            console.error('Failed to update load balancer:', error);
            toast.error(`Failed to update load balancer: ${error.message}`);
        }
    };

    return (
        <motion.div
            className="mx-auto max-w-7xl p-6"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
        >
            <div className="mb-8 flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
                <div>
                    <h1 className="mb-2 text-3xl font-bold text-white">Providers</h1>
                    <p className="max-w-2xl text-gray-400">
                        Manage runtime containers, deploy targets, and model sync from one canonical provider record.
                    </p>
                </div>

                <div className="flex flex-wrap gap-3">
                    <button
                        onClick={() => setShowAddModelModal(true)}
                        disabled={providers.length === 0}
                        className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-white transition-colors hover:bg-purple-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        <Download size={16} />
                        Add Model
                    </button>
                    <button
                        onClick={refreshAll}
                        disabled={isRefreshing}
                        className="inline-flex items-center gap-2 rounded-lg border border-gray-700 bg-gray-800/70 px-4 py-2 text-gray-200 transition-colors hover:bg-gray-700 disabled:opacity-50"
                    >
                        <RefreshCw size={16} className={isRefreshing ? 'animate-spin' : ''} />
                        Refresh
                    </button>
                    <button
                        onClick={handleCleanupState}
                        className="inline-flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-amber-200 transition-colors hover:bg-amber-500/15"
                    >
                        <Wrench size={16} />
                        Cleanup State
                    </button>
                    <button
                        onClick={() => setShowAddModal(true)}
                        className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-white transition-colors hover:bg-blue-700"
                    >
                        <Plus size={16} />
                        Add Provider
                    </button>
                </div>
            </div>

            {lbConfig && (
                <div className="mb-8 rounded-2xl border border-gray-700 bg-gray-900/70 p-6">
                    <div className="mb-5 flex flex-col gap-4 border-b border-gray-800 pb-4 md:flex-row md:items-center md:justify-between">
                        <div>
                            <h2 className="text-xl font-semibold text-white">Load Balancer</h2>
                            <p className="text-sm text-gray-400">Distribute jobs across enabled providers using one shared strategy.</p>
                        </div>
                        <div className="flex gap-2">
                            <span className="rounded-full border border-green-500/25 bg-green-500/10 px-3 py-1 text-sm font-medium text-green-300">
                                {lbStats?.total_providers || 0} active
                            </span>
                            <span className="rounded-full border border-gray-700 bg-gray-800 px-3 py-1 text-sm text-gray-300">
                                {lbConfig.fallback_enabled ? 'Fallback enabled' : 'Fallback disabled'}
                            </span>
                        </div>
                    </div>

                    <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-6">
                        {[
                            { id: 'round-robin', label: 'Round Robin' },
                            { id: 'random', label: 'Random' },
                            { id: 'priority', label: 'Priority' },
                            { id: 'least-connections', label: 'Least Connections' },
                            { id: 'priority-round-robin', label: 'Priority + RR' },
                            { id: 'priority-least-connections', label: 'Priority + LC' },
                        ].map((strategy) => (
                            <button
                                key={strategy.id}
                                onClick={() => handleUpdateLBStrategy(strategy.id)}
                                className={`rounded-xl border px-3 py-3 text-left text-sm transition-colors ${
                                    lbConfig.strategy === strategy.id
                                        ? 'border-blue-500/40 bg-blue-600 text-white'
                                        : 'border-gray-700 bg-gray-800/70 text-gray-300 hover:bg-gray-700'
                                }`}
                            >
                                {strategy.label}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            <div className="mb-6 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <label className="relative block max-w-md flex-1">
                    <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                    <input
                        type="text"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        placeholder="Search by provider ID, type, or account label"
                        className="w-full rounded-xl border border-gray-700 bg-gray-900/80 py-3 pl-10 pr-4 text-white outline-none transition-colors focus:border-blue-500"
                    />
                </label>

                <div className="flex flex-wrap gap-2">
                    {FILTERS.map((option) => (
                        <button
                            key={option.id}
                            onClick={() => setFilter(option.id)}
                            className={`rounded-full border px-3 py-2 text-sm transition-colors ${
                                filter === option.id
                                    ? 'border-blue-500/40 bg-blue-600 text-white'
                                    : 'border-gray-700 bg-gray-900/70 text-gray-300 hover:bg-gray-800'
                            }`}
                        >
                            {option.label}
                        </button>
                    ))}
                </div>
            </div>

            {isLoading ? (
                <div className="flex h-64 items-center justify-center rounded-2xl border border-gray-800 bg-gray-900/40">
                    <div className="text-gray-400">Loading providers...</div>
                </div>
            ) : filteredProviders.length > 0 ? (
                <div className="grid gap-6 xl:grid-cols-2">
                    {filteredProviders.map((provider) => (
                        <ProviderCard
                            key={provider.id}
                            provider={provider}
                            loading={actionLoading[provider.id]}
                            onStart={() => handleStart(provider.id)}
                            onStop={() => handleStop(provider.id)}
                            onRestart={() => handleRestart(provider.id)}
                            onDeploy={() => handleDeploy(provider.id)}
                            onReconcile={() => handleReconcile(provider.id)}
                            onResetStatus={() => setResetConfirm({ isOpen: true, providerId: provider.id })}
                            onSetup={() => handleSetup(provider.id)}
                            onEdit={() => setEditingProvider(provider)}
                            onDelete={() => handleDelete(provider.id)}
                            onToggleEnabled={handleToggleEnabled}
                            providerFailures={providerStatsMap.get(provider.id)?.failures ?? 0}
                            jobsAssigned={providerStatsMap.get(provider.id)?.jobs_assigned ?? 0}
                        />
                    ))}
                </div>
            ) : (
                <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-gray-800 bg-gray-900/40 text-center">
                    <p className="mb-2 text-lg font-medium text-white">
                        {providers.length === 0 ? 'No providers configured' : 'No providers match this view'}
                    </p>
                    <p className="mb-4 max-w-md text-sm text-gray-400">
                        {providers.length === 0
                            ? 'Create a provider to configure runtime, deployment, and sync in one place.'
                            : 'Adjust the search query or filter to see more providers.'}
                    </p>
                    <button
                        onClick={() => setShowAddModal(true)}
                        className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-white transition-colors hover:bg-blue-700"
                    >
                        <Plus size={16} />
                        Add Provider
                    </button>
                </div>
            )}

            {(showAddModal || editingProvider) && (
                <ProviderModal
                    provider={editingProvider}
                    onClose={() => {
                        setShowAddModal(false);
                        setEditingProvider(null);
                    }}
                    onSave={async () => {
                        setShowAddModal(false);
                        setEditingProvider(null);
                        await refreshAll();
                    }}
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
                    onClose={async () => {
                        setReconcilingProviderId(null);
                        await refreshAll();
                    }}
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
