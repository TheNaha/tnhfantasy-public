/**
 * Which side toasts when a job reaches a terminal state.
 *
 * Two live listeners watch the same job: the global `useJobsRealtime`
 * (mounted once in App.jsx) and the page that submitted it
 * (`useGeneratorJob` on the generator). Both used to toast — "Image
 * generated! <prompt>" next to "Generation complete!" for ONE completion
 * (and the same doubling on failure/cancel).
 *
 * The page CLAIMS its job id while it is mounted and could toast itself;
 * the global handler only skips the TOAST for a claimed job. Cache
 * invalidation, gallery refresh and queue bookkeeping stay unconditional on
 * both sides — whichever listener wins a race, the UI still refreshes.
 *
 * On unmount the claim is released, so a job completing after the page has
 * navigated away falls back to the global toast (the normal
 * redirect-after-generate path).
 */

const claimed = new Set();

export function claimJobToast(jobId) {
    if (jobId) claimed.add(String(jobId));
}

export function releaseJobToast(jobId) {
    if (jobId) claimed.delete(String(jobId));
}

export function isJobToastClaimed(jobId) {
    return claimed.has(String(jobId));
}