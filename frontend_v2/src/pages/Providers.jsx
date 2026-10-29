import { useCallback, useMemo, useState } from 'react';
import { Download, Plus, RefreshCw, Rocket, Search, Wrench } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import toast from 'react-hot-toast';
import ProviderListItem from '../components/providers/ProviderListItem';
import ProviderDetailPanel from '../components/providers/ProviderDetailPanel';
import LoadBalancerBar from '../components/providers/LoadBalancerBar';
import ProviderModal from '../components/providers/ProviderModal';
import AddModelToProviderModal from '../components/providers/AddModelToProviderModal';
import ActionOutputModal from '../components/providers/ActionOutputModal';
import { useConfirmation } from '../store/confirmationStore';
import { providersApi } from '../api';
import { summarizeProviderStatus, transportFromProvider, providerLifecycleState, countProviderStates } from '../utils/providerStatus';
import useProvidersPageData, { useProviderMutations } from '../hooks/useProvidersPageData';
import { QueryErrorState } from '../components/common/QueryState';

const FILTERS = [
    { id: 'all', label: 'All' },
    { id: 'image', label: 'Image' },
    { id: 'llm', label: 'LLM' },
    { id: 'tts', label: 'Voice' },
    { id: 'hybrid', label: 'Hybrid' },
    { id: 'issues', label: 'Needs Attention' },
];

