import { AlertCircle, CheckCircle, Database, Download, Eye, HardDrive, Loader2, RefreshCw, XCircle } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const PHASE_CONFIG = {
    queued: { label: 'Queued', icon: RefreshCw, colorClass: 'text-yellow-400' },
    validating: { label: 'Validating', icon: CheckCircle, colorClass: 'text-yellow-400' },
    fetching: { label: 'Fetching', icon: Loader2, colorClass: 'text-blue-400' },
    downloading: { label: 'Downloading', icon: Download, colorClass: 'text-blue-400' },
    deleting: { label: 'Cleaning', icon: RefreshCw, colorClass: 'text-orange-400' },
    completed: { label: 'Complete', icon: CheckCircle, colorClass: 'text-green-400' },
    failed: { label: 'Failed', icon: XCircle, colorClass: 'text-red-400' },
};

export default function SyncStatusBadge({
    providerId,
    modelSync,
    storage,
    reconciliation,
    diagnostics,
    onReconciliationClick,
}) {
    const syncStats = modelSync?.stats || {};
    const storageStats = storage || {};
    const warningCount = diagnostics?.warnings?.length || 0;
    const errorCount = diagnostics?.errors?.length || 0;
    const isActive = ['queued', 'reconciling', 'completed', 'failed'].includes(reconciliation?.status);

    return (
        <div className="space-y-3">
            <AnimatePresence>
                {isActive && (
                    <ReconciliationBlock
                        providerId={providerId}
                        reconciliation={reconciliation}
                        onClick={onReconciliationClick}
                    />
                )}
            </AnimatePresence>

            <div className="rounded-xl border border-gray-700 bg-gray-900/40 p-4 space-y-4">
                <div className="flex items-start justify-between gap-3">
                    <div>
                        <div className="text-xs uppercase tracking-wide text-gray-500">Models</div>
                        <div className="text-sm text-gray-300 mt-1">
                            Canonical sync state and provider storage are shown together here.
                        </div>
                    </div>
                    <div className="text-right">
                        <div className="text-xs text-gray-500">Diagnostics</div>
                        <div className="text-sm text-white">{warningCount} warnings · {errorCount} errors</div>
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <DataCard
                        icon={Database}
                        label="DB Sync"
                        total={modelSync?.total_models || 0}
                        tone="blue"
                        items={[
                            `${syncStats.installed || 0} installed`,
                            `${syncStats.pending || 0} pending`,
                            `${syncStats.downloading || 0} downloading`,
                            `${syncStats.failed || 0} failed`,
                        ]}
                    />
                    <DataCard
                        icon={HardDrive}
                        label="Provider Storage"
                        total={storageStats.total || 0}
                        tone={storageStats.error ? 'yellow' : 'purple'}
                        items={storageStats.error
                            ? [storageStats.error]
                            : formatDirectoryBreakdown(storageStats.by_directory)}
                    />
                </div>

                {(warningCount > 0 || errorCount > 0) && (
                    <div className="flex flex-wrap gap-2 text-xs">
                        {diagnostics.errors?.slice(0, 2).map((message) => (
                            <span key={`error-${message}`} className="px-2 py-1 rounded-full bg-red-500/15 text-red-300 border border-red-500/25">
                                {message}
                            </span>
                        ))}
                        {diagnostics.warnings?.slice(0, 2).map((message) => (
                            <span key={`warning-${message}`} className="px-2 py-1 rounded-full bg-yellow-500/15 text-yellow-300 border border-yellow-500/25">
                                {message}
                            </span>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

function ReconciliationBlock({ reconciliation, onClick }) {
    const phase = reconciliation.phase || (reconciliation.status === 'queued' ? 'queued' : 'validating');
    const phaseConfig = PHASE_CONFIG[phase] || PHASE_CONFIG.validating;
    const PhaseIcon = phaseConfig.icon;
    const stats = reconciliation.stats || {};
    const queued = stats.downloads_queued || 0;
    const completed = stats.downloads_completed || 0;
    const failed = stats.downloads_failed || 0;
    const progress = queued > 0 ? ((completed + failed) / queued) * 100 : 0;
    const activeDownloads = reconciliation.active_downloads || [];
    const toneClass = reconciliation.status === 'failed'
        ? 'bg-red-500/5 border-red-500/30'
        : reconciliation.status === 'completed'
            ? 'bg-green-500/5 border-green-500/30'
            : 'bg-blue-500/5 border-blue-500/30';

    return (
        <motion.button
            type="button"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className={`w-full text-left rounded-xl border p-4 transition-colors hover:border-blue-400/50 ${toneClass}`}
            onClick={onClick}
        >
            <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 min-w-0">
                    <PhaseIcon className={`${phaseConfig.colorClass} ${reconciliation.status === 'reconciling' ? 'animate-spin' : ''}`} size={16} />
                    <span className={`text-sm font-medium ${phaseConfig.colorClass}`}>{phaseConfig.label}</span>
                    {reconciliation.message && (
                        <span className="text-xs text-gray-500 truncate">{reconciliation.message}</span>
                    )}
                </div>
                <div className="flex items-center gap-2 text-xs text-gray-400">
                    {queued > 0 && <span>{completed + failed}/{queued}</span>}
                    <Eye size={12} className="opacity-60" />
                </div>
            </div>

            {queued > 0 && (
                <div className="w-full bg-gray-700 rounded-full h-1.5 mt-3 overflow-hidden">
                    <motion.div
                        className="h-full bg-gradient-to-r from-blue-500 to-cyan-400"
                        initial={{ width: 0 }}
                        animate={{ width: `${progress}%` }}
                        transition={{ duration: 0.3 }}
                    />
                </div>
            )}

            {activeDownloads.length > 0 && (
                <div className="space-y-1 mt-3">
                    {activeDownloads.slice(0, 3).map((download, index) => (
                        <div key={download.file_id || index} className="flex items-center gap-2 text-xs">
                            <Download className="text-blue-400 animate-pulse flex-shrink-0" size={10} />
                            <span className="text-gray-300 truncate flex-1">{download.name}</span>
                            <span className="text-gray-500">{download.index}/{download.total}</span>
                        </div>
                    ))}
                </div>
            )}

            {(stats.deletions_completed > 0 || failed > 0) && (
                <div className="flex items-center gap-3 mt-3 text-xs">
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
                            <RefreshCw size={10} />
                            {stats.deletions_completed} cleaned
                        </span>
                    )}
                </div>
            )}

            {reconciliation.warning && (
                <div className="mt-3 flex items-center gap-1 text-xs text-yellow-300">
                    <AlertCircle size={10} />
                    <span>{reconciliation.warning}</span>
                </div>
            )}
        </motion.button>
    );
}

function DataCard({ icon: Icon, label, total, items, tone = 'blue' }) {
    const toneClasses = {
        blue: 'border-blue-500/20 bg-blue-500/5',
        purple: 'border-purple-500/20 bg-purple-500/5',
        yellow: 'border-yellow-500/20 bg-yellow-500/5',
    };

    return (
        <div className={`rounded-xl border p-3 ${toneClasses[tone] || toneClasses.blue}`}>
            <div className="flex items-center justify-between gap-3 mb-3">
                <div className="flex items-center gap-2">
                    <Icon size={14} className="text-gray-400" />
                    <span className="text-xs uppercase tracking-wide text-gray-500">{label}</span>
                </div>
                <span className="text-sm font-semibold text-white">{total} models</span>
            </div>
            <div className="flex flex-wrap gap-2">
                {items.map((item) => (
                    <span key={item} className="px-2 py-1 rounded-full bg-gray-900/70 border border-gray-700 text-xs text-gray-300">
                        {item}
                    </span>
                ))}
            </div>
        </div>
    );
}

function formatDirectoryBreakdown(byDirectory = {}) {
    const labels = {
        checkpoints: 'Checkpoints',
        loras: 'LoRAs',
        vae: 'VAE',
        controlnet: 'ControlNet',
        unet: 'UNet',
        clip: 'CLIP',
        upscale_models: 'Upscalers',
        embeddings: 'Embeddings',
        hypernetworks: 'Hypernetworks',
        motion_modules: 'Motion',
    };

    const items = Object.entries(byDirectory)
        .filter(([, count]) => count > 0)
        .slice(0, 6)
        .map(([directory, count]) => `${labels[directory] || directory}: ${count}`);

    return items.length > 0 ? items : ['No storage stats yet'];
}
