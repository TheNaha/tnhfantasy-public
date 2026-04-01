/**
 * Enhanced Sync Status Display
 * Shows BOTH reconciliation status AND model storage in separate blocks
 */
import { CheckCircle, Clock, Download, XCircle, RefreshCw, Database, AlertCircle, Loader2, Trash2, Eye } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

// Phase display configuration
const PHASE_CONFIG = {
    validating: { label: 'Validating', icon: CheckCircle, colorClass: 'text-yellow-400' },
    fetching: { label: 'Fetching', icon: Loader2, colorClass: 'text-blue-400' },
    downloading: { label: 'Downloading', icon: Download, colorClass: 'text-blue-400' },
    deleting: { label: 'Cleaning', icon: Trash2, colorClass: 'text-orange-400' },
    completed: { label: 'Complete', icon: CheckCircle, colorClass: 'text-green-400' },
    failed: { label: 'Failed', icon: XCircle, colorClass: 'text-red-400' },
};

/**
 * Main component that shows both blocks
 */
export default function SyncStatusBadge({
    providerId,
    stats,
    modalStats,
    reconciliation,
    onReconciliationClick,
    onStorageClick
}) {
    const isReconciling = reconciliation &&
        (reconciliation.status === 'reconciling' ||
            reconciliation.status === 'completed' ||
            reconciliation.status === 'failed');

    return (
        <div className="space-y-3">
            {/* Reconciliation Block - Only shown when active */}
            <AnimatePresence>
                {isReconciling && (
                    <ReconciliationBlock
                        reconciliation={reconciliation}
                        onClick={onReconciliationClick}
                    />
                )}
            </AnimatePresence>

            {/* Storage Block - Always visible */}
            <StorageBlock
                modalStats={modalStats}
                stats={stats}
                onClick={onStorageClick}
            />
        </div>
    );
}

/**
 * Reconciliation progress block - inline display with phase indicator
 */
