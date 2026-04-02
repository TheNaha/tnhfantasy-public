import { useCallback, useMemo, useRef } from 'react';

import { buildDashboardItems } from '../utils/dashboardItems';
import { getItemTimelineDate, getLocalDateKey } from '../utils/dateTime';

const MAX_JOB_TIMELINE_ANCHORS = 1000;

function getJobTimelineAnchor(job) {
    return job?.created_at || job?.updated_at || 0;
}

export function useDashboardItems({
    data,
    activeJobs,
    selectedJobId,
    activeCollection,
    collections,
    showFavorites,
    favorites,
}) {
    const jobTimelineAnchorsRef = useRef(new Map());

    const jobTimelineOverrides = useMemo(() => {
        const nextAnchors = new Map(jobTimelineAnchorsRef.current);

        activeJobs.forEach((job) => {
            if (!job?.id || nextAnchors.has(job.id)) {
                return;
            }

            nextAnchors.set(job.id, getJobTimelineAnchor(job));
        });

        if (nextAnchors.size > MAX_JOB_TIMELINE_ANCHORS) {
            const toTrim = nextAnchors.size - MAX_JOB_TIMELINE_ANCHORS;
            const iterator = nextAnchors.keys();
            for (let i = 0; i < toTrim; i += 1) {
                const nextKey = iterator.next();
                if (nextKey.done) break;
                nextAnchors.delete(nextKey.value);
            }
        }

        jobTimelineAnchorsRef.current = nextAnchors;
        return nextAnchors;
    }, [activeJobs]);

    const { items: allItems, jobsById } = useMemo(() => {
        return buildDashboardItems(data, activeJobs, jobTimelineOverrides);
    }, [data, activeJobs, jobTimelineOverrides]);

    const selectedJob = useMemo(() => {
        return selectedJobId ? jobsById.get(selectedJobId) || null : null;
    }, [jobsById, selectedJobId]);

    const displayedItems = useMemo(() => {
        let items = allItems;

        // ⚡ Bolt: Pre-compute Set for O(1) lookups to prevent O(N^2) complexity during filtering
        if (activeCollection && collections[activeCollection]) {
            const collectionImagesSet = new Set(collections[activeCollection].images);
            items = items.filter((item) => item.type === 'image' && collectionImagesSet.has(item.name));
        }

        if (showFavorites) {
            const favoritesSet = new Set(favorites);
            items = items.filter((item) => item.type === 'image' && favoritesSet.has(item.name));
        }

        return items;
    }, [activeCollection, allItems, collections, favorites, showFavorites]);

    const grouped = useMemo(() => {
        return displayedItems.reduce((accumulator, item) => {
            const dateKey = getLocalDateKey(getItemTimelineDate(item));
            if (!accumulator[dateKey]) {
                accumulator[dateKey] = [];
            }
            accumulator[dateKey].push(item);
            return accumulator;
        }, {});
    }, [displayedItems]);

    const sortedGroupedEntries = useMemo(() => {
        return Object.entries(grouped)
            .sort(([dateA], [dateB]) => new Date(dateB).getTime() - new Date(dateA).getTime())
            .map(([date, groupItems]) => ([
                date,
                groupItems
                    .slice()
                    .sort((left, right) => getItemTimelineDate(right) - getItemTimelineDate(left)),
            ]));
    }, [grouped]);

    const formatDateLabel = useCallback((localDateKey) => {
        const [year, month, day] = localDateKey.split('-');
        const date = new Date(year, month - 1, day);

        const today = new Date();
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);

        const todayKey = getLocalDateKey(today);
        const yesterdayKey = getLocalDateKey(yesterday);

        if (localDateKey === todayKey) {
            return 'Today';
        }
        if (localDateKey === yesterdayKey) {
            return 'Yesterday';
        }
        return date.toLocaleDateString(undefined, {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric',
        });
    }, []);

    return {
        allItems,
        displayedItems,
        selectedJob,
        sortedGroupedEntries,
        formatDateLabel,
    };
}