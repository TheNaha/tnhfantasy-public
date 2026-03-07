export const ACTIVE_JOB_STATUSES = new Set([
    'pending',
    'running',
    'processing',
    'executing',
    'progress',
    'queued',
    'post-processing',
    'post_processing',
    'submitting',
]);

export function isActiveJobStatus(status) {
    return ACTIVE_JOB_STATUSES.has(status);
}

export function filterActiveJobs(jobs = []) {
    return jobs.filter((job) => isActiveJobStatus(job.status));
}

export function filterHistoricalJobs(jobs = []) {
    return jobs.filter((job) => !isActiveJobStatus(job.status));
}