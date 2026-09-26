/**
 * Canonical job status vocabulary — the single source of truth for the
 * frontend.
 *
 * These values are the *wire* values: `JobStatus` in
 * `backend_v2/core/entities.py` has no `values_callable`, so SQLAlchemy stores
 * the enum NAME (`SENT_TO_PROVIDER`) in the DB, but every serializer emits
 * `job.status.value` (hyphenated). The frontend therefore only ever sees the
 * hyphenated spellings.
 *
 * This file exists because the list was previously copied into five places
 * (useChats.js, JobCard.jsx, JobDetailsModal.jsx, ChatContextPanel.jsx and
 * chats.py on the backend) and had already drifted: three of the copies used
 * snake_case for the multi-word statuses, so they could never match, which made
 * the chat jobs panel stop polling mid-job and print raw enum values.
 *
 * `jobStatusVocabulary.test.js` pins this list against the backend enum, so a
 * change to `JobStatus` fails CI on both sides instead of drifting.
 */

export const JOB_STATUS = Object.freeze({
    PENDING: 'pending',
    RETRYING: 'retrying',
    SENT_TO_PROVIDER: 'sent-to-provider',
    CONNECTED: 'connected',
    PRE_GENERATION: 'pre-generation',
    GENERATING: 'generating',
    COMPLETED: 'completed',
    POST_PROCESSING: 'post-processing',
    FAILED: 'failed',
    CANCELLED: 'cancelled',
});

export const JOB_STATUSES = Object.freeze(Object.values(JOB_STATUS));

/**
 * Every status a job can be in that is NOT finished. This is deliberately
 * *not* the same set as `ACTIVE_JOB_STATUSES` in
 * `backend_v2/services/job_service.py`, which means "a worker has picked this
 * job up" and so excludes PENDING. A poller wants the opposite: a PENDING job
 * is still unfinished and will progress, so it must keep being polled.
 */
export const UNFINISHED_JOB_STATUSES = Object.freeze([
    JOB_STATUS.PENDING,
    JOB_STATUS.RETRYING,
    JOB_STATUS.SENT_TO_PROVIDER,
    JOB_STATUS.CONNECTED,
    JOB_STATUS.PRE_GENERATION,
    JOB_STATUS.GENERATING,
    JOB_STATUS.POST_PROCESSING,
]);

/** Mirrors `TERMINAL_JOB_STATUSES` in `backend_v2/services/job_service.py`. */
export const TERMINAL_JOB_STATUSES = Object.freeze([
    JOB_STATUS.COMPLETED,
    JOB_STATUS.FAILED,
    JOB_STATUS.CANCELLED,
]);

/** Canonical display order for the phases a job passes through. */
export const JOB_PHASE_ORDER = Object.freeze([
    JOB_STATUS.PENDING,
    JOB_STATUS.RETRYING,
    JOB_STATUS.SENT_TO_PROVIDER,
    JOB_STATUS.CONNECTED,
    JOB_STATUS.PRE_GENERATION,
    JOB_STATUS.GENERATING,
    JOB_STATUS.POST_PROCESSING,
]);

export function isActiveJobStatus(status) {
    return UNFINISHED_JOB_STATUSES.includes(status);
}

export function isTerminalJobStatus(status) {
    return TERMINAL_JOB_STATUSES.includes(status);
}

/** True while the job is neither finished nor failed. */
export function isJobRunning(status) {
    return isActiveJobStatus(status);
}

/** True when a job ended badly, including the legacy `error` spelling. */
export function isJobFailed(status) {
    return status === JOB_STATUS.FAILED || status === 'error';
}

export function isJobCancelled(status) {
    return status === JOB_STATUS.CANCELLED;
}

export function isJobComplete(status) {
    return status === JOB_STATUS.COMPLETED;
}
