import { useCallback, useMemo, useState } from 'react';
import { Download, Plus, RefreshCw, ScanSearch, Search, Wrench } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import toast from 'react-hot-toast';
import ProviderListItem from '../components/providers/ProviderListItem';
import ProviderDetailPanel from '../components/providers/ProviderDetailPanel';
import LoadBalancerBar from '../components/providers/LoadBalancerBar';
import ProviderModal from '../components/providers/ProviderModal';
import AddModelToProviderModal from '../components/providers/AddModelToProviderModal';
import { useConfirmation } from '../store/confirmationStore';
import { providersApi } from '../api';
import { summarizeProviderStatus } from '../utils/providerStatus';
import useProvidersPageData, { useProviderMutations } from '../hooks/useProvidersPageData';

const FILTERS = [
    { id: 'all', label: 'All' },
    { id: 'image', label: 'Image' },
    { id: 'llm', label: 'LLM' },
    { id: 'tts', label: 'Voice' },
    { id: 'issues', label: 'Needs Attention' },
];

export default function Providers() {
    const [showAddModal, setShowAddModal] = useState(false);
    const [showAddModelModal, setShowAddModelModal] = useState(false);
    const [editingProvider, setEditingProvider] = useState(null);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [search, setSearch] = useState('');
    const [filter, setFilter] = useState('all');
    const [selectedProviderId, setSelectedProviderId] = useState(null);
    const [isDetecting, setIsDetecting] = useState(false);
    const { confirm } = useConfirmation();

    const {
        providers,
        lbConfig,
        lbStats,
        isLoading,
        refreshAll: refreshProviderData,
    } = useProvidersPageData();
    const {
        actionLoading,
        deployProvider,
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

    const handleDetect = useCallback(async () => {
        setIsDetecting(true);
        try {
            const result = await providersApi.detect();
            const created = result?.created ?? [];
            const already = result?.already ?? [];
            if (created.length) {
                toast.success(`Detected ${created.length} new provider${created.length > 1 ? 's' : ''}: ${created.join(', ')}`);
            } else if (already.length) {
                toast(`${already.length} provider${already.length > 1 ? 's' : ''} already registered (heartbeat auto-discovery).`, { icon: '📡' });
            } else {
                toast('No new providers detected. Add one manually using "+ Add Provider".');
            }
            await refreshProviderData();
        } catch (e) {
            toast.error(`Detection failed: ${e.message}`);
        } finally {
            setIsDetecting(false);
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
                || (filter === 'image' && (provider.worker_type === 'image' || (!provider.worker_type && !provider.capabilities?.length) || (Array.isArray(provider.capabilities) && provider.capabilities.includes('image'))))
                || (filter === 'llm' && (provider.worker_type === 'llm' || (Array.isArray(provider.capabilities) && provider.capabilities.includes('llm'))))
                || (filter === 'tts' && (provider.worker_type === 'tts' || (Array.isArray(provider.capabilities) && provider.capabilities.includes('tts'))))
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

    const handleDeploy = async (providerId) => {
        try {
            const result = await deployProvider(providerId);
            const type = result.provider_type || 'provider';
            toast.success(`${type.charAt(0).toUpperCase() + type.slice(1)} deploy started`);
        } catch (error) { toast.error(`Deploy failed: ${error.message}`); }
    };
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
        } catch (error) { toast.error(`Setup failed: ${error.message}`); }
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
            ) : filteredProviders.length > 0 ? (
                <div className="space-y-8">
                    {filteredProviders.some(p => p.worker_type !== 'llm') && (
                        <div>
                            <h2 className="text-xl font-bold text-gray-200 mb-4 px-2 tracking-wide">Image Workers</h2>
                            <div className="space-y-4">
                                {filteredProviders.filter(p => p.worker_type !== 'llm').map((provider) => (
                                    <ProviderListItem
                                        key={provider.id}
                                        provider={provider}
                                        actionLabel={actionLoading[provider.id] ?? null}
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
                        </div>
                    )}
                    {filteredProviders.some(p => p.worker_type === 'llm') && (
                        <div>
                            <h2 className="text-xl font-bold text-gray-200 mb-4 px-2 tracking-wide">LLM Workers</h2>
                            <div className="space-y-4">
                                {filteredProviders.filter(p => p.worker_type === 'llm').map((provider) => (
                                    <ProviderListItem
                                        key={provider.id}
                                        provider={provider}
                                        actionLabel={actionLoading[provider.id] ?? null}
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
                        </div>
                    )}
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
                            <div className="flex items-center gap-3">
                                <button
                                    onClick={handleDetect}
                                    disabled={isDetecting}
                                    className="bg-white/5 hover:bg-white/10 border border-white/15 text-gray-200 px-6 py-3 rounded-xl font-bold transition-all duration-300 flex items-center gap-2 transform active:scale-95 disabled:opacity-50"
                                >
                                    <ScanSearch size={18} strokeWidth={2.5} className={isDetecting ? 'animate-spin' : ''} />
                                    {isDetecting ? 'Scanning...' : 'Detect Containers'}
                                </button>
                                <button
                                    onClick={() => setShowAddModal(true)}
                                    className="bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white px-6 py-3 rounded-xl font-bold transition-all duration-300 flex items-center gap-2 shadow-lg hover:shadow-[0_0_15px_rgba(59,130,246,0.4)] transform active:scale-95 border border-white/10"
                                >
                                    <Plus size={18} strokeWidth={2.5} />
                                    Add Provider
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* ── Side Drawer ── */}
            <AnimatePresence>
                {selectedProvider && (
                    <ProviderDetailPanel
                        provider={selectedProvider}
                        onClose={() => setSelectedProviderId(null)}
                        loading={actionLoading[selectedProvider.id]}
                        onDeploy={() => handleDeploy(selectedProvider.id)}
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
        </motion.div>
    );
}
