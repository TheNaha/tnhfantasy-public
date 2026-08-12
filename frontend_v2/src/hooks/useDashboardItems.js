import { useCallback, useEffect, useMemo, useReducer } from 'react';

import { buildDashboardItems } from '../utils/dashboardItems';
import { getItemTimelineDate, getLocalDateKey } from '../utils/dateTime';

const MAX_JOB_TIMELINE_ANCHORS = 1000;

function getJobTimelineAnchor(job) {
    return job?.created_at || job?.updated_at || 0;
}

function buildJobTimelineOverrides(previousAnchors, activeJobs = []) {
    const nextAnchors = new Map(previousAnchors);

    (activeJobs || []).forEach((job) => {
        if (!job?.id || nextAnchors.has(job.id)) {
            return;
        }

        nextAnchors.set(job.id, getJobTimelineAnchor(job));
    });

    if (nextAnchors.size > MAX_JOB_TIMELINE_ANCHORS) {
        const toTrim = nextAnchors.size - MAX_JOB_TIMELINE_ANCHORS;
        const iterator = nextAnchors.keys();
        for (let index = 0; index < toTrim; index += 1) {
            const nextKey = iterator.next();
            if (nextKey.done) break;
            nextAnchors.delete(nextKey.value);
        }
    }

    return nextAnchors;
}

function areMapsEqual(left, right) {
    if (left.size !== right.size) {
        return false;
    }

    for (const [key, value] of left.entries()) {
        if (right.get(key) !== value) {
            return false;
        }
    }

    return true;
}

export function useDashboardItems({
    data,
    activeJobs,
    selectedJobId,
    activeCollection,
    collections,
    showFavorites,
    favorites,
    sort = 'date_desc',
}) {
    const [jobTimelineOverrides, updateJobTimelineOverrides] = useReducer(
        (currentAnchors, nextJobs) => {
            const nextAnchors = buildJobTimelineOverrides(currentAnchors, nextJobs);
            return areMapsEqual(currentAnchors, nextAnchors) ? currentAnchors : nextAnchors;
        },
        activeJobs,
        (initialJobs) => buildJobTimelineOverrides(new Map(), initialJobs),
    );

    useEffect(() => {
        updateJobTimelineOverrides(activeJobs);
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
        if (sort === 'random') {
            return [['Random', displayedItems]];
        }
        
        return Object.entries(grouped)
            .sort(([dateA], [dateB]) => {
                const diff = new Date(dateB).getTime() - new Date(dateA).getTime();
                return sort === 'date_asc' ? -diff : diff;
            })
            .map(([date, groupItems]) => {
                const sortedItems = groupItems.slice().sort((left, right) => {
                    const diff = getItemTimelineDate(right) - getItemTimelineDate(left);
                    return sort === 'date_asc' ? -diff : diff;
                });
                return [date, sortedItems];
            });
    }, [grouped, sort, displayedItems]);

    const formatDateLabel = useCallback((localDateKey) => {
        if (localDateKey === 'Random') {
            return 'Random Order';
        }
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
