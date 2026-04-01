/**
 * Provider Management Component
 * UI for configuring serverless providers (Modal, Beam, RunPod)
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Plus, Settings, Trash2, Power, PowerOff, Edit2,
    Server, Activity, TrendingUp, BarChart3, Play, Square, RotateCw, FileText, Upload
} from 'lucide-react';
import toast from 'react-hot-toast';
import { providersApi } from '../api';
import { useConfirmation } from '../store/confirmationStore';
import useProviderStore from '../store/providerStore';

export default function ProviderManagement() {
    const [showAddModal, setShowAddModal] = useState(false);
    const [editingProvider, setEditingProvider] = useState(null);
    const [showLogs, setShowLogs] = useState(null);
    const { confirm } = useConfirmation();
    const providers = useProviderStore((state) => state.providers);
    const lbConfig = useProviderStore((state) => state.lbConfig);
    const lbStats = useProviderStore((state) => state.lbStats);
    const loading = useProviderStore((state) => state.isLoading);
    const containerStatuses = useProviderStore((state) => state.containerStatuses);
    const containerLoading = useProviderStore((state) => state.containerLoading);
    const connectProviders = useProviderStore((state) => state.connect);
    const startProviderContainer = useProviderStore((state) => state.startContainer);
    const stopProviderContainer = useProviderStore((state) => state.stopContainer);
    const restartProviderContainer = useProviderStore((state) => state.restartContainer);
    const deployProvider = useProviderStore((state) => state.deployProvider);
    const toggleProviderEnabled = useProviderStore((state) => state.toggleProviderEnabled);
    const removeProvider = useProviderStore((state) => state.deleteProvider);
    const updateLoadBalancerStrategy = useProviderStore((state) => state.updateLoadBalancerStrategy);
    const saveProvider = useProviderStore((state) => state.saveProvider);

    useEffect(() => {
        connectProviders();
    }, [connectProviders]);

    // ⚡ Bolt: Create an O(1) Hash Map for provider stats to avoid O(N²) lookups during render
    const providerStatsMap = useMemo(() => {
        const map = new Map();
        if (lbStats?.provider_stats) {
            lbStats.provider_stats.forEach(stat => map.set(stat.id, stat));
        }
        return map;
    }, [lbStats]);

    const deployModalApp = async (providerId) => {
        try {
            await deployProvider(providerId);
            toast.success('Modal app deployed successfully!');
        } catch (error) {
            console.error('Failed to deploy Modal app:', error);
            toast.error(`Failed to deploy Modal app: ${error.message}`);
        }
    };

    const startContainer = async (providerId) => {
        try {
            await startProviderContainer(providerId);
        } catch (error) {
            console.error('Failed to start container:', error);
            toast.error(`Failed to start container: ${error.message}`);
        }
    };

    const stopContainer = async (providerId) => {
        try {
            await stopProviderContainer(providerId);
        } catch (error) {
            console.error('Failed to stop container:', error);
            toast.error(`Failed to stop container: ${error.message}`);
        }
    };

    const restartContainer = async (providerId) => {
        try {
            await restartProviderContainer(providerId);
        } catch (error) {
            console.error('Failed to restart container:', error);
            toast.error(`Failed to restart container: ${error.message}`);
        }
    };

    const toggleProvider = async (providerId, currentlyEnabled) => {
        try {
            await toggleProviderEnabled(providerId, currentlyEnabled);
        } catch (error) {
            console.error('Failed to toggle provider:', error);
            toast.error(`Failed to toggle provider: ${error.message}`);
        }
    };

    const deleteProvider = async (providerId) => {
        const confirmed = await confirm({
            title: 'Delete Provider',
            message: `Delete provider ${providerId}? This action cannot be undone.`,
            confirmText: 'Delete',
            isDangerous: true
        });
        if (!confirmed) return;

        try {
            await removeProvider(providerId);
            toast.success('Provider deleted');
        } catch (error) {
            console.error('Failed to delete provider:', error);
            toast.error(`Failed to delete provider: ${error.message}`);
        }
    };

    const updateLBStrategy = async (strategy) => {
        try {
            await updateLoadBalancerStrategy(strategy);
        } catch (error) {
            console.error('Failed to update load balancer:', error);
            toast.error(`Failed to update load balancer: ${error.message}`);
        }
    };

    if (loading) {
        return <div className="text-center py-12 text-white/60 text-lg">Loading providers...</div>;
    }

    return (
        <div className="p-8 max-w-7xl mx-auto">
            {/* Header */}
            <div className="flex justify-between items-center mb-8 gap-6">
                <div>
                    <h2 className="flex items-center gap-3 text-2xl font-semibold bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent mb-2">
                        <Server className="text-blue-400" size={28} />
                        Provider Management
                    </h2>
                    <p className="text-gray-400 text-sm">
                        Configure serverless compute providers
                    </p>
                </div>
                <button
                    onClick={() => setShowAddModal(true)}
                    className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-blue-500 to-purple-500 hover:from-blue-600 hover:to-purple-600 text-white rounded-xl font-medium transition-all duration-200 hover:-translate-y-0.5 shadow-lg shadow-blue-500/30"
                >
                    <Plus size={20} />
                    Add Provider
                </button>
            </div>

            {/* Load Balancer Config Card */}
            {lbConfig && (
                <div className="glass p-7 rounded-2xl mb-8 border border-white/10 shadow-2xl">
                    <div className="flex justify-between items-center mb-6 pb-5 border-b border-white/10">
                        <h3 className="flex items-center gap-2 text-xl font-semibold text-white/95">
                            <Activity size={24} className="text-blue-400" />
                            Load Balancer
                        </h3>
                        {lbStats && (
                            <div className="flex gap-3">
                                <span className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-green-500 to-emerald-600 rounded-lg text-sm font-semibold text-white shadow-md">
                                    <TrendingUp size={16} />
                                    {lbStats.total_providers} active
                                </span>
                            </div>
                        )}
                    </div>

                    {/* Strategy Selector */}
                    <div className="mb-5">
                        <label className="font-medium text-white/70 text-sm block mb-3">
                            Strategy:
                        </label>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                            {['round-robin', 'random', 'priority', 'least-connections'].map((strategy) => (
                                <button
                                    key={strategy}
                                    onClick={() => updateLBStrategy(strategy)}
                                    className={`px-4 py-3 rounded-lg font-medium text-sm capitalize transition-all duration-200 ${lbConfig.strategy === strategy
                                        ? 'bg-gradient-to-r from-blue-500 to-purple-500 text-white shadow-lg shadow-blue-500/30'
                                        : 'bg-gray-800/80 text-white/70 border border-white/10 hover:bg-gray-700/90 hover:border-blue-500/50 hover:-translate-y-0.5'
                                        }`}
                                >
                                    {strategy.replace('-', ' ')}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Fallback Notice */}
                    {lbConfig.fallback_enabled && (
                        <div className="px-5 py-3 bg-green-500/15 border-l-4 border-green-500 rounded-lg text-green-400 text-sm font-medium">
                            ✓ Automatic fallback enabled
                        </div>
                    )}
                </div>
            )}
            {/* Providers List */}
            <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6 mb-8">
                <AnimatePresence>
                    {providers.map((provider) => (
                        <motion.div
                            key={provider.id}
                            layout
                            initial={{ opacity: 0, y: 20 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, scale: 0.95 }}
                            className={`glass p-7 rounded-2xl transition-all duration-300 hover:-translate-y-1 hover:shadow-2xl border ${provider.enabled
                                ? 'border-green-500/30 shadow-xl'
                                : 'border-white/10 opacity-60'
                                }`}
                        >
                            <div className="flex justify-between items-start mb-5 pb-5 border-b border-white/10">
                                <div className="flex-1">
                                    <span className="inline-block px-3 py-1 bg-gradient-to-r from-blue-500 to-purple-500 rounded-lg text-xs font-bold uppercase tracking-wide text-white shadow-md mb-2">
                                        {provider.type}
                                    </span>
                                    <h3 className="text-xl font-semibold text-white/95 mt-2">
                                        {provider.id}
                                    </h3>
                                    <span className={`inline-flex items-center px-3 py-1 rounded-lg text-xs font-semibold mt-2 ${provider.status === 'active'
                                        ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                                        : 'bg-white/10 text-white/50 border border-white/10'
                                        }`}>
                                        {provider.status}
                                    </span>
                                </div>
                                <div className="flex gap-2 ml-4">
                                    <button
                                        onClick={() => toggleProvider(provider.id, provider.enabled)}
                                        className="p-2 bg-gray-800/80 hover:bg-gray-700/90 border border-white/10 hover:border-blue-500/50 rounded-lg text-white/70 hover:text-white transition-all duration-200 hover:-translate-y-0.5"
                                        title={provider.enabled ? 'Disable' : 'Enable'}
                                        aria-label={provider.enabled ? 'Disable provider' : 'Enable provider'}
                                        aria-pressed={provider.enabled}
                                    >
                                        {provider.enabled ? <Power size={18} /> : <PowerOff size={18} />}
                                    </button>
                                    <button
                                        onClick={() => setEditingProvider(provider)}
                                        className="p-2 bg-gray-800/80 hover:bg-gray-700/90 border border-white/10 hover:border-blue-500/50 rounded-lg text-white/70 hover:text-white transition-all duration-200 hover:-translate-y-0.5"
                                        title="Edit"
                                        aria-label="Edit provider"
                                    >
                                        <Edit2 size={18} />
                                    </button>
                                    <button
                                        onClick={() => deleteProvider(provider.id)}
                                        className="p-2 bg-gray-800/80 hover:bg-red-500/20 border border-white/10 hover:border-red-500/50 rounded-lg text-white/70 hover:text-red-400 transition-all duration-200 hover:-translate-y-0.5"
                                        title="Delete"
                                        aria-label="Delete provider"
                                    >
                                        <Trash2 size={18} />
                                    </button>
                                </div>
                            </div>

                            <div className="space-y-3">
                                <div className="flex justify-between items-center text-sm">
                                    <span className="text-white/60 font-medium">Priority:</span>
                                    <span className="font-mono text-sm bg-blue-500/10 px-3 py-1 rounded-md border border-blue-500/20 text-white/95 font-semibold">
                                        {provider.priority || 'N/A'}
                                    </span>
                                </div>
                                {provider.credentials?.username && (
                                    <div className="flex justify-between items-center text-sm">
                                        <span className="text-white/60 font-medium">Username:</span>
                                        <span className="font-mono text-sm bg-blue-500/10 px-3 py-1 rounded-md border border-blue-500/20 text-white/95 font-semibold">
                                            {provider.credentials.username}
                                        </span>
                                    </div>
                                )}
                                {provider.config?.app_name && (
                                    <div className="flex justify-between items-center text-sm">
                                        <span className="text-white/60 font-medium">App Name:</span>
                                        <span className="font-mono text-sm bg-blue-500/10 px-3 py-1 rounded-md border border-blue-500/20 text-white/95 font-semibold">
                                            {provider.config.app_name}
                                        </span>
                                    </div>
                                )}

                                {/* Beam-specific display */}
                                {provider.type === 'beam' && provider.config?.gpu_type && (
                                    <div className="flex justify-between items-center text-sm">
                                        <span className="text-white/60 font-medium">GPU:</span>
                                        <span className="font-mono text-sm bg-purple-500/10 px-3 py-1 rounded-md border border-purple-500/20 text-purple-400 font-semibold">
                                            {provider.config.gpu_type}
                                        </span>
                                    </div>
                                )}
                                {provider.type === 'beam' && provider.config?.gpu_url && (
                                    <div className="text-xs text-white/40 truncate mt-1" title={provider.config.gpu_url}>
                                        GPU: {provider.config.gpu_url.replace('https://', '').substring(0, 30)}...
                                    </div>
                                )}

                                {/* Container Status & Controls */}
                                {provider.container_config && (
                                    <div className="border-t border-white/10 pt-3 mt-3">
                                        <div className="flex items-center justify-between mb-2">
                                            <span className="text-white/60 font-medium text-sm">Container:</span>
                                            {containerStatuses[provider.id] ? (
                                                <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold ${containerStatuses[provider.id].running && containerStatuses[provider.id].healthy
                                                    ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                                                    : containerStatuses[provider.id].running
                                                        ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
                                                        : 'bg-gray-500/20 text-gray-400 border border-gray-500/30'
                                                    }`}>
                                                    <span className="w-2 h-2 rounded-full animate-pulse" style={{
                                                        backgroundColor: containerStatuses[provider.id].running && containerStatuses[provider.id].healthy ? '#22c55e' : containerStatuses[provider.id].running ? '#eab308' : '#6b7280'
                                                    }} />
                                                    {containerStatuses[provider.id].status}
                                                </span>
                                            ) : (
                                                <span className="text-white/40 text-xs">checking...</span>
                                            )}
                                        </div>

                                        <div className="flex gap-1 mt-2">
                                            {containerStatuses[provider.id]?.running ? (
                                                <>
                                                    <button
                                                        onClick={() => stopContainer(provider.id)}
                                                        disabled={containerLoading[provider.id]}
                                                        className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 rounded text-red-400 text-xs font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                                                        title="Stop Container"
                                                    >
                                                        <Square size={12} />
                                                        {containerLoading[provider.id] === 'stopping' ? 'Stopping...' : 'Stop'}
                                                    </button>
                                                    <button
                                                        onClick={() => restartContainer(provider.id)}
                                                        disabled={containerLoading[provider.id]}
                                                        className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/30 rounded text-blue-400 text-xs font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                                                        title="Restart Container"
                                                    >
                                                        <RotateCw size={12} />
                                                        {containerLoading[provider.id] === 'restarting' ? 'Restarting...' : 'Restart'}
                                                    </button>
                                                </>
                                            ) : (
                                                <button
                                                    onClick={() => startContainer(provider.id)}
                                                    disabled={containerLoading[provider.id]}
                                                    className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 bg-green-500/20 hover:bg-green-500/30 border border-green-500/30 rounded text-green-400 text-xs font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                                                    title="Start Container"
                                                >
                                                    <Play size={12} />
                                                    {containerLoading[provider.id] === 'starting' ? 'Starting...' : 'Start'}
                                                </button>
                                            )}
                                            <button
                                                onClick={() => setShowLogs(provider.id)}
                                                className="px-2 py-1.5 bg-gray-700/50 hover:bg-gray-700/70 border border-white/10 rounded text-white/70 text-xs font-medium transition-all"
                                                title="View Logs"
                                                aria-label="View container logs"
                                            >
                                                <FileText size={12} />
                                            </button>
                                            {provider.type === 'modal' && (
                                                <button
                                                    onClick={() => deployModalApp(provider.id)}
                                                    disabled={containerLoading[provider.id]}
                                                    className="px-2 py-1.5 bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/30 rounded text-purple-400 text-xs font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                                                    title="Deploy Modal App"
                                                >
                                                    <Upload size={12} />
                                                    {containerLoading[provider.id] === 'deploying' ? 'Deploying...' : 'Deploy'}
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                )}
                            </div>

                            {providerStatsMap.get(provider.id)?.failures > 0 && (
                                <div className="mt-4 px-5 py-3 bg-orange-500/15 border-l-4 border-orange-500 rounded-lg text-orange-400 text-sm font-medium">
                                    ⚠️ {providerStatsMap.get(provider.id).failures} consecutive failures
                                </div>
                            )}
                        </motion.div>
                    ))}
                </AnimatePresence>
            </div>

            {/* Empty State */}
            {providers.length === 0 && (
                <div className="flex flex-col items-center justify-center py-16 px-8 text-center text-white/50 bg-gray-900/40 border-2 border-dashed border-white/10 rounded-2xl">
                    <Server size={48} className="mb-4 text-white/30" />
                    <p className="mb-6 text-lg font-medium">
                        No providers configured
                    </p>
                    <button
                        className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-blue-500 to-purple-500 hover:from-blue-600 hover:to-purple-600 text-white rounded-xl font-medium transition-all duration-200 hover:-translate-y-0.5 shadow-lg shadow-blue-500/30"
                        onClick={() => setShowAddModal(true)}
                    >
                        <Plus size={18} /> Add Your First Provider
                    </button>
                </div>
            )}

            {/* Add/Edit Provider Modal */}
            <AnimatePresence>
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
                        }}
                        saveProvider={saveProvider}
                    />
                )}
            </AnimatePresence>

            {/* Logs Modal */}
            <AnimatePresence>
                {showLogs && (
                    <LogsModal
                        providerId={showLogs}
                        onClose={() => setShowLogs(null)}
                    />
                )}
            </AnimatePresence>
        </div>
    );
}
export function ProviderModal({ provider, onClose, onSave, saveProvider }) {
    const [formData, setFormData] = useState(
        provider || {
            id: '',
            type: 'modal',
            enabled: true,
            priority: 1,
            credentials: { username: '' },
            config: { app_name: 'comfy-modal-stack' },
            container_config: null
        }
    );

    const [enableContainer, setEnableContainer] = useState(!!provider?.container_config);

    const handleSubmit = async (e) => {
        e.preventDefault();

        try {
            // Remove container_config if not enabled
            const submitData = {
                ...formData,
                container_config: enableContainer ? formData.container_config : null
            };

            await saveProvider(provider, submitData);
            toast.success(provider ? 'Provider updated' : 'Provider created');
            await onSave();
        } catch (error) {
            console.error('Failed to save provider:', error);
            toast.error(error.message || 'Failed to save provider');
        }
    };

    return (
        <motion.div
            className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
        >
            <motion.div
                className="glass p-8 rounded-2xl border border-white/10 shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.9, opacity: 0 }}
                onClick={(e) => e.stopPropagation()}
            >
                <h2 className="text-2xl font-semibold bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent mb-6">
                    {provider ? 'Edit Provider' : 'Add Provider'}
                </h2>

                <form onSubmit={handleSubmit} className="space-y-5">
                    {/* Provider ID */}
                    <div>
                        <label className="block mb-2 text-white/80 font-medium text-sm">Provider ID</label>
                        <input
                            type="text"
                            value={formData.id}
                            onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                            disabled={!!provider}
                            required
                            className="w-full px-4 py-3 bg-gray-800/80 border border-white/10 rounded-lg text-white/95 focus:outline-none focus:border-blue-500 focus:bg-gray-800/95 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                            placeholder="e.g., modal-primary"
                        />
                    </div>

                    {/* Type */}
                    <div>
                        <label className="block mb-2 text-white/80 font-medium text-sm">Type</label>
                        <select
                            value={formData.type}
                            onChange={(e) => {
                                const newType = e.target.value;
                                // Reset credentials/config when type changes
                                const newFormData = {
                                    ...formData,
                                    type: newType,
                                    credentials: newType === 'modal'
                                        ? { username: '' }
                                        : newType === 'beam'
                                            ? { api_key: '' }
                                            : {},
                                    config: newType === 'modal'
                                        ? { app_name: 'comfy-modal-stack' }
                                        : newType === 'beam'
                                            ? { gpu_url: '', storage_url: '', download_url: '', gpu_type: 'RTX4090' }
                                            : {}
                                };
                                setFormData(newFormData);
                            }}
                            className="w-full px-4 py-3 bg-gray-800/80 border border-white/10 rounded-lg text-white/95 focus:outline-none focus:border-blue-500 transition-all"
                        >
                            <option value="modal">Modal</option>
                            <option value="beam">Beam.cloud</option>
                            <option value="runpod" disabled>RunPod (Coming Soon)</option>
                        </select>
                    </div>

                    {/* Priority */}
                    <div>
                        <label className="block mb-2 text-white/80 font-medium text-sm">Priority</label>
                        <input
                            type="number"
                            value={formData.priority}
                            onChange={(e) => setFormData({ ...formData, priority: parseInt(e.target.value) })}
                            min="1"
                            className="w-full px-4 py-3 bg-gray-800/80 border border-white/10 rounded-lg text-white/95 focus:outline-none focus:border-blue-500 transition-all"
                        />
                        <small className="block mt-2 text-white/50 text-xs">Lower number = higher priority</small>
                    </div>

                    {/* Modal-specific fields */}
                    {formData.type === 'modal' && (
                        <>
                            <div>
                                <label className="block text-sm font-medium text-white/70 mb-2">
                                    Token ID
                                </label>
                                <input
                                    type="text"
                                    value={formData.credentials.token_id || ''}
                                    onChange={(e) => setFormData({
                                        ...formData,
                                        credentials: { ...formData.credentials, token_id: e.target.value }
                                    })}
                                    className="w-full px-4 py-2.5 bg-gray-800/50 border border-white/10 rounded-lg text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 transition-colors"
                                    placeholder="ak-..."
                                    required
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-white/70 mb-2">
                                    Token Secret
                                </label>
                                <input
                                    type="password"
                                    value={formData.credentials.token_secret || ''}
                                    onChange={(e) => setFormData({
                                        ...formData,
                                        credentials: { ...formData.credentials, token_secret: e.target.value }
                                    })}
                                    className="w-full px-4 py-2.5 bg-gray-800/50 border border-white/10 rounded-lg text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 transition-colors"
                                    placeholder="as-..."
                                    required
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-white/70 mb-2">
                                    Username
                                </label>
                                <input
                                    type="text"
                                    value={formData.credentials.username || ''}
                                    onChange={(e) => setFormData({
                                        ...formData,
                                        credentials: { ...formData.credentials, username: e.target.value }
                                    })}
                                    className="w-full px-4 py-2.5 bg-gray-800/50 border border-white/10 rounded-lg text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 transition-colors"
                                    placeholder="your-modal-username"
                                    required
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-white/70 mb-2">
                                    App Name
                                </label>
                                <input
                                    type="text"
                                    value={formData.config.app_name || ''}
                                    onChange={(e) => setFormData({
                                        ...formData,
                                        config: { ...formData.config, app_name: e.target.value }
                                    })}
                                    className="w-full px-4 py-2.5 bg-gray-800/50 border border-white/10 rounded-lg text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 transition-colors"
                                    placeholder="comfy-modal-stack"
                                />
                            </div>

                            {/* Memory Snapshot Toggle */}
                            <div className="p-4 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                                <label className="flex items-center justify-between cursor-pointer">
                                    <div>
                                        <span className="text-white/90 font-medium">Enable Memory Snapshot</span>
                                        <p className="text-xs text-yellow-400/80 mt-1">
                                            ⚠️ Experimental: Faster cold starts (~5s) but may cause GPU errors
                                        </p>
                                    </div>
                                    <input
                                        type="checkbox"
                                        checked={formData.config?.enable_memory_snapshot ?? false}
                                        onChange={(e) => setFormData({
                                            ...formData,
                                            config: { ...formData.config, enable_memory_snapshot: e.target.checked }
                                        })}
                                        className="w-5 h-5 accent-yellow-500 cursor-pointer"
                                    />
                                </label>
                                {formData.config?.enable_memory_snapshot && (
                                    <div className="mt-3 p-3 bg-yellow-500/15 border border-yellow-500/40 rounded text-yellow-300 text-xs">
                                        <strong>⚡ Snapshot Mode:</strong> Uses Modal memory snapshots for faster container restarts.
                                        If you experience "no GPU available" errors, disable this option.
                                    </div>
                                )}
                            </div>

                            {/* API Keys Section */}
                            <div className="col-span-2 border-t border-white/10 pt-4 mt-2">
                                <h3 className="text-sm font-semibold text-white/80 mb-3">API Keys (Optional)</h3>
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="block text-sm font-medium text-white/70 mb-2">
                                            HuggingFace Token
                                        </label>
                                        <input
                                            type="password"
                                            value={formData.credentials.hf_token || ''}
                                            onChange={(e) => setFormData({
                                                ...formData,
                                                credentials: { ...formData.credentials, hf_token: e.target.value }
                                            })}
                                            className="w-full px-4 py-2.5 bg-gray-800/50 border border-white/10 rounded-lg text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 transition-colors"
                                            placeholder="hf_..."
                                        />
                                        <p className="text-xs text-white/40 mt-1">For downloading gated models from HuggingFace</p>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-white/70 mb-2">
                                            CivitAI Token
                                        </label>
                                        <input
                                            type="password"
                                            value={formData.credentials.civitai_token || ''}
                                            onChange={(e) => setFormData({
                                                ...formData,
                                                credentials: { ...formData.credentials, civitai_token: e.target.value }
                                            })}
                                            className="w-full px-4 py-2.5 bg-gray-800/50 border border-white/10 rounded-lg text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 transition-colors"
                                            placeholder="Your CivitAI API key"
                                        />
                                        <p className="text-xs text-white/40 mt-1">For downloading models from CivitAI</p>
                                    </div>
                                </div>
                            </div>
                        </>

                    )}

                    {/* Beam-specific fields */}
                    {formData.type === 'beam' && (
                        <>
                            <div className="p-4 bg-blue-500/10 border border-blue-500/30 rounded-lg mb-4">
                                <h3 className="text-sm font-semibold text-blue-400 mb-2">☁️ Beam.cloud Provider</h3>
                                <p className="text-xs text-white/60">
                                    Beam uses two endpoints: GPU (for inference) and Storage (for file operations).
                                    Deploy both with: <code className="bg-gray-800 px-1 rounded">beam deploy beam_app.py:comfy_gpu</code> and <code className="bg-gray-800 px-1 rounded">beam deploy beam_app.py:comfy_storage</code>
                                </p>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-white/70 mb-2">
                                    API Key <span className="text-red-400">*</span>
                                </label>
                                <input
                                    type="password"
                                    value={formData.credentials.api_key || ''}
                                    onChange={(e) => setFormData({
                                        ...formData,
                                        credentials: { ...formData.credentials, api_key: e.target.value }
                                    })}
                                    className="w-full px-4 py-2.5 bg-gray-800/50 border border-white/10 rounded-lg text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 transition-colors"
                                    placeholder="Your Beam API key"
                                    required
                                />
                                <p className="text-xs text-white/40 mt-1">Get from beam.cloud dashboard</p>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-white/70 mb-2">
                                    GPU Endpoint URL <span className="text-red-400">*</span>
                                </label>
                                <input
                                    type="url"
                                    value={formData.config.gpu_url || ''}
                                    onChange={(e) => setFormData({
                                        ...formData,
                                        config: { ...formData.config, gpu_url: e.target.value }
                                    })}
                                    className="w-full px-4 py-2.5 bg-gray-800/50 border border-white/10 rounded-lg text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 transition-colors"

                                    required
                                />
                                <p className="text-xs text-white/40 mt-1">URL from: beam deploy beam_app.py:comfy_gpu</p>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-white/70 mb-2">
                                    Storage Endpoint URL <span className="text-red-400">*</span>
                                </label>
                                <input
                                    type="url"
                                    value={formData.config.storage_url || ''}
                                    onChange={(e) => setFormData({
                                        ...formData,
                                        config: { ...formData.config, storage_url: e.target.value }
                                    })}
                                    className="w-full px-4 py-2.5 bg-gray-800/50 border border-white/10 rounded-lg text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 transition-colors"
                                    placeholder="https://comfy-storage-xxx.app.beam.cloud"
                                    required
                                />
                                <p className="text-xs text-white/40 mt-1">URL from: beam deploy beam_app.py:comfy_storage</p>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-white/70 mb-2">
                                    Download Endpoint URL <span className="text-white/40">(Optional)</span>
                                </label>
                                <input
                                    type="url"
                                    value={formData.config.download_url || ''}
                                    onChange={(e) => setFormData({
                                        ...formData,
                                        config: { ...formData.config, download_url: e.target.value }
                                    })}
                                    className="w-full px-4 py-2.5 bg-gray-800/50 border border-white/10 rounded-lg text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 transition-colors"
                                    placeholder="https://comfy-download-xxx.app.beam.cloud"
                                />
                                <p className="text-xs text-white/40 mt-1">URL from: beam deploy beam_app.py:comfy_download (falls back to storage URL)</p>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-white/70 mb-2">
                                    GPU Type
                                </label>
                                <select
                                    value={formData.config.gpu_type || 'RTX4090'}
                                    onChange={(e) => setFormData({
                                        ...formData,
                                        config: { ...formData.config, gpu_type: e.target.value }
                                    })}
                                    className="w-full px-4 py-2.5 bg-gray-800/50 border border-white/10 rounded-lg text-white focus:outline-none focus:border-blue-500/50 transition-colors"
                                >
                                    <option value="RTX4090">RTX 4090</option>
                                    <option value="A10G">A10G</option>
                                    <option value="A100-40">A100 40GB</option>
                                    <option value="A100-80">A100 80GB</option>
                                    <option value="H100">H100</option>
                                </select>
                            </div>

                            {/* API Keys Section for Beam */}
                            <div className="border-t border-white/10 pt-4 mt-2">
                                <h3 className="text-sm font-semibold text-white/80 mb-3">API Keys (Optional)</h3>
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="block text-sm font-medium text-white/70 mb-2">
                                            HuggingFace Token
                                        </label>
                                        <input
                                            type="password"
                                            value={formData.credentials.hf_token || ''}
                                            onChange={(e) => setFormData({
                                                ...formData,
                                                credentials: { ...formData.credentials, hf_token: e.target.value }
                                            })}
                                            className="w-full px-4 py-2.5 bg-gray-800/50 border border-white/10 rounded-lg text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 transition-colors"
                                            placeholder="hf_..."
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-white/70 mb-2">
                                            CivitAI Token
                                        </label>
                                        <input
                                            type="password"
                                            value={formData.credentials.civitai_token || ''}
                                            onChange={(e) => setFormData({
                                                ...formData,
                                                credentials: { ...formData.credentials, civitai_token: e.target.value }
                                            })}
                                            className="w-full px-4 py-2.5 bg-gray-800/50 border border-white/10 rounded-lg text-white placeholder-white/30 focus:outline-none focus:border-blue-500/50 transition-colors"
                                            placeholder="Your CivitAI API key"
                                        />
                                    </div>
                                </div>
                            </div>
                        </>
                    )}

                    {/* Modal Credentials (for containerized mode - Modal only) */}
                    {enableContainer && formData.type === 'modal' && (
                        <>
                            <div>
                                <label className="block mb-2 text-white/80 font-medium text-sm">Modal Token ID</label>
                                <input
                                    type="password"
                                    value={formData.credentials?.token_id || ''}
                                    onChange={(e) => setFormData({
                                        ...formData,
                                        credentials: { ...formData.credentials, token_id: e.target.value }
                                    })}
                                    className="w-full px-4 py-3 bg-gray-800/80 border border-white/10 rounded-lg text-white/95 focus:outline-none focus:border-blue-500 transition-all font-mono text-sm"
                                    placeholder="ak-..."
                                />
                                <small className="block mt-2 text-white/50 text-xs">Get from: modal token show</small>
                            </div>

                            <div>
                                <label className="block mb-2 text-white/80 font-medium text-sm">Modal Token Secret</label>
                                <input
                                    type="password"
                                    value={formData.credentials?.token_secret || ''}
                                    onChange={(e) => setFormData({
                                        ...formData,
                                        credentials: { ...formData.credentials, token_secret: e.target.value }
                                    })}
                                    className="w-full px-4 py-3 bg-gray-800/80 border border-white/10 rounded-lg text-white/95 focus:outline-none focus:border-blue-500 transition-all font-mono text-sm"
                                    placeholder="as-..."
                                />
                            </div>
                        </>
                    )}

                    {/* Container Config Section */}
                    <div className="border-t border-white/10 pt-5 mt-5">
                        <label className="flex items-center gap-3 cursor-pointer mb-4">
                            <input
                                type="checkbox"
                                checked={enableContainer}
                                onChange={(e) => {
                                    setEnableContainer(e.target.checked);
                                    if (e.target.checked && !formData.container_config) {
                                        setFormData({
                                            ...formData,
                                            container_config: { port: 8001 }
                                        });
                                    }
                                }}
                                className="w-5 h-5 accent-blue-500 cursor-pointer"
                            />
                            <span className="text-white/90 font-medium">
                                Use Docker/Podman Container (Multi-Account Mode)
                            </span>
                        </label>

                        {enableContainer && (
                            <div className="space-y-4 pl-8 border-l-2 border-blue-500/30">
                                <div>
                                    <label className="block mb-2 text-white/80 font-medium text-sm">Container Port</label>
                                    <input
                                        type="number"
                                        value={formData.container_config?.port || 8001}
                                        onChange={(e) => setFormData({
                                            ...formData,
                                            container_config: {
                                                ...formData.container_config,
                                                port: parseInt(e.target.value)
                                            }
                                        })}
                                        min="8001"
                                        max="9000"
                                        className="w-full px-4 py-3 bg-gray-800/80 border border-white/10 rounded-lg text-white/95 focus:outline-none focus:border-blue-500 transition-all"
                                        placeholder="8001"
                                    />
                                    <small className="block mt-2 text-white/50 text-xs">Unique port for this container (e.g., 8001, 8002, 8003...)</small>
                                </div>

                                <div className="px-4 py-3 bg-blue-500/10 border border-blue-500/30 rounded-lg text-blue-300 text-sm">
                                    <strong>💡 Container Mode:</strong> Runs in isolated Docker/Podman container with separate credentials. Manage containers via Start/Stop buttons in the provider list.
                                </div>
                            </div>
                        )}
                    </div>
                    {/* Advanced Settings - Worker & Function Config */}
                    {enableContainer && (
                        <div className="border-t border-white/10 pt-5 mt-5">
                            <details className="group">
                                <summary className="flex items-center gap-2 cursor-pointer text-white/90 font-medium">
                                    <span className="group-open:rotate-90 transition-transform">▶</span>
                                    ⚙️ Advanced Settings
                                    <span className="text-xs text-white/50 ml-2">(Worker & Deployment Config)</span>
                                </summary>

                                <div className="mt-4 space-y-6 pl-4 border-l-2 border-purple-500/30">                                    {/* Worker Settings - Hot Reload */}
                                    <div>
                                        <h4 className="flex items-center gap-2 text-sm font-semibold text-white/80 mb-3">
                                            <span className="text-green-400">⚡</span> Worker Settings
                                            <span className="text-xs font-normal text-green-400/80">(Hot-reloadable)</span>
                                        </h4>
                                        <div className="grid grid-cols-3 gap-3">
                                            <div>
                                                <label className="block text-xs font-medium text-white/60 mb-1">
                                                    Max Concurrent Downloads
                                                </label>
                                                <input
                                                    type="number"
                                                    min="1"
                                                    max="20"
                                                    value={formData.config?.worker?.max_concurrent_downloads ?? 5}
                                                    onChange={(e) => setFormData({
                                                        ...formData,
                                                        config: {
                                                            ...formData.config,
                                                            worker: {
                                                                ...formData.config?.worker,
                                                                max_concurrent_downloads: parseInt(e.target.value)
                                                            }
                                                        }
                                                    })}
                                                    className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-green-500/50"
                                                />
                                            </div>
                                            <div>
                                                <label className="block text-xs font-medium text-white/60 mb-1">
                                                    Reconciliation Interval (hours)
                                                </label>
                                                <input
                                                    type="number"
                                                    min="1"
                                                    max="24"
                                                    value={formData.config?.worker?.reconciliation_interval_hours ?? 2}
                                                    onChange={(e) => setFormData({
                                                        ...formData,
                                                        config: {
                                                            ...formData.config,
                                                            worker: {
                                                                ...formData.config?.worker,
                                                                reconciliation_interval_hours: parseInt(e.target.value)
                                                            }
                                                        }
                                                    })}
                                                    className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-green-500/50"
                                                />
                                            </div>
                                            <div>
                                                <label className="block text-xs font-medium text-white/60 mb-1">
                                                    Validation Timeout (s)
                                                </label>
                                                <input
                                                    type="number"
                                                    min="60"
                                                    max="1800"
                                                    value={formData.config?.worker?.validation_timeout_seconds ?? 300}
                                                    onChange={(e) => setFormData({
                                                        ...formData,
                                                        config: {
                                                            ...formData.config,
                                                            worker: {
                                                                ...formData.config?.worker,
                                                                validation_timeout_seconds: parseInt(e.target.value)
                                                            }
                                                        }
                                                    })}
                                                    className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-green-500/50"
                                                />
                                            </div>
                                        </div>

                                        {/* Beam-specific WebSocket settings */}
                                        {formData.type === 'beam' && (
                                            <div className="mt-3">
                                                <label className="block text-xs font-medium text-white/50 mb-2">WebSocket Settings</label>
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div>
                                                        <label className="block text-xs font-medium text-white/60 mb-1">
                                                            WS Max Size (MB)
                                                        </label>
                                                        <input
                                                            type="number"
                                                            min="10"
                                                            max="100"
                                                            value={formData.config?.worker?.ws_max_size_mb ?? 20}
                                                            onChange={(e) => setFormData({
                                                                ...formData,
                                                                config: {
                                                                    ...formData.config,
                                                                    worker: {
                                                                        ...formData.config?.worker,
                                                                        ws_max_size_mb: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            })}
                                                            className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-green-500/50"
                                                        />
                                                    </div>
                                                    <div>
                                                        <label className="block text-xs font-medium text-white/60 mb-1">
                                                            WS Open Timeout (s)
                                                        </label>
                                                        <input
                                                            type="number"
                                                            min="30"
                                                            max="300"
                                                            value={formData.config?.worker?.ws_open_timeout ?? 120}
                                                            onChange={(e) => setFormData({
                                                                ...formData,
                                                                config: {
                                                                    ...formData.config,
                                                                    worker: {
                                                                        ...formData.config?.worker,
                                                                        ws_open_timeout: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            })}
                                                            className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-green-500/50"
                                                        />
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    {/* Function Settings - Deploy Required (Modal) */}
                                    {formData.type === 'modal' && (
                                        <div>
                                            <h4 className="flex items-center gap-2 text-sm font-semibold text-white/80 mb-3">
                                                <span className="text-purple-400">🚀</span> ComfyUI Function
                                                <span className="text-xs font-normal text-purple-400/80">(Deploy required)</span>
                                            </h4>
                                            <div className="grid grid-cols-3 gap-3">
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">GPU Type</label>
                                                    <select
                                                        value={formData.config?.functions?.comfyui?.gpu_type ?? 'L4'}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    comfyui: {
                                                                        ...formData.config?.functions?.comfyui,
                                                                        gpu_type: e.target.value
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    >
                                                        <option value="T4">T4 ($0.59/hr)</option>
                                                        <option value="L4">L4 ($0.76/hr)</option>
                                                        <option value="A10G">A10G ($1.10/hr)</option>
                                                        <option value="A100">A100 ($3.00/hr)</option>
                                                    </select>
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Timeout (s)</label>
                                                    <input
                                                        type="number"
                                                        min="60"
                                                        max="3600"
                                                        value={formData.config?.functions?.comfyui?.timeout_seconds ?? 600}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    comfyui: {
                                                                        ...formData.config?.functions?.comfyui,
                                                                        timeout_seconds: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Max Containers</label>
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="10"
                                                        value={formData.config?.functions?.comfyui?.max_containers ?? 1}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    comfyui: {
                                                                        ...formData.config?.functions?.comfyui,
                                                                        max_containers: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                            </div>
                                            {/* Second row: CPU, scaledown */}
                                            <div className="grid grid-cols-3 gap-3 mt-2">
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">CPU Cores</label>
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="8"
                                                        value={formData.config?.functions?.comfyui?.cpu ?? 2}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    comfyui: {
                                                                        ...formData.config?.functions?.comfyui,
                                                                        cpu: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Scaledown (s)</label>
                                                    <input
                                                        type="number"
                                                        min="5"
                                                        max="300"
                                                        value={formData.config?.functions?.comfyui?.scaledown_window_seconds ?? 15}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    comfyui: {
                                                                        ...formData.config?.functions?.comfyui,
                                                                        scaledown_window_seconds: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Snapshot Scaledown</label>
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="60"
                                                        value={formData.config?.functions?.comfyui?.scaledown_snapshot_seconds ?? 5}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    comfyui: {
                                                                        ...formData.config?.functions?.comfyui,
                                                                        scaledown_snapshot_seconds: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                            </div>

                                            {/* Download Function */}
                                            <h4 className="flex items-center gap-2 text-sm font-semibold text-white/80 mb-3 mt-4">
                                                <span className="text-purple-400">📥</span> Download Function
                                            </h4>
                                            <div className="grid grid-cols-2 gap-3">
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Timeout (s)</label>
                                                    <input
                                                        type="number"
                                                        min="300"
                                                        max="7200"
                                                        value={formData.config?.functions?.download?.timeout_seconds ?? 1800}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    download: {
                                                                        ...formData.config?.functions?.download,
                                                                        timeout_seconds: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Max Containers</label>
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="10"
                                                        value={formData.config?.functions?.download?.max_containers ?? 5}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    download: {
                                                                        ...formData.config?.functions?.download,
                                                                        max_containers: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                            </div>

                                            {/* Storage Function */}
                                            <h4 className="flex items-center gap-2 text-sm font-semibold text-white/80 mb-3 mt-4">
                                                <span className="text-purple-400">📁</span> Storage Function
                                            </h4>
                                            <div className="grid grid-cols-3 gap-3">
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Timeout (s)</label>
                                                    <input
                                                        type="number"
                                                        min="60"
                                                        max="1800"
                                                        value={formData.config?.functions?.storage?.timeout_seconds ?? 300}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    storage: {
                                                                        ...formData.config?.functions?.storage,
                                                                        timeout_seconds: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Max Containers</label>
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="5"
                                                        value={formData.config?.functions?.storage?.max_containers ?? 1}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    storage: {
                                                                        ...formData.config?.functions?.storage,
                                                                        max_containers: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Scaledown (s)</label>
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="60"
                                                        value={formData.config?.functions?.storage?.scaledown_window_seconds ?? 5}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    storage: {
                                                                        ...formData.config?.functions?.storage,
                                                                        scaledown_window_seconds: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                            </div>

                                            {/* Validate Function */}
                                            <h4 className="flex items-center gap-2 text-sm font-semibold text-white/80 mb-3 mt-4">
                                                <span className="text-purple-400">✅</span> Validate Function
                                            </h4>
                                            <div className="grid grid-cols-2 gap-3">
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Timeout (s)</label>
                                                    <input
                                                        type="number"
                                                        min="60"
                                                        max="3600"
                                                        value={formData.config?.functions?.validate?.timeout_seconds ?? 600}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    validate: {
                                                                        ...formData.config?.functions?.validate,
                                                                        timeout_seconds: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Max Containers</label>
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="5"
                                                        value={formData.config?.functions?.validate?.max_containers ?? 1}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    validate: {
                                                                        ...formData.config?.functions?.validate,
                                                                        max_containers: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    )}

                                    {/* Function Settings - Deploy Required (Beam) */}

                                    {formData.type === 'beam' && (
                                        <div>
                                            <h4 className="flex items-center gap-2 text-sm font-semibold text-white/80 mb-3">
                                                <span className="text-purple-400">🚀</span> GPU Deployment
                                                <span className="text-xs font-normal text-purple-400/80">(Deploy required)</span>
                                            </h4>
                                            {/* Row 1: GPU type, CPU, Memory */}
                                            <div className="grid grid-cols-3 gap-3 mb-2">
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">GPU Type</label>
                                                    <select
                                                        value={formData.config?.functions?.comfyui?.gpu_type ?? 'RTX4090'}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    comfyui: {
                                                                        ...formData.config?.functions?.comfyui,
                                                                        gpu_type: e.target.value
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    >
                                                        <option value="RTX4090">RTX 4090 ($0.45/hr)</option>
                                                        <option value="A10G">A10G ($0.60/hr)</option>
                                                        <option value="A100-40">A100 40GB ($1.50/hr)</option>
                                                        <option value="A100-80">A100 80GB ($2.00/hr)</option>
                                                        <option value="H100">H100 ($4.00/hr)</option>
                                                    </select>
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">CPU Cores</label>
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="16"
                                                        value={formData.config?.functions?.comfyui?.cpu ?? 4}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    comfyui: {
                                                                        ...formData.config?.functions?.comfyui,
                                                                        cpu: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Memory (Gi)</label>
                                                    <input
                                                        type="number"
                                                        min="4"
                                                        max="128"
                                                        value={parseInt(formData.config?.functions?.comfyui?.memory?.replace('Gi', '')) || 16}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    comfyui: {
                                                                        ...formData.config?.functions?.comfyui,
                                                                        memory: `${e.target.value}Gi`
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                            </div>
                                            {/* Row 2: Timeout, Keep Warm, Concurrent */}
                                            <div className="grid grid-cols-3 gap-3">
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Timeout (s)</label>
                                                    <input
                                                        type="number"
                                                        min="60"
                                                        max="3600"
                                                        value={formData.config?.functions?.comfyui?.timeout_seconds ?? 600}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    comfyui: {
                                                                        ...formData.config?.functions?.comfyui,
                                                                        timeout_seconds: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Keep Warm (s)</label>
                                                    <input
                                                        type="number"
                                                        min="0"
                                                        max="300"
                                                        value={formData.config?.functions?.comfyui?.keep_warm_seconds ?? 10}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    comfyui: {
                                                                        ...formData.config?.functions?.comfyui,
                                                                        keep_warm_seconds: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Concurrent</label>
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="10"
                                                        value={formData.config?.functions?.comfyui?.concurrent_requests ?? 1}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    comfyui: {
                                                                        ...formData.config?.functions?.comfyui,
                                                                        concurrent_requests: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                            </div>

                                            {/* Download Deployment */}
                                            <h4 className="flex items-center gap-2 text-sm font-semibold text-white/80 mb-3 mt-4">
                                                <span className="text-purple-400">📥</span> Download Deployment
                                            </h4>
                                            <div className="grid grid-cols-2 gap-3">
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Max Containers</label>
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="10"
                                                        value={formData.config?.functions?.download?.max_containers ?? 3}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    download: {
                                                                        ...formData.config?.functions?.download,
                                                                        max_containers: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Concurrent</label>
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="10"
                                                        value={formData.config?.functions?.download?.concurrent ?? 5}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    download: {
                                                                        ...formData.config?.functions?.download,
                                                                        concurrent: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                            </div>

                                            {/* Storage Deployment */}
                                            <h4 className="flex items-center gap-2 text-sm font-semibold text-white/80 mb-3 mt-4">
                                                <span className="text-purple-400">📁</span> Storage Deployment
                                            </h4>
                                            <div className="grid grid-cols-3 gap-3">
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">CPU Cores</label>
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="8"
                                                        value={formData.config?.functions?.storage?.cpu ?? 3}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    storage: {
                                                                        ...formData.config?.functions?.storage,
                                                                        cpu: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Memory (Gi)</label>
                                                    <input
                                                        type="number"
                                                        min="2"
                                                        max="16"
                                                        value={parseInt(formData.config?.functions?.storage?.memory?.replace('Gi', '')) || 4}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    storage: {
                                                                        ...formData.config?.functions?.storage,
                                                                        memory: `${e.target.value}Gi`
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-white/60 mb-1">Max Containers</label>
                                                    <input
                                                        type="number"
                                                        min="1"
                                                        max="5"
                                                        value={formData.config?.functions?.storage?.max_containers ?? 1}
                                                        onChange={(e) => setFormData({
                                                            ...formData,
                                                            config: {
                                                                ...formData.config,
                                                                functions: {
                                                                    ...formData.config?.functions,
                                                                    storage: {
                                                                        ...formData.config?.functions?.storage,
                                                                        max_containers: parseInt(e.target.value)
                                                                    }
                                                                }
                                                            }
                                                        })}
                                                        className="w-full px-3 py-2 bg-gray-800/50 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-purple-500/50"
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    )}

                                    {/* Legend */}

                                    <div className="flex gap-4 text-xs text-white/50 pt-2 border-t border-white/5">
                                        <span><span className="text-green-400">⚡</span> Hot-reload (instant)</span>
                                        <span><span className="text-blue-400">🔄</span> Container restart</span>
                                        <span><span className="text-purple-400">🚀</span> Deploy required</span>
                                    </div>
                                </div>
                            </details>
                        </div>
                    )}

                    {/* Enabled Checkbox */}
                    <div className="pt-4">
                        <label className="flex items-center gap-3 cursor-pointer">
                            <input
                                type="checkbox"
                                checked={formData.enabled}
                                onChange={(e) => setFormData({ ...formData, enabled: e.target.checked })}
                                className="w-5 h-5 accent-blue-500 cursor-pointer"
                            />
                            <span className="text-white/90">Enabled</span>
                        </label>
                    </div>

                    {/* Actions */}
                    <div className="flex gap-3 justify-end pt-6 border-t border-white/10 mt-6">
                        <button
                            type="button"
                            onClick={onClose}
                            className="px-6 py-3 bg-gray-800/80 hover:bg-gray-700/90 border border-white/10 rounded-lg text-white/80 hover:text-white font-medium transition-all"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-blue-500 to-purple-500 hover:from-blue-600 hover:to-purple-600 text-white rounded-xl font-medium transition-all duration-200 hover:-translate-y-0.5 shadow-lg shadow-blue-500/30"
                        >
                            {provider ? 'Update' : 'Add'} Provider
                        </button>
                    </div>
                </form>
            </motion.div>
        </motion.div>
    );
}

function LogsModal({ providerId, onClose }) {
    const [logs, setLogs] = useState('');
    const [loading, setLoading] = useState(true);

    const fetchLogs = useCallback(async () => {
        try {
            const data = await providersApi.getContainerLogs(providerId, 100);
            setLogs(data.logs);
        } catch (error) {
            console.error('Failed to fetch logs:', error);
            setLogs('Failed to fetch logs');
        } finally {
            setLoading(false);
        }
    }, [providerId]);

    useEffect(() => {
        fetchLogs();
    }, [fetchLogs]);

    return (
        <motion.div
            className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
        >
            <motion.div
                className="glass p-6 rounded-2xl border border-white/10 shadow-2xl max-w-4xl w-full max-h-[80vh] flex flex-col"
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.9, opacity: 0 }}
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between mb-4 pb-4 border-b border-white/10">
                    <h2 className="flex items-center gap-2 text-xl font-semibold bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-transparent">
                        <FileText size={24} className="text-blue-400" />
                        Container Logs - {providerId}
                    </h2>
                    <div className="flex gap-2">
                        <button
                            onClick={fetchLogs}
                            disabled={loading}
                            className="px-4 py-2 bg-blue-600/80 hover:bg-blue-600 border border-white/10 rounded-lg text-white font-medium transition-all flex items-center gap-2"
                        >
                            <RotateCw size={16} className={loading ? 'animate-spin' : ''} />
                            Refresh
                        </button>
                        <button
                            onClick={onClose}
                            className="px-4 py-2 bg-gray-800/80 hover:bg-gray-700/90 border border-white/10 rounded-lg text-white/80 hover:text-white font-medium transition-all"
                        >
                            Close
                        </button>
                    </div>
                </div>

                <div className="flex-1 overflow-auto">
                    {loading ? (
                        <div className="flex items-center justify-center py-12 text-white/60">
                            Loading logs...
                        </div>
                    ) : (
                        <pre className="bg-black/40 border border-white/10 rounded-lg p-4 text-green-400 text-xs font-mono overflow-x-auto whitespace-pre-wrap">
                            {logs || 'No logs available'}
                        </pre>
                    )}
                </div>
            </motion.div>
        </motion.div>
    );
}
