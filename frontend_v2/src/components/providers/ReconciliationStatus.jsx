import { useEffect, useState } from 'react';
import { X, Download, CheckCircle, XCircle, Clock, HardDrive, AlertCircle, RefreshCw, Trash2, Loader2, Search } from 'lucide-react';
import { motion } from 'framer-motion';
import useReconciliationStore from '../../store/reconciliationStore';
import { providersApi } from '../../api';
import { normalizeReconciliationStatus } from '../../hooks/useProviderModels';

// Phase definitions with static Tailwind classes
const PHASES = {
    validating: {
        label: 'Validating Files',
        icon: Search,
        desc: 'Checking for corrupt or partial files',
        iconClass: 'text-yellow-400',
        bgClass: 'bg-yellow-500/10 border-yellow-500/20'
    },
    fetching: {
        label: 'Fetching Lists',
        icon: RefreshCw,
        desc: 'Querying backend for pending downloads',
        iconClass: 'text-blue-400',
        bgClass: 'bg-blue-500/10 border-blue-500/20'
    },
    downloading: {
        label: 'Downloading Models',
        icon: Download,
        desc: 'Syncing models to provider storage',
        iconClass: 'text-blue-400',
        bgClass: 'bg-blue-500/10 border-blue-500/20'
    },
    deleting: {
        label: 'Cleaning Up',
        icon: Trash2,
        desc: 'Removing orphaned files',
        iconClass: 'text-orange-400',
        bgClass: 'bg-orange-500/10 border-orange-500/20'
    },
    completed: {
        label: 'Complete',
        icon: CheckCircle,
        desc: 'Reconciliation finished successfully',
        iconClass: 'text-green-400',
        bgClass: 'bg-green-500/10 border-green-500/20'
    },
    failed: {
        label: 'Failed',
        icon: XCircle,
        desc: 'Reconciliation encountered errors',
        iconClass: 'text-red-400',
        bgClass: 'bg-red-500/10 border-red-500/20'
    },
};

const PHASE_ORDER = ['validating', 'fetching', 'downloading', 'deleting', 'completed'];

