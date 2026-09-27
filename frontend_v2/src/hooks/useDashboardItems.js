import { useCallback, useMemo } from 'react';

import { buildDashboardItems } from '../utils/dashboardItems';
import { getItemTimelineDate, getLocalDateKey } from '../utils/dateTime';
import { assetPath } from '../utils/assetUrl';

const MAX_JOB_TIMELINE_ANCHORS = 1000;

function getJobTimelineAnchor(job) {
    return job?.created_at || job?.updated_at || 0;
}

/**
 * Anchors for jobs seen while running, keyed by job id.
 *
 * A job's `created_at` can be null (recovered jobs), and its timeline date then
 * falls back to `updated_at` — which moves on every poll, shuffling the item
 * between date groups. The first-seen anchor has to outlive the render that
 * recorded it, which is why this is module state: a ref may not be read during
 * render (`react-hooks/refs`), and a `useReducer` dispatched from an effect on
 * every `useActiveJobs()` poll re-rendered the whole Dashboard for it. The map
 * is capped at MAX_JOB_TIMELINE_ANCHORS below.
 */
const jobTimelineAnchors = new Map();

function buildJobTimelineOverrides(activeJobs = []) {
    const nextAnchors = jobTimelineAnchors;

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
    // Identity is stable: `buildJobTimelineOverrides` mutates the module map in
    // place, so the downstream memos keyed on it do not re-run per poll.
    const jobTimelineOverrides = useMemo(
        () => buildJobTimelineOverrides(activeJobs),
        [activeJobs]
    );

    const { items: allItems, jobsById } = useMemo(() => {
        return buildDashboardItems(data, activeJobs, jobTimelineOverrides, { sort });
    }, [data, activeJobs, jobTimelineOverrides, sort]);

    const selectedJob = useMemo(() => {
        return selectedJobId ? jobsById.get(selectedJobId) || null : null;
    }, [jobsById, selectedJobId]);

    const displayedItems = useMemo(() => {
        let items = allItems;

        // ⚡ Bolt: Pre-compute Set for O(1) lookups to prevent O(N^2) complexity during filtering
        if (activeCollection && collections[activeCollection]) {
            const collectionImagesSet = new Set(collections[activeCollection].images);
            items = items.filter((item) => item.type === 'image' && (
                collectionImagesSet.has(item.name) || collectionImagesSet.has(assetPath(item))
            ));
        }

        if (showFavorites) {
            const favoritesSet = new Set(favorites);
            items = items.filter((item) => item.type === 'image' && (
                favoritesSet.has(item.name) || favoritesSet.has(assetPath(item))
            ));
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
        if (sort?.startsWith('random')) {
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
