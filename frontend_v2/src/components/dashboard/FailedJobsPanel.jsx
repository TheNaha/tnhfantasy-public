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
import { describeErrorType, describeGroupSize, formatDuration, groupFailedJobs } from '../gallery/groupFailedJobs';

/**
 * The expanded group list is capped so no number of failures can push the
 * gallery grid off the first screen. The list scrolls inside the cap.
 */
const GROUP_LIST_MAX_HEIGHT = 'max-h-[40vh]';

/**
 * FailedJobsPanel — user-facing failure diagnostics with a retry action.
 *
 * Explains *why* recent jobs failed (cause, provider, model, attempts,
 * duration) and offers one-click retry, plus a queue recovery action for jobs
 * wedged by a restart or a dead worker. Renders nothing when no job has failed,
 * so it costs no space on a healthy instance.
 *
 * Two bounds keep it from becoming the page: failures are grouped by cause so
 * one outage is one row rather than N identical cards, and the whole body
 * starts collapsed behind a header that still carries the cause summary and
 * the Recover action.
 */
export default function FailedJobsPanel({ limit = 5 }) {
    const [isCollapsed, setIsCollapsed] = useState(true);
    const [expandedGroupKeys, setExpandedGroupKeys] = useState(() => new Set());
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

    const groups = useMemo(() => groupFailedJobs(jobs), [jobs]);

    if (isLoading || jobs.length === 0) return null;

    const toggleGroup = (key) => {
        setExpandedGroupKeys((prev) => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    };

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
                                className="text-xs text-red-300 bg-red-500/10 px-2 py-0.5 rounded-full font-bold uppercase tracking-wider border border-red-400/20"
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
                <div className={`px-5 pb-5 ${GROUP_LIST_MAX_HEIGHT} overflow-y-auto`}>
                    <ul className="space-y-2">
                        {groups.map((group) => {
                            // A group of one has nothing to fold away, so it
                            // renders its detail without an extra click.
                            const isGroupOpen =
                                group.count === 1 || expandedGroupKeys.has(group.key);

                            return (
                                <li
                                    key={group.key}
                                    className="rounded-xl border border-red-500/20 bg-red-500/5"
                                >
                                    <div className="flex items-start justify-between gap-3 flex-wrap p-3">
                                        <div className="min-w-0 flex-1">
                                            <div className="flex items-center gap-2 flex-wrap">
                                                <span className="px-2 py-0.5 rounded text-xs font-bold uppercase tracking-wider bg-red-500/20 text-red-300 border border-red-400/30">
                                                    {group.label}
                                                </span>
                                                <span className="px-2 py-0.5 rounded text-xs bg-purple-500/20 text-purple-300 border border-purple-400/30 flex items-center gap-1">
                                                    <Server size={10} aria-hidden="true" />
                                                    {group.providerLabel}
                                                </span>
                                            </div>
                                            <p className="text-sm text-red-300 break-words mt-1">
                                                {describeGroupSize(group.count)}
                                                {group.hint ? ` — ${group.hint}` : ''}
                                            </p>
                                        </div>

                                        {group.count > 1 && (
                                            <button
                                                onClick={() => toggleGroup(group.key)}
                                                aria-expanded={isGroupOpen}
                                                aria-label={`${isGroupOpen ? 'Hide' : 'Show'} the ${group.count} jobs that failed on ${group.providerLabel}`}
                                                className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-gray-700/60 hover:bg-gray-600 text-gray-200 text-sm font-medium transition-colors flex-shrink-0"
                                            >
                                                {isGroupOpen ? (
                                                    <ChevronUp size={14} aria-hidden="true" />
                                                ) : (
                                                    <ChevronDown size={14} aria-hidden="true" />
                                                )}
                                                {isGroupOpen ? 'Hide' : 'Show'} jobs
                                            </button>
                                        )}
                                    </div>

                                    {isGroupOpen && (
                                        <ul className="px-3 pb-3 space-y-2">
                                            {group.jobs.map((job) => (
                                                <FailedJobCard
                                                    key={job.id}
                                                    job={job}
                                                    onRetry={handleRetry}
                                                    isRetrying={isRetrying}
                                                    retryingJobId={retryingJobId}
                                                    expandedJobId={expandedJobId}
                                                    onToggleAttempts={setExpandedJobId}
                                                />
                                            ))}
                                        </ul>
                                    )}
                                </li>
                            );
                        })}
                    </ul>
                </div>
            )}

            {jobs.length === 0 && !isLoading && (
                <p className="px-5 pb-4 text-sm text-gray-500 flex items-center gap-2">
                    <X size={14} aria-hidden="true" /> No failed jobs.
                </p>
            )}
        </section>
    );
}

/**
 * One failed job inside a group. The cause and provider live on the group
 * header, so this carries only what is unique to the job: its error, model,
 * duration, prompt, attempt count and timestamp.
 */
function FailedJobCard({
    job,
    onRetry,
    isRetrying,
    retryingJobId,
    expandedJobId,
    onToggleAttempts,
}) {
    const diagnostics = job.diagnostics || {};
    const duration = formatDuration(diagnostics.duration_seconds);
    const attempts = Array.isArray(diagnostics.attempts) ? diagnostics.attempts : [];
    const isExpanded = expandedJobId === job.id;
    const canRetry = diagnostics.is_retryable !== false && diagnostics.failure_kind !== 'cancelled';
    const isThisRetrying = isRetrying && retryingJobId === job.id;
    const prompt = (job.metadata || job.metadata_ || {}).prompt;

    return (
        <li className="rounded-lg border border-red-500/15 bg-gray-900/40 p-3 space-y-2">
            <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        {diagnostics.model && (
                            <span
                                className="px-2 py-0.5 rounded text-xs bg-gray-700/60 text-gray-300 border border-gray-600 truncate max-w-[12rem]"
                                title={diagnostics.model}
                            >
                                {diagnostics.model.replace('.safetensors', '')}
                            </span>
                        )}
                        {duration && (
                            <span className="px-2 py-0.5 rounded text-xs bg-gray-700/60 text-gray-300 border border-gray-600 flex items-center gap-1">
                                <Timer size={10} aria-hidden="true" />
                                {duration}
                            </span>
                        )}
                    </div>

                    <p className="text-sm text-red-300 break-words mt-1">
                        {job.error || job.message || 'No error detail recorded'}
                    </p>
                    {prompt && (
                        <p className="text-xs text-gray-500 truncate mt-1" title={prompt}>
                            {prompt}
                        </p>
                    )}
                    <p className="text-xs text-gray-600 mt-1">
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
                            onClick={() => onToggleAttempts(isExpanded ? null : job.id)}
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
                        onClick={() => onRetry(job.id)}
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
                                <span className="text-red-400/80 truncate">— {attempt.error}</span>
                            )}
                        </li>
                    ))}
                </ol>
            )}
        </li>
    );
}