export default function Providers() {
    const [showAddModal, setShowAddModal] = useState(false);
    const [showAddModelModal, setShowAddModelModal] = useState(false);
    const [editingProvider, setEditingProvider] = useState(null);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [search, setSearch] = useState('');
    const [filter, setFilter] = useState('all');
    const [stateFilter, setStateFilter] = useState('all');
    const [selectedProviderId, setSelectedProviderId] = useState(null);
    const [drawerTab, setDrawerTab] = useState('runtime');
    const [actionOutput, setActionOutput] = useState(null);
    const { confirm } = useConfirmation();

    const {
        providers,
        lbConfig,
        lbStats,
        isLoading,
        isError,
        error,
        refreshAll: refreshProviderData,
    } = useProvidersPageData();
    const {
        actionLoading,
        reconcileProvider,
        quickSyncProvider,
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

            const hasIssues = provider.enabled && (
                (provider.diagnostics?.warnings?.length || 0) > 0
                || (provider.diagnostics?.errors?.length || 0) > 0
                || (provider.reconciliation_state?.status === 'failed')
            );

            const matchesStateFilter =
                stateFilter === 'all' || providerLifecycleState(provider) === stateFilter;

            const matchesFilter = (
                filter === 'all'
                || (filter === 'image' && (provider.worker_type === 'image' || provider.worker_type === 'hybrid' || (!provider.worker_type && !provider.capabilities?.length) || (Array.isArray(provider.capabilities) && provider.capabilities.includes('image'))))
                || (filter === 'llm' && (provider.worker_type === 'llm' || provider.worker_type === 'hybrid' || (Array.isArray(provider.capabilities) && provider.capabilities.includes('llm'))))
                || (filter === 'tts' && (provider.worker_type === 'tts' || (Array.isArray(provider.capabilities) && provider.capabilities.includes('tts'))))
                || (filter === 'hybrid' && (provider.worker_type === 'hybrid' || (Array.isArray(provider.capabilities) && provider.capabilities.length > 1)))
                || (filter === 'issues' && hasIssues)
            );

            return matchesSearch && matchesFilter && matchesStateFilter;
        });
    }, [filter, providers, search, stateFilter]);

    const selectedProvider = useMemo(
        () => providers.find((p) => p.id === selectedProviderId) || null,
        [providers, selectedProviderId]
    );

    // ── Actions ──

    const handleReconcile = async (providerId) => {
        try {
            await reconcileProvider(providerId);
        } catch (error) { toast.error(`Reconciliation failed: ${error.message}`); }
    };

    const handleQuickSync = async (providerId) => {
        try {
            await quickSyncProvider(providerId);
        } catch (error) { toast.error(`Quick sync failed: ${error.message}`); }
    };
    const handleSetup = async (providerId) => {
        try {
            const result = await setupProvider(providerId);
            toast.success(result.message || 'Provider setup completed');
            setActionOutput({
                title: `Setup: ${providerId}`,
                status: 'success',
                message: result.message || 'Provider setup completed',
                details: JSON.stringify(result, null, 2),
            });
        } catch (error) {
            toast.error(`Setup failed: ${error.message}`);
            setActionOutput({
                title: `Setup: ${providerId}`,
                status: 'failed',
                message: error.message,
                details: error?.response?.data ? JSON.stringify(error.response.data, null, 2) : error.stack || error.message,
            });
        }
    };
    const handleDeployProvider = (provider) => {
        if (!provider) return;
        setSelectedProviderId(provider.id);
        setDrawerTab('deploy');
    };

    const handleDelete = async (providerId) => {
        // Destructive and immediate — no confirmation was wired up, so a stray
        // click on the delete icon removed the provider and its model status
        // records outright.
        const ok = await confirm({
            title: 'Delete Provider',
            message: `Delete "${providerId}" and its model status records? Jobs already queued for it will fail.`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
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
    const executeResetStatus = async (providerId) => {
        try {
            const result = await resetProviderModelStatus(providerId);
            toast.success(`Reset complete! ${result.deleted_count || 0} entries cleared.`);
        } catch (error) { toast.error(`Reset failed: ${error.message}`); }
    };

    // ── Stats helpers ──
    const onlineCount = providers.filter((p) => summarizeProviderStatus(p).isOnline).length;
    const pausedCount = providers.filter((p) => !p.enabled).length;

    const { counts: stateCounts } = useMemo(() => countProviderStates(providers), [providers]);
    const inFlightJobs = useMemo(() => {
        let total = 0;
        if (lbStats?.provider_stats) {
            lbStats.provider_stats.forEach((stat) => {
                total += stat.jobs_assigned ?? 0;
            });
        }
        return total;
    }, [lbStats]);

    return (
        <motion.div
            className="mx-auto max-w-7xl"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
        >
            {/* ── Page Header ── */}
            <div className="mb-6">
                <h1 className="text-2xl md:text-3xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-500 drop-shadow-md tracking-tight mb-1">Providers</h1>
                <p className="text-sm text-gray-400 font-medium tracking-wide">
                    {providers.length} provider{providers.length !== 1 ? 's' : ''} configured
                    {onlineCount > 0 && (
                        <span className="text-emerald-400 font-bold ml-1">· {onlineCount} online</span>
                    )}
                    {pausedCount > 0 && (
                        <span className="text-gray-400 font-medium ml-1">· {pausedCount} paused</span>
                    )}
                </p>
            </div>

            {/* ── Toolbar ── */}
            <div className="flex flex-wrap gap-3 mb-8">
                <button className="bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white px-5 py-2.5 rounded-xl font-bold transition-all duration-300 flex items-center gap-2 shadow-lg hover:shadow-[0_0_15px_rgba(59,130,246,0.4)] transform active:scale-95 border border-white/10" onClick={() => setShowAddModal(true)}>
                    <Plus size={18} strokeWidth={2.5} />
                    Add Provider
                </button>
                <button className="bg-[#0B0E14]/80 hover:bg-black/40 text-gray-300 hover:text-white px-5 py-2.5 rounded-xl font-bold transition-all duration-300 flex items-center gap-2 border border-white/10 shadow-inner disabled:opacity-50 disabled:cursor-not-allowed" onClick={() => setShowAddModelModal(true)} disabled={providers.length === 0}>
                    <Download size={18} />
                    Add Model
                </button>
                <button className="bg-[#0B0E14]/80 hover:bg-black/40 text-gray-300 hover:text-white px-5 py-2.5 rounded-xl font-bold transition-all duration-300 flex items-center gap-2 border border-white/10 shadow-inner" onClick={refreshAll} disabled={isRefreshing}>
                    <RefreshCw size={18} className={isRefreshing ? 'animate-spin' : ''} />
                    Refresh
                </button>
                <button className="bg-red-500/10 hover:bg-red-500/20 text-red-400 hover:text-red-300 px-5 py-2.5 rounded-xl font-bold transition-all duration-300 flex items-center gap-2 border border-red-500/20 shadow-inner" onClick={handleCleanupState}>
                    <Wrench size={18} />
                    Cleanup
                </button>
            </div>


            {/* ── Fleet overview strip ── */}
            <div className="mb-6 flex flex-wrap gap-2">
                {[
                    { key: 'all', label: 'All', count: providers.length, tone: 'text-gray-300' },
                    { key: 'ready', label: 'Ready', count: stateCounts.ready, tone: 'text-emerald-300' },
                    { key: 'warm', label: 'Warm', count: stateCounts.warm, tone: 'text-amber-300' },
                    { key: 'cooling', label: 'Cooling', count: stateCounts.cooling, tone: 'text-orange-300' },
                    { key: 'cold', label: 'Cold', count: stateCounts.cold, tone: 'text-gray-400' },
                    { key: 'offline', label: 'Offline', count: stateCounts.offline, tone: 'text-red-300' },
                    { key: 'disabled', label: 'Disabled', count: stateCounts.disabled, tone: 'text-gray-500' },
                ].map((chip) => (
                    <button
                        key={chip.key}
                        type="button"
                        onClick={() => setStateFilter(chip.key === 'all' ? 'all' : chip.key)}
                        className={`flex items-center gap-2 rounded-xl border px-3 py-1.5 text-xs font-bold transition-all ${
                            stateFilter === chip.key
                                ? 'border-blue-500/40 bg-blue-500/10 text-white'
                                : 'border-white/5 bg-[#0B0E14]/60 text-gray-400 hover:text-white'
                        }`}
                    >
                        <span className={chip.tone}>{chip.count}</span>
                        <span>{chip.label}</span>
                    </button>
                ))}
                <span className="flex items-center gap-2 rounded-xl border border-white/5 bg-[#0B0E14]/60 px-3 py-1.5 text-xs font-bold text-gray-400">
                    <span className="text-blue-300">{inFlightJobs}</span>
                    <span>In-flight</span>
                </span>
            </div>
            {/* ── Load Balancer Bar ── */}
            <LoadBalancerBar
                config={lbConfig}
                stats={lbStats}
                onUpdateStrategy={handleUpdateLBStrategy}
                providers={providers}
            />

            {/* ── Search + Filters ── */}
            <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <label className="relative block max-w-md flex-1">
                    <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500" />
                    <input
                        type="text"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        aria-label="Search providers" placeholder="Search providers..."
                        className="w-full bg-[#0B0E14]/80 border border-white/10 rounded-xl pl-12 pr-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-blue-500/50 shadow-inner glow-focus placeholder-gray-600 font-medium"
                    />
                </label>

                <div className="flex flex-wrap gap-2 p-1.5 bg-black/40 border border-white/10 rounded-2xl w-fit shadow-inner">
                    {FILTERS.map((option) => (
                        <button
                            key={option.id}
                            onClick={() => setFilter(option.id)}
                            className={`relative px-4 py-2 text-xs font-bold rounded-xl transition-all duration-300 tracking-wide ${
                                filter === option.id
                                    ? 'text-white shadow-[0_0_10px_rgba(59,130,246,0.3)] bg-gradient-to-r from-blue-600/80 to-violet-600/80 border border-white/20'
                                    : 'text-gray-400 hover:text-white hover:bg-white/5 border border-transparent'
                            }`}
                        >
                            {option.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* ── Provider List ── */}
            {isLoading ? (
                <div className="glass-panel flex h-64 items-center justify-center rounded-3xl border border-white/5 shadow-2xl relative overflow-hidden">
                     <div className="absolute inset-0 bg-gradient-to-br from-blue-500/5 to-purple-500/5 animate-pulse" />
                    <div className="flex flex-col items-center gap-4 relative z-10">
                        <RefreshCw size={32} className="animate-spin text-blue-400 drop-shadow-[0_0_10px_rgba(59,130,246,0.5)]" />
                        <div className="text-sm font-bold text-gray-400 tracking-wider uppercase">Loading providers...</div>
                    </div>
                </div>
            ) : isError ? (
                <QueryErrorState
                    error={error}
                    noun="providers"
                    onRetry={() => refreshProviderData()}
                />
            ) : filteredProviders.length > 0 ? (
                <div className="space-y-8">
                    {[
                        { key: 'modal', label: 'Modal Workers', badge: 'Serverless' },
                        { key: 'beam', label: 'Beam Workers', badge: 'Serverless' },
                        { key: 'remote', label: 'Remote Workers', badge: 'Self-hosted' },
                        { key: 'direct', label: 'Direct / Hosted API', badge: 'API' },
                    ].map((section) => {
                        const sectionProviders = filteredProviders.filter((p) => transportFromProvider(p) === section.key);
                        if (sectionProviders.length === 0) return null;
                        return (
                            <div key={section.key}>
                                <h2 className="text-xl font-bold text-gray-200 mb-4 px-2 tracking-wide flex items-center gap-2">
                                    <span>{section.label}</span>
                                    <span className="text-xs font-normal text-indigo-400 bg-indigo-500/10 border border-indigo-500/20 px-2 py-0.5 rounded-full uppercase tracking-wider">{section.badge}</span>
                                </h2>
                                <div className="space-y-4">
                                    {sectionProviders.map((provider) => (
                                        <ProviderListItem
                                            key={provider.id}
                                            provider={provider}
                                            actionLabel={actionLoading[provider.id] ?? null}
                                            isSelected={selectedProviderId === provider.id}
                                            onSelect={(id) => {
                                                setSelectedProviderId(selectedProviderId === id ? null : id);
                                                setDrawerTab('runtime');
                                            }}
                                            onToggleEnabled={handleToggleEnabled}
                                            onEdit={() => setEditingProvider(provider)}
                                            onDelete={() => handleDelete(provider.id)}
                                            onDeploy={handleDeployProvider}
                                            providerFailures={providerStatsMap.get(provider.id)?.failures ?? 0}
                                            jobsAssigned={providerStatsMap.get(provider.id)?.jobs_assigned ?? 0}
                                        />
                                    ))}
                                </div>
                            </div>
                        );
                    })}
                </div>
            ) : (
                <div className="glass-panel flex h-64 flex-col items-center justify-center rounded-3xl border border-white/5 shadow-2xl text-center relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-64 h-64 bg-blue-500/5 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2 pointer-events-none" />
                    <div className="absolute bottom-0 left-0 w-64 h-64 bg-purple-500/5 rounded-full blur-3xl translate-y-1/2 -translate-x-1/2 pointer-events-none" />
                    <div className="relative z-10 flex flex-col items-center">
                        <Wrench size={48} className="mb-4 text-gray-600/50 drop-shadow-md" />
                        <p className="mb-2 text-xl font-bold text-white tracking-wide">
                            {providers.length === 0 ? 'No providers configured' : 'No matches'}
                        </p>
                        <p className="mb-6 max-w-sm text-sm text-gray-400 font-medium">
                            {providers.length === 0
                                ? 'Create a provider to start dispatching inference jobs.'
                                : 'Adjust your search or filter.'}
                        </p>
                        {providers.length === 0 && (
                            <button
                                onClick={() => setShowAddModal(true)}
                                className="bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white px-6 py-3 rounded-xl font-bold transition-all duration-300 flex items-center gap-2 shadow-lg hover:shadow-[0_0_15px_rgba(59,130,246,0.4)] transform active:scale-95 border border-white/10"
                            >
                                <Plus size={18} strokeWidth={2.5} />
                                Add Provider
                            </button>
                        )}
                    </div>
                </div>
            )}

            {/* ── Side Drawer ── */}
            <AnimatePresence>
                {selectedProvider && (
                    <ProviderDetailPanel
                        provider={selectedProvider}
                        initialTab={drawerTab}
                        onClose={() => {
                            setSelectedProviderId(null);
                            setDrawerTab('runtime');
                        }}
                        loading={actionLoading[selectedProvider.id]}
                        onReconcile={() => handleReconcile(selectedProvider.id)}
                        onQuickSync={() => handleQuickSync(selectedProvider.id)}
                        onResetStatus={async () => {
                            const accepted = await confirm({
                                title: 'Reset Provider Status',
                                message: 'This clears persisted provider sync rows and forces the next reconciliation to rebuild model state.',
                                confirmText: 'Reset Provider',
                                isDangerous: true,
                            });
                            if (accepted) executeResetStatus(selectedProvider.id);
                        }}
                        onSetup={() => handleSetup(selectedProvider.id)}
                        onDeploy={() => {
                            setDrawerTab('deploy');
                        }}
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

            {actionOutput && (
                <ActionOutputModal
                    output={actionOutput}
                    onClose={() => setActionOutput(null)}
                />
            )}
        </motion.div>
    );
}
