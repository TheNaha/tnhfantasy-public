import { X, Loader2, Trash2, RefreshCw } from 'lucide-react';
import toast from 'react-hot-toast';
import { useConfirmation } from '../../store/confirmationStore';
import { getProviderDisplayName } from '../../utils/providerUtils';
import { formatElapsed, formatTimestamp } from '../../utils/dateTime';

import { memo } from 'react';
import { createPortal } from 'react-dom';

// ⚡ Bolt: Wrap JobDetailsModal in React.memo to prevent unnecessary re-renders when parent Dashboard updates
export default memo(function JobDetailsModal({ job, onClose, onCancel, onDelete, onRetry }) {
    const { confirm } = useConfirmation();

    if (!job) return null;

    const meta = job.metadata || job.metadata_ || {};
    const diagnostics = job.diagnostics || null;
    const checkpoint = typeof meta.checkpoint === 'object' ? meta.checkpoint?.name : meta.checkpoint;
    const isProcessing = ['retrying', 'sent-to-provider', 'connected', 'pre-generation', 'generating', 'processing', 'executing', 'progress', 'running', 'post-processing'].includes(job.status);
    const isPending = ['pending', 'queued'].includes(job.status);
    const isCompleted = job.status === 'completed';
    const isFailed = job.status === 'failed' || job.status === 'error';
    const isCancelled = job.status === 'cancelled';

    const handleActionClick = async (actionType) => {
        if (actionType === 'cancel') {
            const accepted = await confirm({
                title: "Cancel Job",
                message: "Are you sure you want to cancel this job? This action cannot be undone.",
                confirmText: "Yes, Cancel Job",
                isDangerous: true,
            });
            if (!accepted) return;
            try {
                await onCancel(job.id);
                onClose();
                toast.success('Job cancelled');
            } catch {
                toast.error('Failed to cancel job');
            }
        } else if (actionType === 'delete') {
            const accepted = await confirm({
                title: "Remove Job",
                message: "Are you sure you want to remove this job from history? The generated images will remain in your gallery.",
                confirmText: "Yes, Remove Job",
                isDangerous: true,
            });
            if (!accepted) return;
            try {
                await onDelete(job.id);
                onClose();
                toast.success('Job removed from history');
            } catch {
                toast.error('Failed to delete job');
            }
        }
    };

    // Calculate elapsed time
    const getElapsedTime = () => formatElapsed(job.created_at, job.completed_at);

    const formatDuration = (seconds) => {
        if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return null;
        if (seconds < 60) return `${Math.round(seconds)}s`;
        if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
        return `${Math.round(seconds / 3600)}h`;
    };

    const providerName = getProviderDisplayName(job.provider_id);

    return createPortal(
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4" onClick={onClose}>
            <div className="bg-gray-800 rounded-xl max-w-lg w-full max-h-[calc(85*var(--vh,1vh))] overflow-hidden border border-gray-700 flex flex-col !flex-nowrap shadow-2xl" onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div className="p-4 border-b border-gray-700 flex justify-between items-start bg-gray-900/50 flex-shrink-0">
                    <div>
                        <h3 className="text-lg font-bold text-white">Job Details</h3>
                        <p className="text-xs text-gray-500 font-mono mt-1">{job.id}</p>
                    </div>
                    <button onClick={onClose} className="text-gray-400 hover:text-white p-1 ml-2" aria-label="Close job details">
                        <X size={20} />
                    </button>
                </div>

                {/* Scrollable Content */}
                <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
                    {/* Status Row */}
                    <div className="flex items-center gap-3 flex-wrap">
                        <span className={`px-3 py-1.5 rounded-lg text-sm font-bold uppercase ${isCompleted ? 'bg-green-500/20 text-green-400 border border-green-500/30' :
                            isFailed ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                                isProcessing ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' :
                                    isCancelled ? 'bg-gray-500/20 text-gray-300 border border-gray-500/30' :
                                    'bg-gray-700 text-gray-400 border border-gray-600'
                            }`}>
                            {isProcessing && <Loader2 className="inline animate-spin mr-1" size={14} />}
                            {job.status}
                        </span>
                        {providerName && (
                            <span className="px-2 py-1 rounded text-xs bg-purple-500/20 text-purple-400 border border-purple-500/30">
                                {providerName}
                            </span>
                        )}
                        {getElapsedTime() && (
                            <span className="text-xs text-gray-500">
                                {isCompleted || isFailed ? 'Completed in ' : 'Elapsed: '}{getElapsedTime()}
                            </span>
                        )}
                    </div>

                    {/* Message */}
                    {job.message && (
                        <div className="bg-gray-900 p-3 rounded-lg border border-gray-700">
                            <p className="text-sm text-gray-300 break-words">{job.message}</p>
                        </div>
                    )}

                    {/* Error */}
                    {job.error && (
                        <div className="bg-red-900/20 p-3 rounded-lg border border-red-500/30">
                            <p className="text-sm text-red-400 break-words">{job.error}</p>
                        </div>
                    )}

                    {/* Diagnostics — why the job failed and whether it can be retried */}
                    {diagnostics && (isFailed || diagnostics.attempt_count > 0 || diagnostics.error_type) && (
                        <div className="bg-gray-900 p-3 rounded-lg border border-gray-700 space-y-2">
                            <div className="flex items-center justify-between gap-2">
                                <span className="text-xs text-gray-500 uppercase font-medium">Diagnostics</span>
                                {diagnostics.error_type && (
                                    <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-red-500/20 text-red-300 border border-red-400/30">
                                        {diagnostics.error_type.replace(/_/g, ' ')}
                                    </span>
                                )}
                            </div>
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                                <div className="bg-gray-800/60 p-2 rounded text-center">
                                    <span className="text-[10px] text-gray-500 block">Attempts</span>
                                    <span className="text-sm text-white">{diagnostics.attempt_count || 0}</span>
                                </div>
                                <div className="bg-gray-800/60 p-2 rounded text-center">
                                    <span className="text-[10px] text-gray-500 block">Duration</span>
                                    <span className="text-sm text-white">
                                        {formatDuration(diagnostics.duration_seconds) || '—'}
                                    </span>
                                </div>
                                <div className="bg-gray-800/60 p-2 rounded text-center">
                                    <span className="text-[10px] text-gray-500 block">Provider</span>
                                    <span className="text-sm text-white truncate block" title={diagnostics.last_provider_id || ''}>
                                        {diagnostics.last_provider_id || '—'}
                                    </span>
                                </div>
                                <div className="bg-gray-800/60 p-2 rounded text-center">
                                    <span className="text-[10px] text-gray-500 block">Retryable</span>
                                    <span className="text-sm text-white">{diagnostics.is_retryable ? 'Yes' : 'No'}</span>
                                </div>
                            </div>
                            {diagnostics.retry_of && (
                                <p className="text-[10px] text-gray-600 break-all">
                                    Retry of {diagnostics.retry_of}
                                </p>
                            )}
                            {Array.isArray(diagnostics.attempts) && diagnostics.attempts.length > 0 && (
                                <ol className="text-xs text-gray-400 space-y-1 pt-1 border-t border-gray-700">
                                    {diagnostics.attempts.map((attempt, index) => (
                                        <li key={index} className="flex items-center gap-2 flex-wrap">
                                            <span className="text-gray-600">#{index + 1}</span>
                                            <span className="text-gray-300">{attempt.provider_id || 'unassigned'}</span>
                                            <span className="text-gray-500">{attempt.outcome}</span>
                                            {attempt.duration_seconds != null && (
                                                <span className="text-gray-600">{formatDuration(attempt.duration_seconds)}</span>
                                            )}
                                            {attempt.error && <span className="text-red-400/80 break-words">— {attempt.error}</span>}
                                        </li>
                                    ))}
                                </ol>
                            )}
                        </div>
                    )}

                    {/* Progress Bars (if processing) */}
                    {isProcessing && (
                        <div className="space-y-2">
                            <div>
                                <div className="flex justify-between text-xs text-gray-500 mb-1">
                                    <span>Workflow Progress</span>
                                    <span>{Math.round(job.overall_progress || 0)}%</span>
                                </div>
                                <div className="w-full bg-gray-700 rounded-full h-2">
                                    <div className="progress-gradient h-full rounded-full transition-all" style={{ width: `${job.overall_progress || 0}%` }} />
                                </div>
                            </div>
                            {job.progress > 0 && (
                                <div>
                                    <div className="flex justify-between text-xs text-gray-500 mb-1">
                                        <span>Render Progress</span>
                                        <span>{Math.round(job.progress || 0)}%</span>
                                    </div>
                                    <div className="w-full bg-gray-700 rounded-full h-2">
                                        <div className="bg-gradient-to-r from-blue-500 to-cyan-400 h-full rounded-full transition-all" style={{ width: `${job.progress || 0}%` }} />
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Model Info */}
                    {checkpoint && (
                        <div className="bg-gray-900 p-3 rounded-lg border border-gray-700">
                            <span className="text-xs text-gray-500 uppercase font-medium">Model</span>
                            <p className="text-sm text-white mt-1 truncate" title={checkpoint}>{checkpoint.replace('.safetensors', '')}</p>
                        </div>
                    )}

                    {/* Generation Params Grid */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                        {meta.width && meta.height && (
                            <div className="bg-gray-900 p-2 rounded-lg border border-gray-700 text-center">
                                <span className="text-xs text-gray-500 block">Size</span>
                                <span className="text-sm text-white">{meta.width}×{meta.height}</span>
                            </div>
                        )}
                        {meta.steps && (
                            <div className="bg-gray-900 p-2 rounded-lg border border-gray-700 text-center">
                                <span className="text-xs text-gray-500 block">Steps</span>
                                <span className="text-sm text-white">{meta.steps}</span>
                            </div>
                        )}
                        {meta.cfg && (
                            <div className="bg-gray-900 p-2 rounded-lg border border-gray-700 text-center">
                                <span className="text-xs text-gray-500 block">CFG</span>
                                <span className="text-sm text-white">{meta.cfg}</span>
                            </div>
                        )}
                        {meta.sampler && (
                            <div className="bg-gray-900 p-2 rounded-lg border border-gray-700 text-center">
                                <span className="text-xs text-gray-500 block">Sampler</span>
                                <span className="text-sm text-white truncate" title={meta.sampler}>{meta.sampler}</span>
                            </div>
                        )}
                        {meta.scheduler && (
                            <div className="bg-gray-900 p-2 rounded-lg border border-gray-700 text-center">
                                <span className="text-xs text-gray-500 block">Scheduler</span>
                                <span className="text-sm text-white truncate" title={meta.scheduler}>{meta.scheduler}</span>
                            </div>
                        )}
                        {meta.seed && (
                            <div className="bg-gray-900 p-2 rounded-lg border border-gray-700 text-center col-span-2 sm:col-span-1">
                                <span className="text-xs text-gray-500 block">Seed</span>
                                <span className="text-sm text-white font-mono break-all block" title={String(meta.seed)}>{meta.seed}</span>
                            </div>
                        )}
                        {meta.batchSize && meta.batchSize > 1 && (
                            <div className="bg-gray-900 p-2 rounded-lg border border-gray-700 text-center">
                                <span className="text-xs text-gray-500 block">Batch</span>
                                <span className="text-sm text-white">{meta.batchSize}</span>
                            </div>
                        )}
                    </div>

                    {/* LoRAs */}
                    {meta.loras?.length > 0 && (
                        <div>
                            <span className="text-xs text-gray-500 uppercase font-medium mb-2 block">LoRAs ({meta.loras.length})</span>
                            <div className="flex flex-wrap gap-2">
                                {meta.loras.map((lora, i) => (
                                    <span key={i} className="px-2 py-1 bg-purple-500/20 text-purple-300 rounded text-xs border border-purple-500/30">
                                        {lora.name?.replace('.safetensors', '') || 'Unknown'} ({lora.strength})
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Prompt */}
                    {meta.prompt && (
                        <div>
                            <span className="text-xs text-gray-500 uppercase font-medium mb-2 block">Prompt</span>
                            <p className="text-sm text-gray-300 bg-gray-900 p-3 rounded-lg border border-gray-700 max-h-32 overflow-y-auto whitespace-pre-wrap break-words">
                                {meta.prompt}
                            </p>
                        </div>
                    )}

                    {/* Negative Prompt */}
                    {meta.negativePrompt && (
                        <div>
                            <span className="text-xs text-gray-500 uppercase font-medium mb-2 block">Negative Prompt</span>
                            <p className="text-sm text-gray-400 bg-gray-900 p-3 rounded-lg border border-gray-700 max-h-24 overflow-y-auto whitespace-pre-wrap break-words">
                                {meta.negativePrompt}
                            </p>
                        </div>
                    )}

                    {/* Timestamps */}
                    <div className="text-xs text-gray-600 space-y-1 pt-2 border-t border-gray-700">
                        {job.created_at && (
                            <p>Created: {formatTimestamp(job.created_at)}</p>
                        )}
                        {job.started_at && (
                            <p>Started: {formatTimestamp(job.started_at)}</p>
                        )}
                        {job.completed_at && (
                            <p>Completed: {formatTimestamp(job.completed_at)}</p>
                        )}
                    </div>
                </div>

                {/* Actions Footer */}
                <div className="p-4 border-t border-gray-700 flex flex-col sm:flex-row gap-2 flex-shrink-0">
                    {(isPending || isProcessing) && (
                        <button
                            onClick={() => handleActionClick('cancel')}
                            aria-label="Cancel this job"
                            className="flex-1 bg-red-600 hover:bg-red-500 text-white py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-2"
                        >
                            <X size={16} /> Cancel Job
                        </button>
                    )}
                    {(isCompleted || isFailed || isCancelled) && onDelete && (
                        <button
                            onClick={() => handleActionClick('delete')}
                            aria-label="Remove this job from history"
                            className="flex-1 bg-gray-700 hover:bg-gray-600 text-white py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-2"
                        >
                            <Trash2 size={16} /> Remove from History
                        </button>
                    )}
                    {isFailed && onRetry && (
                        <button
                            onClick={async () => {
                                try {
                                    await onRetry(job.id);
                                    onClose();
                                    toast.success('Job retry queued!');
                                } catch (e) {
                                    toast.error(e.message || 'Failed to retry job');
                                }
                            }}
                            disabled={diagnostics?.is_retryable === false}
                            aria-label="Retry this job"
                            title={diagnostics?.is_retryable === false
                                ? 'This job has no workflow to retry'
                                : 'Retry this job'}
                            className="flex-1 bg-blue-600 hover:bg-blue-500 text-white py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-blue-600"
                        >
                            <RefreshCw size={16} /> Retry Job
                        </button>
                    )}
                    <button
                        onClick={onClose}
                        aria-label="Close job details modal"
                        className="flex-1 bg-gray-700 hover:bg-gray-600 text-white py-2 rounded-lg text-sm font-medium"
                    >
                        Close
                    </button>
                </div>
            </div>
        </div>,
        document.body
    );
});
