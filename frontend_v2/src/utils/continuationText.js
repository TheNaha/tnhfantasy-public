/**
 * Join the two halves of a seamless continuation.
 *
 * Mirrors `_join_continuation_text` in
 * `backend_v2/services/world_integration_service.py`: a continuation resumes
 * mid-beat, so it must not introduce a double space or separate a punctuation
 * mark from the word it follows.
 */
export function joinContinuationText(existing, addition) {
    const left = existing || '';
    const right = addition || '';
    if (!left) return right;
    if (!right) return left;
    if (/\s$/.test(left) || /^\s/.test(right)) return left + right;
    if (/^[.,;:!?)\]}…’"]/.test(right)) return left + right;
    return `${left} ${right}`;
}

/**
 * Fold in-flight continuation streams into the messages they continue.
 *
 * A continuation job (`metadata.continuation_of_job_id`) is a second LLM pass
 * over a beat that was cut off. Rendering it as its own "X is thinking…" row
 * would duplicate the speaker and detach the prose from the reply it extends,
 * so its streamed text is appended to the parent bubble instead.
 *
 * `jobs` are the `{ jobId, jobData }` entries from `useActiveChatStreams`.
 * Returns the timeline entries plus the set of parent job ids that found a
 * bubble, which callers use to keep an unmatched continuation visible rather
 * than silently dropping it.
 */
export function buildContinuationTimeline(messages, jobs) {
    const continuationTextByParentJob = new Map();
    for (const entry of jobs || []) {
        const jobData = entry?.jobData ?? entry;
        const parentJobId = jobData?.continuationOfJobId;
        if (!parentJobId) continue;
        continuationTextByParentJob.set(parentJobId, jobData.text || '');
    }

    const parentJobIds = new Set();
    const items = (messages || []).map((msg, i) => {
        const key = msg.id || `msg-${i}`;
        const parentJobId = msg.message_metadata?.source_job_id;
        if (!parentJobId || !continuationTextByParentJob.has(parentJobId)) {
            return { _key: key, item: msg };
        }
        parentJobIds.add(parentJobId);
        return {
            _key: key,
            item: {
                ...msg,
                content: joinContinuationText(msg.content, continuationTextByParentJob.get(parentJobId)),
                continuation_streaming: true,
            },
        };
    });

    return { items, parentJobIds };
}
