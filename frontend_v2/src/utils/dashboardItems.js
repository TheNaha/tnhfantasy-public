import { getLatestDate, getItemTimelineDate } from './dateTime';
import { seededSort } from './seededRandom';

function getPersistedJobTimelineAnchor(image) {
    return image?.metadata?.job_timeline_anchor || image?.metadata?.job_created_at || null;
}

function resolveTimelineDate(jobId, fallbackValues = [], jobTimelineOverrides = null) {
    if (jobId && jobTimelineOverrides && typeof jobTimelineOverrides.get === 'function') {
        const anchored = jobTimelineOverrides.get(jobId);
        if (anchored !== undefined && anchored !== null && anchored !== '') {
            return anchored;
        }
    }

    for (const value of fallbackValues) {
        if (value !== undefined && value !== null && value !== '') {
            return value;
        }
    }

    return 0;
}

function toImageItem(file) {
    const persistedAnchor = file?.metadata?.job_timeline_anchor || file?.metadata?.job_created_at;
    return {
        ...file,
        type: 'image',
        date: file.date || file.mtime,
        timelineDate: persistedAnchor || file.date || file.mtime,
    };
}

function toJobItem(job) {
    return {
        ...job,
        type: 'job',
        date: job.created_at || job.updated_at || 0,
        timelineDate: job.created_at || job.updated_at || 0,
    };
}

export const UNTITLED_SESSION_NAME = 'Untitled session';

function toTimestamp(value) {
    if (value === undefined || value === null || value === '') return null;
    const parsed = typeof value === 'number' ? value : Date.parse(value);
    return Number.isNaN(parsed) ? null : parsed;
}

/**
 * The sort key for a session: `[touched, generated]`.
 *
 * `updated_at` stays primary, deliberately — a session someone just curated
 * should float to the top, and that is the intent the existing tests protect.
 *
 * It is not sufficient on its own, though. `updated_at` is a bookkeeping column
 * that moves on any write, so a library created or re-indexed in one
 * transaction gives every session the SAME value to the microsecond. Sorting on
 * it alone then falls through to the id tiebreak, and reversing the direction
 * changes nothing — which is exactly what a broken sort looks like: the control
 * moves, the order does not. (In a 1,411-session library every `updated_at` was
 * `2026-09-27T07:46:12.265488Z`.)
 *
 * So the generation window — when the images were actually made — breaks the
 * tie. It is the only ordering that stays meaningful across database
 * maintenance, and it makes the sort visibly work instead of silently not.
 */
export function getSessionSortDateParts(session) {
    const first = (values) => {
        for (const value of values) {
            const parsed = toTimestamp(value);
            if (parsed !== null) return parsed;
        }
        return 0;
    };
    return {
        touched: first([session?.updated_at, session?.created_at]),
        generated: first([session?.end_at, session?.start_at]),
    };
}

/** The primary sort key. Kept for callers that only need one number. */
export function getSessionSortDate(session) {
    return getSessionSortDateParts(session).touched;
}

/** Auto-detected rows routinely arrive unnamed; the UI needs something to show. */
export function getSessionName(session) {
    const name = typeof session?.name === 'string' ? session.name.trim() : '';
    return name || UNTITLED_SESSION_NAME;
}

/**
 * Wraps one `SessionOut` row as a dashboard item.
 *
 * A session is one unit the way an `imageGroup` is one unit, so it carries an
 * `id` (the virtualizer's item key) and a sort timestamp rather than a
 * `getLocalDateKey` bucket. `members` is deliberately absent: a session's
 * images live behind `GET /api/v2/sessions/{id}/assets`, and a list of
 * sessions must not become a fan-out of member requests.
 */
export function toSessionItem(session) {
    return {
        type: 'session',
        id: `session-${session?.id}`,
        sessionId: session?.id,
        session,
        name: getSessionName(session),
        imageCount: session?.image_count ?? 0,
        autoDetected: Boolean(session?.auto_detected),
        locked: Boolean(session?.locked),
        thumbnail: session?.thumbnail ?? null,
        description: session?.description ?? null,
        startAt: session?.start_at ?? null,
        endAt: session?.end_at ?? null,
        updatedAt: session?.updated_at ?? null,
        sortDate: getSessionSortDate(session),
        sortDateParts: getSessionSortDateParts(session),
    };
}