export default function ReconciliationStatus({ providerId, onClose }) {
    // Read from global store - WebSocket updates happen globally now
    const rawStoreStatus = useReconciliationStore(state => state.activeReconciliations[providerId]);
    const storeStatus = hasReconciliationContent(rawStoreStatus)
        ? normalizeReconciliationStatus(rawStoreStatus)
        : null;
    const [localStatus, setLocalStatus] = useState(null);
    
    // Use store status if available, otherwise fall back to local fetch
    const status = storeStatus || (localStatus ? normalizeReconciliationStatus(localStatus) : null);

    // Initial fetch only if not in store
    useEffect(() => {
        if (storeStatus) return; // Already have data from store
        
        const fetchInitialStatus = async () => {
            try {
                const data = await providersApi.getReconciliationStatus(providerId);
                setLocalStatus(normalizeReconciliationStatus(data));
            } catch (error) {
                console.error('Failed to fetch reconciliation status:', error);
            }
        };
        fetchInitialStatus();
    }, [providerId, storeStatus]);

    if (!status) {
        return (
            <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
                <div className="bg-gray-800 rounded-xl border border-gray-700 p-8">
                    <Loader2 className="animate-spin text-blue-400 mx-auto" size={32} />
                    <div className="text-gray-400 mt-3">Loading status...</div>
                </div>
            </div>
        );
    }

    const phase = status.phase || 'validating';
    const phaseConfig = PHASES[phase] || PHASES.validating;
    const PhaseIcon = phaseConfig.icon;
    const stats = status.stats || {};
    const activeDownloads = status.active_downloads || [];
    const errors = status.errors || [];
    const isReconciling = status.status === 'reconciling';
    const isCompleted = status.status === 'completed';
    const isFailed = status.status === 'failed';

    // Calculate progress
    const queued = stats.downloads_queued || 0;
    const completed = stats.downloads_completed || 0;
    const failed = stats.downloads_failed || 0;
    const progress = queued > 0 ? ((completed + failed) / queued) * 100 : 0;

    // Current phase index for stepper
    const currentPhaseIndex = PHASE_ORDER.indexOf(phase);

    return (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                className="bg-gray-800 rounded-xl border border-gray-700 max-w-2xl w-full max-h-[90vh] overflow-hidden flex flex-col"
            >
                {/* Header with Phase */}
                <div className="sticky top-0 bg-gray-800 border-b border-gray-700 px-6 py-4">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <div className={`p-2 rounded-lg border ${phaseConfig.bgClass}`}>
                                <PhaseIcon
                                    className={`${phaseConfig.iconClass} ${isReconciling && phase !== 'completed' ? 'animate-spin' : ''}`}
                                    size={20}
                                />
                            </div>
                            <div>
                                <h2 className="text-lg font-semibold text-white">{phaseConfig.label}</h2>
                                <p className="text-xs text-gray-400">{phaseConfig.desc}</p>
                            </div>
                        </div>
                        <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors" aria-label="Close status">
                            <X size={24} />
                        </button>
                    </div>

                    {/* Phase Progress Stepper */}
                    <div className="flex items-center gap-1 mt-4">
                        {PHASE_ORDER.map((p, i) => {
                            const isPast = currentPhaseIndex > i;
                            const isCurrent = currentPhaseIndex === i;

                            let barClass = 'bg-gray-700';
                            if (isPast) barClass = 'bg-green-500';
                            else if (isCurrent) barClass = 'bg-blue-500 animate-pulse';

                            return (
                                <div key={p} className="flex-1">
                                    <div className={`h-1.5 rounded ${barClass}`} />
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6">
                    {/* Message */}
                    {status.message && (
                        <div className="text-sm text-gray-300 bg-gray-900/50 rounded-lg px-4 py-2 border border-gray-700">
                            {status.message}
                        </div>
                    )}

                    {/* Stats Grid */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <StatCard
                            icon={<HardDrive size={16} />}
                            label="In Storage"
                            value={stats.total_models_in_storage || stats.total_models_in_modal || 0}
                            colorClass="text-purple-400"
                            borderClass="border-purple-500/20"
                        />
                        <StatCard
                            icon={<Download size={16} />}
                            label="Queued"
                            value={queued}
                            colorClass="text-blue-400"
                            borderClass="border-blue-500/20"
                        />
                        <StatCard
                            icon={<CheckCircle size={16} />}
                            label="Downloaded"
                            value={completed}
                            colorClass="text-green-400"
                            borderClass="border-green-500/20"
                        />
                        <StatCard
                            icon={<XCircle size={16} />}
                            label="Failed"
                            value={failed}
                            colorClass="text-red-400"
                            borderClass="border-red-500/20"
                        />
                    </div>

                    {/* Overall Progress */}
                    {queued > 0 && (
                        <div>
                            <div className="flex justify-between text-sm mb-2">
                                <span className="text-gray-400">Overall Progress</span>
                                <span className="text-white font-medium">{Math.round(progress)}%</span>
                            </div>
                            <div className="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
                                <motion.div
                                    className="h-full bg-gradient-to-r from-blue-500 to-purple-500"
                                    initial={{ width: 0 }}
                                    animate={{ width: `${progress}%` }}
                                    transition={{ duration: 0.3 }}
                                />
                            </div>
                        </div>
                    )}

                    {/* Active Downloads */}
                    {activeDownloads.length > 0 && (
                        <div className="bg-gray-900/50 rounded-lg border border-gray-700 p-4">
                            <div className="flex items-center gap-2 mb-3">
                                <Download className="text-blue-400 animate-pulse" size={16} />
                                <span className="text-sm font-medium text-white">
                                    Active Downloads ({activeDownloads.length})
                                </span>
                            </div>
                            <div className="space-y-2">
                                {activeDownloads.map((dl, idx) => (
                                    <div key={dl.file_id || idx} className="flex items-center gap-3 text-sm">
                                        <Loader2 className="text-blue-400 animate-spin flex-shrink-0" size={14} />
                                        <span className="text-gray-300 truncate flex-1">{dl.name}</span>
                                        <span className="text-gray-500 text-xs">{dl.index}/{dl.total}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Errors */}
                    {errors.length > 0 && (
                        <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-4">
                            <div className="flex items-center gap-2 mb-3">
                                <AlertCircle className="text-red-400" size={16} />
                                <h3 className="font-medium text-red-400">Errors ({errors.length})</h3>
                            </div>
                            <div className="space-y-2 max-h-40 overflow-y-auto custom-scrollbar">
                                {errors.map((error, idx) => (
                                    <div key={idx} className="text-sm text-gray-300 bg-gray-900/50 rounded px-3 py-2">
                                        {error}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Completion Message */}
                    {isCompleted && (
                        <div className="bg-green-900/20 border border-green-500/30 rounded-lg p-4">
                            <div className="flex items-center gap-2">
                                <CheckCircle className="text-green-400" size={20} />
                                <div>
                                    <p className="font-medium text-green-400">Reconciliation Complete!</p>
                                    <p className="text-sm text-gray-300 mt-1">
                                        {completed} models downloaded
                                        {failed > 0 && `, ${failed} failed`}
                                        {stats.deletions_completed > 0 && `, ${stats.deletions_completed} deleted`}
                                    </p>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Failed Message */}
                    {isFailed && (
                        <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-4">
                            <div className="flex items-center gap-2">
                                <XCircle className="text-red-400" size={20} />
                                <div>
                                    <p className="font-medium text-red-400">Reconciliation Failed</p>
                                    <p className="text-sm text-gray-300 mt-1">Check the errors above for details</p>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Idle State */}
                    {status.status === 'idle' && !activeDownloads.length && completed === 0 && (
                        <div className="bg-gray-900/50 rounded-lg border border-gray-700 p-8 text-center">
                            <Clock className="text-gray-500 mx-auto mb-3" size={32} />
                            <p className="text-gray-400">No reconciliation in progress</p>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="sticky bottom-0 bg-gray-800 border-t border-gray-700 px-6 py-4 flex justify-between items-center">
                    <div className="flex items-center gap-2 text-sm text-gray-400">
                        <span className={`w-2 h-2 rounded-full ${storeStatus ? 'bg-green-500' : 'bg-yellow-500'}`} />
                        {storeStatus ? 'Live updates active' : 'Fetched status'}
                    </div>
                    <button
                        onClick={onClose}
                        className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-colors"
                    >
                        Close
                    </button>
                </div>
            </motion.div>
        </div>
    );
}

function hasReconciliationContent(status) {
    if (!status) return false;
    return Boolean(
        status.status ||
        status.phase ||
        status.message ||
        status.stats ||
        status.current_download ||
        (Array.isArray(status.active_downloads) && status.active_downloads.length > 0) ||
        (Array.isArray(status.errors) && status.errors.length > 0)
    );
}

function StatCard({ icon, label, value, colorClass, borderClass }) {
    return (
        <div className={`bg-gray-900/50 rounded-lg border ${borderClass} p-3`}>
            <div className={`flex items-center gap-2 mb-1 ${colorClass}`}>
                {icon}
                <span className="text-xs text-gray-400">{label}</span>
            </div>
            <p className="text-xl font-bold text-white">{value}</p>
        </div>
    );
}
