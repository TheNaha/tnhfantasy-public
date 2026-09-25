import { useMemo, useState } from 'react';
import {
    AlertTriangle,
    ChevronDown,
    ChevronUp,
    LifeBuoy,
    RefreshCw,
    Server,
    Timer,
    X,
} from 'lucide-react';
import toast from 'react-hot-toast';
import { useJobRecovery } from '../../hooks/useJobRecovery';
import { getProviderDisplayName } from '../../utils/providerUtils';
import { formatTimestamp } from '../../utils/dateTime';

/**
 * Human-readable labels + guidance for the `diagnostics.error_type` values the
 * backend records. Anything unmapped falls back to the raw value so new server
 * side kinds still render instead of disappearing.
 */
const ERROR_TYPE_INFO = {
    no_providers: { label: 'No providers', hint: 'No enabled provider can run this workflow.' },
    providers_exhausted: { label: 'Providers exhausted', hint: 'Every provider was tried and failed.' },
    provider_error: { label: 'Provider error', hint: 'The provider rejected or crashed on this job.' },
    timeout: { label: 'Timed out', hint: 'The provider did not answer in time.' },
    stale_recovery: { label: 'Interrupted', hint: 'A restart or dead worker left this job running.' },
    finalization_failed: { label: 'Post-processing failed', hint: 'Output was produced but saving it failed.' },
    unexpected: { label: 'Unexpected error', hint: 'The job runner hit an unhandled error.' },
    cancelled: { label: 'Cancelled', hint: 'The job was cancelled.' },
    unknown: { label: 'Failed', hint: 'No further detail was recorded.' },
};

function describeErrorType(errorType) {
    return ERROR_TYPE_INFO[errorType] || { label: errorType || 'Failed', hint: '' };
}

function formatDuration(seconds) {
    if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return null;
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
}

/**
 * FailedJobsPanel — user-facing failure diagnostics with a retry action.
 *
 * Explains *why* recent jobs failed (cause, provider, model, attempts,
 * duration) and offers one-click retry, plus a queue recovery action for jobs
 * wedged by a restart or a dead worker. Renders nothing when no job has failed,
 * so it costs no space on a healthy instance.
 */