/**
 * Session view mode's counterpart to `sortedGroupedEntries`.
 *
 * One entry per session, each holding exactly one item, so the window
 * virtualizer measures a whole session as a single row. Sessions are ordered
 * by `updated_at desc` (ascending for `date_asc`) and never bucketed by day —
 * the date grouping belongs to the image modes, and a session that spans
 * midnight would otherwise tear in half.
 */
export function buildSessionGroupedEntries(sessions, { sort = 'date_desc' } = {}) {
    const items = (sessions || [])
        .filter((session) => session?.id)
        .map(toSessionItem);

    // The gallery's sort is an IMAGE sort, and it arrives here as one of three
    // shapes: `date_desc`, `date_asc`, or `random:<seed>`.
    //
    // The previous version collapsed all three into `sort === 'date_asc' ? 1 :
    // -1`, which meant Random silently ordered sessions by date, and did so
    // without saying so — a sort control that looks like it did something and
    // provably did not. Sessions have no natural random order, so the honest
    // answer is a real shuffle keyed on the same seed the images use: choosing
    // Random twice with the same seed gives the same order, which is what makes
    // a random sort shareable.
    const isRandom = String(sort).startsWith('random');
    const seed = isRandom ? String(sort).slice('random:'.length) : '';
    const direction = sort === 'date_asc' ? 1 : -1;

    const ordered = isRandom
        // `seededSort` is the same primitive the image grid uses for Random, so
        // the two agree: same seed, same order, and a stable one that survives a
        // re-render and a re-fetch.
        ? seededSort(items, seed, (item) => item.sessionId)
        : items.sort((left, right) => (
            (left.sortDateParts.touched - right.sortDateParts.touched) * direction
            // The tie-break, and the reason the sort works at all when every
            // session was written in the same transaction.
            || (left.sortDateParts.generated - right.sortDateParts.generated) * direction
            || String(left.sessionId).localeCompare(String(right.sessionId))
        ));

    return ordered.map((item) => [item.id, [item]]);
}

