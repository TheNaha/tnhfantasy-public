import { useCallback, useMemo } from 'react';

import { buildDashboardItems } from '../utils/dashboardItems';
import { getItemTimelineDate, getLocalDateKey } from '../utils/dateTime';

export function useDashboardItems({
    data,
    activeJobs,
    selectedJobId,
    activeCollection,
    collections,
    showFavorites,
    favorites,
}) {
    const { items: allItems, jobsById } = useMemo(() => {
        return buildDashboardItems(data, activeJobs);
    }, [data, activeJobs]);

    const selectedJob = useMemo(() => {
        return selectedJobId ? jobsById.get(selectedJobId) || null : null;
    }, [jobsById, selectedJobId]);

    const displayedItems = useMemo(() => {
        let items = allItems;

        if (activeCollection && collections[activeCollection]) {
            const collectionImages = collections[activeCollection].images;
            items = items.filter((item) => item.type === 'image' && collectionImages.includes(item.name));
        }

        if (showFavorites) {
            items = items.filter((item) => item.type === 'image' && favorites.includes(item.name));
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