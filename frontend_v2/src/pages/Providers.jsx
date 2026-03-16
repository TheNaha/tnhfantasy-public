import { useCallback, useEffect, useMemo, useState } from 'react';
import { Plus, RefreshCw, Download } from 'lucide-react';
import { motion } from 'framer-motion';
import toast from 'react-hot-toast';
import ProviderCard from '../components/providers/ProviderCard';
import { ProviderModal } from '../components/ProviderManagement';
import AddModelToProviderModal from '../components/providers/AddModelToProviderModal';
import ReconciliationStatus from '../components/providers/ReconciliationStatus';
import ConfirmationModal from '../components/ConfirmationModal';
import useReconciliationStore from '../store/reconciliationStore';
import { useProviderStore } from '../store/providerStore';

export default function Providers() {
    const [showAddModal, setShowAddModal] = useState(false);
    const [showAddModelModal, setShowAddModelModal] = useState(false);
    const [reconcilingProviderId, setReconcilingProviderId] = useState(null); // Track which provider is reconciling
    const [editingProvider, setEditingProvider] = useState(null); // Track provider being edited
    const [isRefreshing, setIsRefreshing] = useState(false);
    
    const { startReconciliation } = useReconciliationStore();
    const connectProviders = useProviderStore(state => state.connect);
    const providers = useProviderStore(state => state.providers);
    const isLoading = useProviderStore(state => state.isLoading);
    const containerStatuses = useProviderStore(state => state.containerStatuses);
    const containerLoading = useProviderStore(state => state.containerLoading);
    const lbConfig = useProviderStore(state => state.lbConfig);
    const lbStats = useProviderStore(state => state.lbStats);
    const refreshProviders = useProviderStore(state => state.refreshAll);
    const startContainer = useProviderStore(state => state.startContainer);
    const stopContainer = useProviderStore(state => state.stopContainer);
    const restartContainer = useProviderStore(state => state.restartContainer);
    const deployProvider = useProviderStore(state => state.deployProvider);
    const reconcileProvider = useProviderStore(state => state.reconcileProvider);
    const setupProvider = useProviderStore(state => state.setupProvider);
    const resetProviderModelStatus = useProviderStore(state => state.resetProviderModelStatus);
    const toggleProviderEnabled = useProviderStore(state => state.toggleProviderEnabled);
    const deleteProvider = useProviderStore(state => state.deleteProvider);
    const updateLoadBalancerStrategy = useProviderStore(state => state.updateLoadBalancerStrategy);
    const saveProvider = useProviderStore(state => state.saveProvider);
    const [resetConfirm, setResetConfirm] = useState({ isOpen: false, providerId: null });

    const refreshAll = useCallback(async () => {
        setIsRefreshing(true);
        try {
            await refreshProviders();
        } finally {
            setIsRefreshing(false);
        }
    }, [refreshProviders]);

    useEffect(() => {
        connectProviders();
    }, [connectProviders]);

    // Enrich providers with container status and default enabled to true
    const enrichedProviders = useMemo(() => providers.map(provider => ({
        ...provider,
        container_status: containerStatuses[provider.id]?.status || 'stopped',
        enabled: provider.enabled !== undefined ? provider.enabled : true // Default to enabled if not set
    })), [providers, containerStatuses]);

    // ⚡ Bolt: Create an O(1) Hash Map for provider stats to avoid O(N²) lookups during render
    const providerStatsMap = useMemo(() => {
        const map = new Map();
        if (lbStats?.provider_stats) {
            lbStats.provider_stats.forEach(stat => map.set(stat.id, stat));
        }
        return map;
    }, [lbStats]);

    const pageVariants = {
        initial: { opacity: 0, y: 20 },
        animate: { opacity: 1, y: 0 },
        exit: { opacity: 0, y: -20 }
    };

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

    const handleDeploy = async (providerId) => {
        try {
            const result = await deployProvider(providerId);
            const providerType = result.provider_type || 'Provider';
            toast.success(`${providerType.charAt(0).toUpperCase() + providerType.slice(1)} app deployed successfully!`);
        } catch (error) {
            console.error('Failed to deploy app:', error);
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
            toast.success(`Setup complete! ${result.message}`);
        } catch (error) {
            console.error('Failed to setup provider:', error);
            toast.error(`Failed to setup provider: ${error.message}`);
        }
    };

    const handleResetStatus = async (providerId) => {
        // Show confirmation modal
        setResetConfirm({ isOpen: true, providerId });
    };

    const executeResetStatus = async () => {
        const providerId = resetConfirm.providerId;
        setResetConfirm({ isOpen: false, providerId: null });

        try {
            const result = await resetProviderModelStatus(providerId);
            toast.success(`Reset complete! ${result.deleted_count} entries cleared. Click Reconcile to re-download.`);
        } catch (error) {
            console.error('Failed to reset status:', error);
            toast.error(`Failed to reset: ${error.message}`);
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

    const handleEdit = (provider) => {
        setEditingProvider(provider);
    };

    const handleDelete = async (providerId) => {
        // Note: Browser confirm() is blocked, proceeding directly
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

    const handleUpdateLBStrategy = async (strategy) => {
        try {
            await updateLoadBalancerStrategy(strategy);
        } catch (error) {
            console.error('Failed to update load balancer:', error);
            toast.error(`Failed to update load balancer: ${error.message}`);
        }
    };


    return (
        <motion.div
            className="p-6 max-w-7xl mx-auto"
            initial="initial"
            animate="animate"
            exit="exit"
            variants={pageVariants}
            transition={{ duration: 0.3 }}
        >
            {/* Header */}
            <div className="flex items-center justify-between mb-8">
                <div>
                    <h1 className="text-3xl font-bold text-white mb-2">Providers</h1>
                    <p className="text-gray-400">Manage computational providers and model synchronization</p>
                </div>

                <div className="flex items-center gap-3">
                    <button
                        onClick={() => setShowAddModelModal(true)}
                        disabled={providers.length === 0}
                        className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        <Download size={16} />
                        Add Model
                    </button>

                    <button
                        onClick={refreshAll}
                        disabled={isRefreshing}
                        className="flex items-center gap-2 px-4 py-2 bg-gray-700/50 hover:bg-gray-700 text-gray-300 rounded-lg border border-gray-600 transition-colors disabled:opacity-50"
                    >
                        <RefreshCw size={16} className={isRefreshing ? 'animate-spin' : ''} />
                        Refresh
                    </button>

                    <button
                        onClick={() => setShowAddModal(true)}
                        className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
                    >
                        <Plus size={16} />
                        Add Provider
                    </button>
                </div>
            </div>

            {/* Load Balancer Config */}
            {lbConfig && (
                <div className="bg-gray-800/50 backdrop-blur-sm border border-gray-700 rounded-xl p-6 mb-8">
                    <div className="flex justify-between items-center mb-6 pb-4 border-b border-gray-700">
                        <div>
                            <h2 className="text-xl font-semibold text-white mb-1">Load Balancer</h2>
                            <p className="text-sm text-gray-400">Distribute requests across providers</p>
                        </div>
                        {lbStats && (
                            <div className="flex gap-2">
                                <span className="inline-flex items-center gap-2 px-3 py-1.5 bg-green-500/20 text-green-400 rounded-lg text-sm font-semibold border border-green-500/30">
                                    {lbStats.total_providers} active
                                </span>
                            </div>
                        )}
                    </div>

                    {/* Strategy Selector */}
                    <div className="space-y-3">
                        <label className="text-sm font-medium text-gray-400">Strategy:</label>
                        <div className="grid grid-cols-3 gap-2">
                            {[
                                { id: 'round-robin', label: 'Round Robin', desc: 'Cycle through all' },
                                { id: 'random', label: 'Random', desc: 'Random selection' },
                                { id: 'priority', label: 'Priority', desc: 'Best priority only' },
                                { id: 'least-connections', label: 'Least Connections', desc: 'Fewest active jobs' },
                                { id: 'priority-round-robin', label: 'Priority + RR', desc: 'Round-robin in best tier' },
                                { id: 'priority-least-connections', label: 'Priority + LC', desc: 'Least conn. in best tier' },
                            ].map((strategy) => (
                                <button
                                    key={strategy.id}
                                    onClick={() => handleUpdateLBStrategy(strategy.id)}
                                    className={`px-3 py-2 rounded-lg text-sm transition-all text-left ${lbConfig.strategy === strategy.id
                                        ? 'bg-blue-600 text-white'
                                        : 'bg-gray-700/50 text-gray-300 border border-gray-600 hover:bg-gray-700'
                                        }`}
                                >
                                    <div className="font-medium">{strategy.label}</div>
                                    <div className={`text-xs ${lbConfig.strategy === strategy.id ? 'text-blue-200' : 'text-gray-500'}`}>
                                        {strategy.desc}
                                    </div>
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Fallback Notice */}
                    {lbConfig.fallback_enabled && (
                        <div className="mt-4 px-4 py-2 bg-green-500/15 border-l-4 border-green-500 rounded-lg text-green-400 text-sm font-medium">
                            ✓ Automatic fallback enabled
                        </div>
                    )}
                </div>
            )}

            {/* Provider Grid */}
            {isLoading ? (
                <div className="flex items-center justify-center h-64">
                    <div className="text-gray-400">Loading providers...</div>
                </div>
            ) : enrichedProviders && enrichedProviders.length > 0 ? (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {enrichedProviders.map((provider) => (
                        <ProviderCard
                            key={provider.id}
                            provider={provider}
                            loading={containerLoading[provider.id]}
                            onStart={() => handleStart(provider.id)}
                            onStop={() => handleStop(provider.id)}
                            onRestart={() => handleRestart(provider.id)}
                            onDeploy={() => handleDeploy(provider.id)}
                            onReconcile={() => handleReconcile(provider.id)}
                            onResetStatus={() => handleResetStatus(provider.id)}
                            onSetup={() => handleSetup(provider.id)}
                            onConfigure={() => handleEdit(provider)}
                            onEdit={() => handleEdit(provider)}
                            onDelete={() => handleDelete(provider.id)}
                            onToggleEnabled={handleToggleEnabled}
                            providerFailures={providerStatsMap.get(provider.id)?.failures ?? 0}
                            jobsAssigned={providerStatsMap.get(provider.id)?.jobs_assigned ?? 0}
                        />
                    ))}
                </div>
            ) : (
                <div className="flex flex-col items-center justify-center h-64 bg-gray-800/30 rounded-xl border border-gray-700">
                    <p className="text-gray-400 mb-4">No providers configured</p>
                    <button
                        onClick={() => setShowAddModal(true)}
                        className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
                    >
                        <Plus size={16} />
                        Add Your First Provider
                    </button>
                </div>
            )}

            {/* Add/Edit Provider Modal */}
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
                    saveProvider={saveProvider}
                />
            )}

            {/* Add Model to Provider Modal */}
            {showAddModelModal && (
                <AddModelToProviderModal
                    providers={enrichedProviders}
                    onClose={() => setShowAddModelModal(false)}
                />
            )}

            {/* Reconciliation Status Modal */}
            {reconcilingProviderId && (
                <ReconciliationStatus
                    providerId={reconcilingProviderId}
                    onClose={async () => {
                        setReconcilingProviderId(null);
                        await refreshAll();
                    }}
                />
            )}

            {/* Reset Status Confirmation Modal */}
            <ConfirmationModal
                isOpen={resetConfirm.isOpen}
                onClose={() => setResetConfirm({ isOpen: false, providerId: null })}
                onConfirm={executeResetStatus}
                title="Reset Provider Status"
                message={`This will mark ALL files as pending and force a complete re-download on next reconcile. Orphaned files in Modal will be deleted.`}
                isDangerous={true}
                confirmText="Reset All"
            />
        </motion.div>
    );
}
