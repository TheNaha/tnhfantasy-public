import { getProviderDisplayName } from '../../utils/providerUtils';

/**
 * Failure grouping for the gallery's failed-job panel.
 *
 * The failed-jobs query returns one row per job, so a single upstream outage
 * arrives as N visually identical cards ("providers exhausted / llm-local"),
 * differing only by a duration badge. Grouping collapses those into one row
 * per cause while keeping every job reachable underneath it.
 *
 * The grouping key is `diagnostics.error_type` plus the job's provider:
 *
 *  - `error_type` is the backend's own failure classification. It is produced
 *    by `build_job_diagnostics` as the stored `failure_kind`, falling back to
 *    `classify_job_error(error)`, so it is populated for every failed job and
 *    never null. It is also the field `summarize_failed_jobs` already counts
 *    by_error_type on, so the panel header and these groups agree by
 *    construction.
 *  - the provider is the last provider attempted, written to `jobs.provider_id`
 *    when the job fails. Two jobs that exhausted *different* providers did not
 *    fail for the same actionable reason, so merging them would be misleading.
 *
 * Deliberately NOT part of the key: `duration_seconds`, `model`, `prompt`,
 * `attempt_count` and timestamps. Those differ per job even when the cause is
 * identical — the 7s/7s/8s badges in the original report — so including them
 * would put every job in its own group and change nothing.
 */

const UNASSIGNED_PROVIDER = '(unassigned)';

/**
 * Human-readable labels + guidance for the `diagnostics.error_type` values the
 * backend records. Anything unmapped falls back to the raw value so new server
 * side kinds still render instead of disappearing.
 */
export const ERROR_TYPE_INFO = {
    no_providers: { label: 'No providers', hint: 'No enabled provider can run this workflow.' },
    providers_exhausted: { label: 'Providers exhausted', hint: 'Every provider was tried and failed.' },
    provider_error: { label: 'Provider error', hint: 'The provider rejected or crashed on this job.' },
    provider_unavailable: { label: 'Provider unavailable', hint: 'The provider was not reachable for this job.' },
    timeout: { label: 'Timed out', hint: 'The provider did not answer in time.' },
    stale_recovery: { label: 'Interrupted', hint: 'A restart or dead worker left this job running.' },
    finalization_failed: { label: 'Post-processing failed', hint: 'Output was produced but saving it failed.' },
    unexpected: { label: 'Unexpected error', hint: 'The job runner hit an unhandled error.' },
    cancelled: { label: 'Cancelled', hint: 'The job was cancelled.' },
    unknown: { label: 'Failed', hint: 'No further detail was recorded.' },
};

export function describeErrorType(errorType) {
    return ERROR_TYPE_INFO[errorType] || { label: errorType || 'Failed', hint: '' };
}

export function formatDuration(seconds) {
    if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return null;
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
}

/** Singular/plural job count used in the group headline. */
export function describeGroupSize(count) {
    return `${count} job${count === 1 ? '' : 's'} failed`;
}

/**
 * Group failed jobs by cause + provider, newest first.
 *
 * Groups are ordered by size (largest outage first) and, for equal sizes, by
 * first appearance, which is the backend's newest-first job order. Jobs keep
 * that order inside each group, so the most recent failure of a cause is the
 * first one listed.
 *
 * @param {Array<object>} jobs Serialized failed jobs from `useJobRecovery`
 * @returns {Array<{key: string, errorType: string, label: string, hint: string,
 *   providerId: string|null, providerLabel: string, count: number,
 *   jobs: Array<object>}>}
 */
export function groupFailedJobs(jobs) {
    const groups = new Map();
    const list = Array.isArray(jobs) ? jobs : [];

    list.forEach((job, index) => {
        if (!job) return;

        const diagnostics = job.diagnostics || {};
        const errorType = diagnostics.error_type || 'unknown';
        const providerId = job.provider_id || diagnostics.last_provider_id || null;
        const key = `${errorType}::${providerId || UNASSIGNED_PROVIDER}`;

        let group = groups.get(key);
        if (!group) {
            const info = describeErrorType(errorType);
            group = {
                key,
                errorType,
                label: info.label,
                hint: info.hint,
                providerId,
                providerLabel: getProviderDisplayName(providerId) || providerId || 'unassigned',
                firstIndex: index,
                jobs: [],
            };
            groups.set(key, group);
        }
        group.jobs.push(job);
    });

    return [...groups.values()]
        .map((group) => ({ ...group, count: group.jobs.length }))
        .sort((a, b) => b.count - a.count || a.firstIndex - b.firstIndex);
}