export default function FailedJobsPanel({ limit = 5 }) {
    const [isCollapsed, setIsCollapsed] = useState(false);
    const [expandedJobId, setExpandedJobId] = useState(null);

    const {
        jobs,
        total,
        summary,
        isLoading,
        retryJob,
        recoverJobs,
        isRetrying,
        retryingJobId,
        isRecovering,
    } = useJobRecovery({ limit });

    const errorTypeEntries = useMemo(
        () => Object.entries(summary?.by_error_type || {}).sort((a, b) => b[1] - a[1]),
        [summary]
    );

    if (isLoading || jobs.length === 0) return null;

    const handleRetry = async (jobId) => {
        try {
            await retryJob(jobId);
            toast.success('Retry queued', { icon: '🔁' });
        } catch (error) {
            toast.error(error?.message || 'Failed to retry job');
        }
    };

    const handleRecover = async () => {
        try {
            const result = await recoverJobs();
            const recovered = result?.recovered ?? 0;
            const failed = result?.failed ?? 0;
            toast.success(
                `Queue recovered: ${recovered} requeued, ${failed} failed as stale`,
                { icon: '🛠️' }
            );
        } catch (error) {
            toast.error(error?.message || 'Failed to recover queue');
        }
    };

    return (
        <section
            aria-label="Failed jobs"
            className="glass-panel rounded-2xl overflow-hidden mb-4 border border-red-500/20 shadow-xl"
        >
            <div className="flex items-stretch">
                <button
                    onClick={() => setIsCollapsed((prev) => !prev)}
                    aria-expanded={!isCollapsed}
                    className="flex-1 px-5 py-4 flex items-center justify-between hover:bg-white/5 transition-colors text-left"
                >
                    <div className="flex items-center gap-3 flex-wrap">
                        <AlertTriangle className="text-red-400" size={18} aria-hidden="true" />
                        <span className="font-semibold text-white tracking-wide">
                            Failed jobs{' '}
                            <span className="text-gray-400 font-normal">
                                ({total > jobs.length ? `${jobs.length} of ${total}` : total})
                            </span>
                        </span>
                        {errorTypeEntries.map(([errorType, count]) => (
                            <span
                                key={errorType}
                                className="text-[10px] text-red-300 bg-red-500/10 px-2 py-0.5 rounded-full font-bold uppercase tracking-wider border border-red-400/20"
                            >
                                {describeErrorType(errorType).label} · {count}
                            </span>
                        ))}
                    </div>
                    {isCollapsed ? (
                        <ChevronDown size={18} className="text-gray-400" aria-hidden="true" />
                    ) : (
                        <ChevronUp size={18} className="text-gray-400" aria-hidden="true" />
                    )}
                </button>

                <button
                    onClick={handleRecover}
                    disabled={isRecovering}
                    aria-label="Recover stuck jobs and requeue interrupted work"
                    className="px-4 border-l border-white/5 text-gray-300 hover:text-white hover:bg-white/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 text-sm"
                >
                    <LifeBuoy size={16} aria-hidden="true" />
                    <span className="hidden sm:inline">Recover</span>
                </button>
            </div>

            {!isCollapsed && (
                <ul className="px-5 pb-5 space-y-2">
                    {jobs.map((job) => {
                        const diagnostics = job.diagnostics || {};
                        const errorType = diagnostics.error_type;
                        const info = describeErrorType(errorType);
                        const provider = getProviderDisplayName(job.provider_id) || job.provider_id;
                        const duration = formatDuration(diagnostics.duration_seconds);
                        const attempts = Array.isArray(diagnostics.attempts) ? diagnostics.attempts : [];
                        const isExpanded = expandedJobId === job.id;
                        const canRetry = diagnostics.is_retryable !== false && diagnostics.failure_kind !== 'cancelled';
                        const isThisRetrying = isRetrying && retryingJobId === job.id;
                        const prompt = (job.metadata || job.metadata_ || {}).prompt;

                        return (
                            <li
                                key={job.id}
                                className="rounded-xl border border-red-500/20 bg-red-500/5 p-3 space-y-2"
                            >
                                <div className="flex items-start justify-between gap-3 flex-wrap">
                                    <div className="min-w-0 flex-1">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-red-500/20 text-red-300 border border-red-400/30">
                                                {info.label}
                                            </span>
                                            {provider && (
                                                <span className="px-2 py-0.5 rounded text-[10px] bg-purple-500/20 text-purple-300 border border-purple-400/30 flex items-center gap-1">
                                                    <Server size={10} aria-hidden="true" />
                                                    {provider}
                                                </span>
                                            )}
                                            {diagnostics.model && (
                                                <span
                                                    className="px-2 py-0.5 rounded text-[10px] bg-gray-700/60 text-gray-300 border border-gray-600 truncate max-w-[12rem]"
                                                    title={diagnostics.model}
                                                >
                                                    {diagnostics.model.replace('.safetensors', '')}
                                                </span>
                                            )}
                                            {duration && (
                                                <span className="px-2 py-0.5 rounded text-[10px] bg-gray-700/60 text-gray-300 border border-gray-600 flex items-center gap-1">
                                                    <Timer size={10} aria-hidden="true" />
                                                    {duration}
                                                </span>
                                            )}
                                        </div>

                                        <p className="text-sm text-red-300 break-words mt-1">
                                            {job.error || job.message || 'No error detail recorded'}
                                        </p>
                                        {info.hint && (
                                            <p className="text-xs text-gray-500 mt-0.5">{info.hint}</p>
                                        )}
                                        {prompt && (
                                            <p className="text-xs text-gray-500 truncate mt-1" title={prompt}>
                                                {prompt}
                                            </p>
                                        )}
                                        <p className="text-[10px] text-gray-600 mt-1">
                                            {diagnostics.attempt_count > 0
                                                ? `${diagnostics.attempt_count} attempt${diagnostics.attempt_count === 1 ? '' : 's'}`
                                                : 'No attempt history'}
                                            {diagnostics.retry_of ? ' · retry' : ''}
                                            {job.completed_at ? ` · ${formatTimestamp(job.completed_at)}` : ''}
                                        </p>
                                    </div>

                                    <div className="flex items-center gap-2 flex-shrink-0">
                                        {attempts.length > 0 && (
                                            <button
                                                onClick={() =>
                                                    setExpandedJobId(isExpanded ? null : job.id)
                                                }
                                                aria-expanded={isExpanded}
                                                aria-label={`Toggle attempt history for job ${job.id}`}
                                                className="p-2 rounded-lg bg-gray-700/60 hover:bg-gray-600 text-gray-300 transition-colors"
                                            >
                                                {isExpanded ? (
                                                    <ChevronUp size={14} aria-hidden="true" />
                                                ) : (
                                                    <ChevronDown size={14} aria-hidden="true" />
                                                )}
                                            </button>
                                        )}
                                        <button
                                            onClick={() => handleRetry(job.id)}
                                            disabled={!canRetry || isThisRetrying}
                                            aria-label={`Retry failed job ${job.id}`}
                                            title={canRetry ? 'Retry this job' : 'This job cannot be retried'}
                                            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                        >
                                            <RefreshCw
                                                size={14}
                                                className={isThisRetrying ? 'animate-spin' : ''}
                                                aria-hidden="true"
                                            />
                                            Retry
                                        </button>
                                    </div>
                                </div>

                                {isExpanded && attempts.length > 0 && (
                                    <ol className="text-xs space-y-1 border-t border-red-500/10 pt-2">
                                        {attempts.map((attempt, index) => (
                                            <li
                                                key={`${job.id}-attempt-${index}`}
                                                className="flex items-center gap-2 text-gray-400"
                                            >
                                                <span className="text-gray-600">#{index + 1}</span>
                                                <span className="text-gray-300">
                                                    {getProviderDisplayName(attempt.provider_id) ||
                                                        attempt.provider_id ||
                                                        'unassigned'}
                                                </span>
                                                <span className="text-gray-500">{attempt.outcome}</span>
                                                {formatDuration(attempt.duration_seconds) && (
                                                    <span className="text-gray-600">
                                                        {formatDuration(attempt.duration_seconds)}
                                                    </span>
                                                )}
                                                {attempt.error && (
                                                    <span className="text-red-400/80 truncate">
                                                        — {attempt.error}
                                                    </span>
                                                )}
                                            </li>
                                        ))}
                                    </ol>
                                )}
                            </li>
                        );
                    })}
                </ul>
            )}

            {jobs.length === 0 && !isLoading && (
                <p className="px-5 pb-4 text-sm text-gray-500 flex items-center gap-2">
                    <X size={14} aria-hidden="true" /> No failed jobs.
                </p>
            )}
        </section>
    );
}
