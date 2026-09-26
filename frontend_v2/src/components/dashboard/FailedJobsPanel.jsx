import { useMemo, useState } from 'react';
import {
    AlertTriangle,
    ChevronDown,
    ChevronUp,
    LifeBuoy,
    RefreshCw,
    Server,
    Timer,
    Undo2,
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

/** Singular/plural failure count for the dismiss toasts and labels. */
function describeFailures(count) {
    return `${count} failure${count === 1 ? '' : 's'}`;
}

/**
 * FailedJobsPanel — user-facing failure diagnostics with retry and dismiss.
 *
 * Explains *why* recent jobs failed (cause, provider, model, attempts,
 * duration) and offers one-click retry, a dismiss control per cause, plus a
 * queue recovery action for jobs wedged by a restart or a dead worker. Renders
 * nothing when no unacknowledged job has failed, so it costs no space on a
 * healthy instance and stops shouting once a user has read what went wrong.
 *
 * Dismissal is acknowledgement, not deletion: the job and its history stay and
 * the dismiss toast offers an Undo, so a user who has dealt with a cause can
 * hide just that cause and still get it back.
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
    // Off by default: acknowledged failures stay out of the way until asked
    // for, and the flag is part of the query key so toggling it refetches.
    const [showAcknowledged, setShowAcknowledged] = useState(false);

    const {
        jobs,
        total,
        summary,
        acknowledgedCount,
        isLoading,
        retryJob,
        recoverJobs,
        acknowledgeJob,
        unacknowledgeJob,
        acknowledgeAll,
        unacknowledgeAll,
        isRetrying,
        retryingJobId,
        isRecovering,
        isAcknowledging,
        isAcknowledgingAll,
    } = useJobRecovery({ limit, includeAcknowledged: showAcknowledged });

    const errorTypeEntries = useMemo(
        () => Object.entries(summary?.by_error_type || {}).sort((a, b) => b[1] - a[1]),
        [summary]
    );

    const groups = useMemo(() => groupFailedJobs(jobs), [jobs]);

    // The server reports how many acknowledged failures it is holding back.
    // Once they are included it reports 0, so the shown page is counted here.
    const acknowledgedInPage = useMemo(
        () => jobs.filter((job) => job.acknowledged_at).length,
        [jobs]
    );
    const acknowledgedTotal = showAcknowledged ? acknowledgedInPage : acknowledgedCount;

    // Everything dismissed. Rendering nothing here was a dead end: the "show
    // acknowledged" toggle lives inside this panel, so dismissing the last
    // failure removed the only way to get it back except the 6-second undo
    // toast. A slim bar keeps the re-entry point without bringing the panel
    // back at full size.
    if (isLoading) return null;
    if (jobs.length === 0) {
        if (acknowledgedCount === 0) return null;
        return (
            <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2">
                <span className="text-xs text-gray-500">
                    {acknowledgedCount} dismissed {acknowledgedCount === 1 ? 'failure' : 'failures'}
                </span>
                <button
                    type="button"
                    onClick={() => setShowAcknowledged(true)}
                    className="text-xs text-gray-400 hover:text-gray-200 transition-colors"
                >
                    Show dismissed
                </button>
            </div>
        );
    }

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

    /** One restore path for every undo, so a failed undo still says so. */
    const restore = async (run, message) => {
        try {
            await run();
        } catch (error) {
            toast.error(error?.message || message);
        }
    };

    /**
     * Dismissal is reversible, so every dismiss toast carries the inverse
     * action instead of leaving the user to dig the failures back out of
     * history. Same shape as the trigger-word toasts in ModelGridCard.
     */
    const toastUndoable = (message, undo, undoErrorMessage) => {
        toast(
            (t) => (
                <div className="flex flex-col gap-2">
                    <span className="font-medium">{message}</span>
                    <div className="flex gap-2">
                        <button
                            onClick={() => {
                                restore(undo, undoErrorMessage);
                                toast.dismiss(t.id);
                            }}
                            className="bg-gray-700 text-white text-xs px-2 py-1 rounded"
                        >
                            Undo
                        </button>
                        <button
                            onClick={() => toast.dismiss(t.id)}
                            className="text-gray-400 text-xs"
                        >
                            Dismiss
                        </button>
                    </div>
                </div>
            ),
            { duration: 6000, icon: '🔕' }
        );
    };

    const handleDismissGroup = async (group) => {
        const jobIds = group.jobs.map((job) => job.id);
        try {
            await Promise.all(jobIds.map((jobId) => acknowledgeJob(jobId)));
        } catch (error) {
            toast.error(error?.message || 'Failed to dismiss these failures');
            return;
        }
        toastUndoable(
            `Dismissed ${describeFailures(jobIds.length)}`,
            () => Promise.all(jobIds.map((jobId) => unacknowledgeJob(jobId))),
            'Failed to bring these failures back'
        );
    };

    const handleRestoreGroup = async (group) => {
        const jobIds = group.jobs.filter((job) => job.acknowledged_at).map((job) => job.id);
        await restore(
            () => Promise.all(jobIds.map((jobId) => unacknowledgeJob(jobId))),
            'Failed to bring these failures back'
        );
    };

    const handleDismissAll = async () => {
        let result;
        try {
            result = await acknowledgeAll();
        } catch (error) {
            toast.error(error?.message || 'Failed to dismiss failures');
            return;
        }
        // The bulk endpoint has no id list, so it covers every failure, not
        // just the page on screen; trust its count over the visible one.
        const dismissed = result?.updated ?? jobs.length;
        toastUndoable(
            `Dismissed ${describeFailures(dismissed)}`,
            () => unacknowledgeAll(),
            'Failed to bring these failures back'
        );
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
                    onClick={() => setShowAcknowledged((prev) => !prev)}
                    aria-pressed={showAcknowledged}
                    className="px-3 border-l border-white/5 text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors text-xs flex items-center"
                >
                    {showAcknowledged ? 'Hide acknowledged' : 'Show acknowledged'}
                    {acknowledgedTotal > 0 ? ` (${acknowledgedTotal})` : ''}
                </button>

                <button
                    onClick={handleDismissAll}
                    disabled={isAcknowledgingAll}
                    aria-label="Dismiss all failures without retrying them"
                    title="Dismiss every failure without retrying it — reversible from the toast or by showing acknowledged failures"
                    className="px-3 border-l border-white/5 text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 text-xs"
                >
                    <X size={14} aria-hidden="true" />
                    <span className="hidden sm:inline">Dismiss all</span>
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
                            const isGroupAcknowledged = group.jobs.every(
                                (job) => job.acknowledged_at
                            );
                            const groupSize = `${group.count} ${
                                group.count === 1 ? 'job' : 'jobs'
                            }`;

                            return (
                                <li
                                    key={group.key}
                                    className={`rounded-xl border bg-red-500/5 ${
                                        isGroupAcknowledged
                                            ? 'border-white/5 opacity-60'
                                            : 'border-red-500/20'
                                    }`}
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
                                                {isGroupAcknowledged && (
                                                    <span className="px-2 py-0.5 rounded text-xs bg-white/5 text-gray-400 border border-white/10">
                                                        Acknowledged
                                                    </span>
                                                )}
                                            </div>
                                            <p className="text-sm text-red-300 break-words mt-1">
                                                {describeGroupSize(group.count)}
                                                {group.hint ? ` — ${group.hint}` : ''}
                                            </p>
                                        </div>

                                        <div className="flex items-center gap-2 flex-shrink-0">
                                            {group.count > 1 && (
                                                <button
                                                    onClick={() => toggleGroup(group.key)}
                                                    aria-expanded={isGroupOpen}
                                                    aria-label={`${isGroupOpen ? 'Hide' : 'Show'} the ${groupSize} that failed on ${group.providerLabel}`}
                                                    className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-gray-700/60 hover:bg-gray-600 text-gray-200 text-sm font-medium transition-colors"
                                                >
                                                    {isGroupOpen ? (
                                                        <ChevronUp size={14} aria-hidden="true" />
                                                    ) : (
                                                        <ChevronDown size={14} aria-hidden="true" />
                                                    )}
                                                    {isGroupOpen ? 'Hide' : 'Show'} jobs
                                                </button>
                                            )}

                                            {/* An X on a ghost button, not a blue
                                                Retry: dismissal is housekeeping,
                                                and its label says so. */}
                                            <button
                                                onClick={() =>
                                                    isGroupAcknowledged
                                                        ? handleRestoreGroup(group)
                                                        : handleDismissGroup(group)
                                                }
                                                disabled={isAcknowledging}
                                                aria-label={
                                                    isGroupAcknowledged
                                                        ? `Show the dismissed ${groupSize} from ${group.providerLabel} again`
                                                        : `Dismiss the ${groupSize} that failed on ${group.providerLabel} without retrying ${
                                                              group.count === 1 ? 'it' : 'them'
                                                          }`
                                                }
                                                title={
                                                    isGroupAcknowledged
                                                        ? 'Show these failures in the panel again'
                                                        : 'Dismiss these failures without retrying them'
                                                }
                                                className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                            >
                                                {isGroupAcknowledged ? (
                                                    <Undo2 size={14} aria-hidden="true" />
                                                ) : (
                                                    <X size={14} aria-hidden="true" />
                                                )}
                                            </button>
                                        </div>
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