function ReconciliationBlock({ reconciliation, onClick }) {
    const phase = reconciliation.phase || 'validating';
    const phaseConfig = PHASE_CONFIG[phase] || PHASE_CONFIG.validating;
    const PhaseIcon = phaseConfig.icon;

    const stats = reconciliation.stats || {};
    const activeDownloads = reconciliation.active_downloads || [];
    const isReconciling = reconciliation.status === 'reconciling';
    const isCompleted = reconciliation.status === 'completed';

    // Calculate progress
    const queued = stats.downloads_queued || 0;
    const completed = stats.downloads_completed || 0;
    const failed = stats.downloads_failed || 0;
    const progress = queued > 0 ? ((completed + failed) / queued) * 100 : 0;

    // Get border class based on status
    const borderClass = isReconciling
        ? 'bg-blue-500/5 border-blue-500/30'
        : isCompleted
            ? 'bg-green-500/5 border-green-500/30'
            : 'bg-red-500/5 border-red-500/30';

    return (
        <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className={`rounded-lg border p-3 cursor-pointer transition-all hover:border-blue-500/50 ${borderClass}`}
            onClick={onClick}
        >
            {/* Phase Header */}
            <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                    <PhaseIcon
                        className={`${phaseConfig.colorClass} ${isReconciling && phase !== 'completed' ? 'animate-spin' : ''}`}
                        size={16}
                    />
                    <span className={`text-sm font-medium ${phaseConfig.colorClass}`}>
                        {phaseConfig.label}
                    </span>
                    {reconciliation.message && (
                        <span className="text-xs text-gray-500 hidden sm:inline">
                            — {reconciliation.message}
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-2 text-xs text-gray-400">
                    {queued > 0 && (
                        <span>{completed + failed}/{queued}</span>
                    )}
                    <Eye size={12} className="opacity-60" />
                </div>
            </div>

            {/* Progress Bar - only show if there are queued downloads */}
            {isReconciling && queued > 0 && (
                <div className="w-full bg-gray-700 rounded-full h-1.5 mb-2 overflow-hidden">
                    <motion.div
                        className="h-full bg-gradient-to-r from-blue-500 to-purple-500"
                        initial={{ width: 0 }}
                        animate={{ width: `${progress}%` }}
                        transition={{ duration: 0.3 }}
                    />
                </div>
            )}

            {/* Active Downloads (show up to 3) */}
            {activeDownloads.length > 0 && (
                <div className="space-y-1">
                    {activeDownloads.slice(0, 3).map((dl, idx) => (
                        <div key={dl.file_id || idx} className="flex items-center gap-2 text-xs">
                            <Download className="text-blue-400 animate-pulse flex-shrink-0" size={10} />
                            <span className="text-gray-400 truncate flex-1">{dl.name}</span>
                            <span className="text-gray-500">{dl.index}/{dl.total}</span>
                        </div>
                    ))}
                    {activeDownloads.length > 3 && (
                        <div className="text-xs text-gray-500 pl-4">
                            +{activeDownloads.length - 3} more...
                        </div>
                    )}
                </div>
            )}

            {/* Stats Row - only show if there are any stats */}
            {(completed > 0 || failed > 0 || stats.deletions_completed > 0) && (
                <div className="flex items-center gap-3 mt-2 text-xs">
                    {completed > 0 && (
                        <span className="text-green-400 flex items-center gap-1">
                            <CheckCircle size={10} />
                            {completed}
                        </span>
                    )}
                    {failed > 0 && (
                        <span className="text-red-400 flex items-center gap-1">
                            <XCircle size={10} />
                            {failed}
                        </span>
                    )}
                    {stats.deletions_completed > 0 && (
                        <span className="text-orange-400 flex items-center gap-1">
                            <Trash2 size={10} />
                            {stats.deletions_completed}
                        </span>
                    )}
                </div>
            )}

            {/* Error indicator */}
            {reconciliation.errors?.length > 0 && (
                <div className="mt-2 flex items-center gap-1 text-xs text-red-400">
                    <AlertCircle size={10} />
                    <span>{reconciliation.errors.length} error(s) - click for details</span>
                </div>
            )}
        </motion.div>
    );
}

/**
 * Storage block - shows model counts by directory
 */
function StorageBlock({ modalStats, stats, onClick }) {
    // If we have real modal stats, show those
    if (modalStats && modalStats.total > 0) {
        return <ModalStatsDisplay modalStats={modalStats} onClick={onClick} />;
    }

    // Fall back to sync status
    if (stats) {
        const { pending = 0, downloading = 0, installed = 0, failed = 0 } = stats;
        const total = pending + downloading + installed + failed;

        if (total > 0) {
            return (
                <div
                    className={`bg-gray-900/50 rounded-lg border border-gray-700 p-3 ${onClick ? 'cursor-pointer hover:border-gray-500' : ''}`}
                    onClick={onClick}
                >
                    <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                            <Database className="text-gray-400" size={14} />
                            <span className="text-xs text-gray-400">Sync Status</span>
                        </div>
                        <span className="text-sm font-medium text-white">{total} models</span>
                    </div>
                    <div className="flex gap-3 text-xs">
                        <span className="text-green-400">{installed} installed</span>
                        {pending > 0 && <span className="text-yellow-400">{pending} pending</span>}
                        {downloading > 0 && <span className="text-blue-400">{downloading} downloading</span>}
                        {failed > 0 && <span className="text-red-400">{failed} failed</span>}
                    </div>
                </div>
            );
        }
    }

    // No data
    return (
        <div className="bg-gray-900/50 rounded-lg border border-gray-700 p-3">
            <div className="flex items-center gap-2 text-sm text-gray-500">
                <Database size={14} />
                <span>No models synced</span>
            </div>
        </div>
    );
}

/**
 * Modal storage stats display with directory breakdown
 */
function ModalStatsDisplay({ modalStats, onClick }) {
    const { total, by_directory = {} } = modalStats;

    const directoryLabels = {
        'checkpoints': 'Checkpoints',
        'loras': 'LoRAs',
        'vae': 'VAE',
        'controlnet': 'ControlNet',
        'unet': 'UNet',
        'clip': 'CLIP',
        'upscale/models': 'Upscalers',
        'embeddings': 'Embeddings',
        'hypernetworks': 'Hypernetworks',
        'aesthetics': 'Aesthetics',
        'poses': 'Poses',
        'wildcards': 'Wildcards',
        'motion_modules': 'Motion'
    };

    return (
        <div
            className={`bg-gray-900/50 rounded-lg border border-purple-500/20 p-3 ${onClick ? 'cursor-pointer hover:border-purple-500/40 transition-colors' : ''}`}
            onClick={onClick}
        >
            {/* Header with total */}
            <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                    <Database className="text-purple-400" size={14} />
                    <span className="text-xs text-purple-400/80">Provider Storage</span>
                </div>
                <span className="text-sm font-semibold text-white">
                    {total} models
                </span>
            </div>

            {/* Breakdown by directory (compact) */}
            <div className="flex flex-wrap gap-1.5">
                {Object.entries(by_directory)
                    .filter(([, count]) => count > 0)
                    .slice(0, 6)
                    .map(([dir, count]) => (
                        <span
                            key={dir}
                            className="px-1.5 py-0.5 bg-gray-800/50 rounded text-xs text-gray-400 border border-gray-700/50"
                        >
                            {directoryLabels[dir] || dir}: {count}
                        </span>
                    ))
                }
                {Object.keys(by_directory).filter(k => by_directory[k] > 0).length > 6 && (
                    <span className="text-xs text-gray-500">+more</span>
                )}
            </div>
        </div>
    );
}
