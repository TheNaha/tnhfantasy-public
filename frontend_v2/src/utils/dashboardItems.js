import { getLatestDate, getItemTimelineDate } from './dateTime';

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

export function buildDashboardItems(data, activeJobs, jobTimelineOverrides = null) {
    const historicalFiles = data ? data.pages.flatMap((page) => page.files.map(toImageItem)) : [];
    const historicalJobs = data ? data.pages.flatMap((page) => (page.jobs || []).map(toJobItem)) : [];

    const mergedJobs = new Map();
    historicalJobs.forEach((job) => mergedJobs.set(job.id, job));
    activeJobs.forEach((job) => mergedJobs.set(job.id, toJobItem(job)));

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

        if (job.status !== 'completed') {
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