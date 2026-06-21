export const ACTIVE_JOB_STATUSES = new Set([
    'pending',
    'sent-to-provider',
    'connected',
    'pre-generation',
    'generating',
    'post-processing',
    'post_processing',
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