export function buildDashboardItems(data, activeJobs, jobTimelineOverrides = null, options = {}) {
    const historicalFiles = data ? data.pages.flatMap((page) => page.files.map(toImageItem)) : [];
    const historicalJobs = data ? data.pages.flatMap((page) => (page.jobs || []).map(toJobItem)) : [];

    const mergedJobs = new Map();
    historicalJobs.forEach((job) => mergedJobs.set(job.id, job));
    (activeJobs || []).forEach((job) => mergedJobs.set(job.id, toJobItem(job)));

    const imagesByJobId = new Map();
    // ⚡ Bolt: Create a hash map for O(1) image lookups by filename to prevent O(N^2) performance degradation on large galleries
    const imagesByName = new Map();

    historicalFiles.forEach((image) => {
        imagesByName.set(image.name, image);

        const jobId = image.metadata?.job_id;
        if (!jobId) {
            return;
        }

        if (!imagesByJobId.has(jobId)) {
            imagesByJobId.set(jobId, []);
        }

        imagesByJobId.get(jobId).push(image);
    });

    const combined = [];
    const usedImages = new Set();
    const usedJobIds = new Set();

    if (options.sort?.startsWith('random')) {
        // For random sort, sort each page independently so that new pages
        // from infinite scroll append at the bottom instead of re-shuffling
        // the entire accumulated list. This preserves stable ordering of
        // existing items while still providing a random layout per page.
        const seed = options.sort.split(':')[1] || 'default_random';
        const sortedFiles = [];
        if (data && data.pages) {
            for (const page of data.pages) {
                const pageFiles = (page.files || []).map(toImageItem);
                sortedFiles.push(...seededSort(pageFiles, seed));
            }
        }

        // Push active jobs first, then sorted files
        Array.from(mergedJobs.values()).forEach((job) => {
            if (job.status !== 'completed' && job.status !== 'failed' && job.status !== 'cancelled') {
                combined.push(job);
            }
        });
        sortedFiles.forEach((image) => {
            combined.push({
                ...image,
                type: 'image',
            });
        });
        return { items: combined, jobsById: mergedJobs };
    }

    Array.from(mergedJobs.values()).forEach((job) => {
        if (job.status === 'completed' && job.outputs && job.outputs.length > 0) {
            const groupedImages = imagesByJobId.get(job.id);
            const anchoredTimelineDate = resolveTimelineDate(
                job.id,
                [
                    job.created_at,
                    getPersistedJobTimelineAnchor(groupedImages?.[0]),
                    groupedImages?.[0]?.timelineDate,
                    groupedImages?.[0]?.date,
                    groupedImages?.[0]?.mtime,
                    0,
                ],
                jobTimelineOverrides
            );

            if (groupedImages && groupedImages.length > 1) {
                combined.push({
                    type: 'imageGroup',
                    images: groupedImages,
                    job,
                    date: getLatestDate([job.created_at, ...groupedImages.map((image) => image.date)]).toISOString(),
                    timelineDate: anchoredTimelineDate,
                    id: `group-${job.id}`,
                });
                groupedImages.forEach((image) => usedImages.add(image.name));
                usedJobIds.add(job.id);
                return;
            }

            if (groupedImages && groupedImages.length === 1) {
                const image = groupedImages[0];
                combined.push({
                    ...image,
                    type: 'image',
                    date: getLatestDate([job.created_at, image.date]).toISOString(),
                    timelineDate: anchoredTimelineDate,
                    _replacedJobId: job.id,
                    _job: job,
                });
                usedImages.add(image.name);
                usedJobIds.add(job.id);
                return;
            }

            const outputFilename = job.outputs[0];
            // ⚡ Bolt: Use O(1) hash map lookup instead of O(N) array find
            const matchingImage = imagesByName.get(outputFilename);
            if (matchingImage && !usedImages.has(matchingImage.name)) {
                combined.push({
                    ...matchingImage,
                    type: 'image',
                    date: getLatestDate([job.created_at, matchingImage.date]).toISOString(),
                    timelineDate: anchoredTimelineDate,
                    _replacedJobId: job.id,
                    _job: job,
                });
                usedImages.add(matchingImage.name);
            }
            return;
        }

        // Only surface in-progress jobs as cards — failed/cancelled jobs
        // (e.g. LLM failures) must not linger in the timeline.
        if (job.status !== 'completed' && job.status !== 'failed' && job.status !== 'cancelled') {
            combined.push(job);
        }
    });

    historicalFiles.forEach((image) => {
        if (usedImages.has(image.name)) {
            return;
        }

        const jobId = image.metadata?.job_id;
        if (jobId && !usedJobIds.has(jobId)) {
            const groupedImages = imagesByJobId.get(jobId);
            const anchoredTimelineDate = resolveTimelineDate(
                jobId,
                [
                    getPersistedJobTimelineAnchor(image),
                    getPersistedJobTimelineAnchor(groupedImages?.[0]),
                    image.timelineDate,
                    image.date,
                    image.mtime,
                    0,
                ],
                jobTimelineOverrides
            );

            // ⚡ Bolt: Removed O(N) `combined.find` for `existingGroup` here.
            // Since `usedJobIds` tracks all processed job IDs, if `!usedJobIds.has(jobId)` is true,
            // we are guaranteed that `group-${jobId}` does not exist in `combined`.
            if (groupedImages && groupedImages.length > 1) {
                combined.push({
                    type: 'imageGroup',
                    images: groupedImages,
                    job: null,
                    date: getLatestDate(groupedImages.map((groupedImage) => groupedImage.date)).toISOString(),
                    timelineDate: anchoredTimelineDate,
                    id: `group-${jobId}`,
                });
                groupedImages.forEach((groupedImage) => usedImages.add(groupedImage.name));
                usedJobIds.add(jobId);
            } else {
                combined.push({
                    ...image,
                    timelineDate: anchoredTimelineDate,
                    _replacedJobId: jobId,
                });
                usedImages.add(image.name);
            }
            return;
        }

        if (!jobId) {
            combined.push(image);
        }
    });

    const items = combined.sort((left, right) => getItemTimelineDate(right) - getItemTimelineDate(left));
    const jobsById = new Map(Array.from(mergedJobs.values()).map((job) => [job.id, job]));

    return { items, jobsById };
}