import { memo } from 'react';
import { Loader2 } from 'lucide-react';

import EmptyState from '../EmptyState';
import { QueryErrorState } from '../common/QueryState';
import { TimelineView } from './TimelineView';
import GroupedDashboardContent from './GroupedDashboardContent';
import useSettingsStore from '../../store/settingsStore';

/**
 * DashboardGalleryGrid Component
 * @param {object} props
 * @param {boolean} props.isLoading - Whether gallery is loading initial page
 * @param {string} props.viewMode - Current view mode ('grid', 'list', 'feed', 'timeline')
 * @param {array} props.displayedItems - Flattened or filtered gallery items currently displayed
 * @param {boolean} props.showFavorites - Whether showFavorites filter is active
 * @param {string|null} props.activeCollection - ID of active collection, or null
 * @param {object} props.filters - Active filter query state
 * @param {() => void} props.onClearFilters - Callback to reset active filters/views
 * @param {array} props.allItems - Unfiltered / all items to check if user has any generations
 * 
 * @param {(image: object) => void} props.onImageClick - Click handler for images
 * @param {(jobId: string) => void} props.onJobClick - Click handler for jobs
 * @param {boolean} props.selectionMode - Selection mode flag
 * @param {Set<string>} props.selectedFiles - Set of selected file names
 * @param {(filename: string) => void} props.onToggleSelection - Callback to toggle selection of a file
 * @param {(filename: string) => boolean} props.isFavorite - Utility to check if a file is favorite
 * @param {(filename: string) => void} props.onToggleFavorite - Callback to toggle favorite state
 * 
 * @param {array} props.sortedGroupedEntries - Chronologically grouped entries for grid/list/feed
 * @param {(dateStr: string) => string} props.formatDateLabel - Function to format date headers
 * @param {number} props.gridCols - Grid column count
 * @param {(filename: string) => Promise<void>} props.onDelete - Callback to delete an image file
 * @param {(jobId: string) => Promise<void>} props.onJobDelete - Callback to delete a job record
 * 
 * @param {React.RefObject} props.sentinelRef - React Ref for infinite scrolling scroll sentinel
 * @param {boolean} props.isFetchingNextPage - Whether next page is being fetched
 * @param {boolean} props.isRefreshing - Whether a background refetch is in flight
 *
 * Memoised, and the memo holds: every prop is either a primitive, a ref, a
 * `Set` held in state, or one of `useDashboardItems`/`useDashboardModals`/
 * `useDashboardSelection`'s `useMemo`/`useCallback` outputs. `Dashboard` itself
 * re-renders on every job-progress websocket frame, on every settings-store
 * write and on every keystroke in the filter panel, and each of those used to
 * re-render the whole gallery subtree — the most expensive thing on the page.
 * A memo that did not hold would be worse than none (a wasted shallow prop
 * comparison plus a false sense of safety), so `Dashboard.galleryGridProps`
 * pins the referential stability this depends on.
 */
export default memo(function DashboardGalleryGrid({
    isLoading,
    isError,
    error,
    onRetry,
    viewMode,
    displayedItems,
    showFavorites,
    activeCollection,
    filters,
    onClearFilters,
    allItems,

    onImageClick,
    onJobClick,
    selectionMode,
    selectedFiles,
    onToggleSelection,
    isFavorite,
    onToggleFavorite,

    sortedGroupedEntries,
    formatDateLabel,
    gridCols,
    onDelete,
    onJobDelete,
    onQuickReuse,
    sentinelRef,
    isFetchingNextPage,
    isRefreshing,
}) {
    // Settings > Gallery > "Silent Refresh": a background refetch (job
    // completion, reconnect) leaves the already-rendered grid alone, so the
    // indicator is only worth showing when the user turned this off.
    const silentRefresh = useSettingsStore((s) => s.settings?.gallery?.silentRefresh);

    if (isLoading) {
        return (
            <div className="flex justify-center items-center h-64">
                <Loader2 className="animate-spin text-blue-500" size={32} />
            </div>
        );
    }

    // A failed fetch produces zero items, so every `length === 0` check below
    // is satisfied by an outage. This is the one place that has to know it: the
    // grid is handed a flat array with no provenance, so "the library is empty"
    // and "the library could not be reached" are the same value unless the
    // query says otherwise. Checked before the empty state, and stated as a
    // failure with a retry, never as emptiness.
    //
    // Gated on emptiness too, deliberately. A background page failing is not a
    // reason to destroy the pages already on screen — and a query that loaded,
    // then failed to refresh, leaves `isError` true with real items still
    // displayed. The failure is only total when it produced nothing.
    if (isError && displayedItems.length === 0) {
        return <QueryErrorState noun="images" error={error} onRetry={onRetry} />;
    }

    if (displayedItems.length === 0) {
        return (
            <>
                <EmptyState
                    type={
                        showFavorites ? 'favorites' :
                            activeCollection ? 'collection' :
                                filters.search ? 'search' :
                                    'gallery'
                    }
                    primaryLabel={
                        activeCollection ? 'Back to All Images' : undefined
                    }
                    onAction={onClearFilters}
                    showTutorialHint={!showFavorites && !activeCollection && allItems.length === 0}
                />
                <div ref={sentinelRef} className="h-4" />
                {isFetchingNextPage && (
                    <div className="flex justify-center py-8">
                        <Loader2 className="animate-spin text-gray-400" size={32} />
                    </div>
                )}
            </>
        );
    }

    return (
        <>
            {viewMode === 'timeline' ? (
                <TimelineView
                    items={displayedItems}
                    sort={filters.sort}
                    onImageClick={onImageClick}
                    onJobClick={onJobClick}
                    selectionMode={selectionMode}
                    selectedFiles={selectedFiles}
                    onToggleSelection={onToggleSelection}
                    isFavorite={isFavorite}
                    onToggleFavorite={onToggleFavorite}
                />
            ) : (
                <GroupedDashboardContent
                    viewMode={viewMode}
                    sortedGroupedEntries={sortedGroupedEntries}
                    formatDateLabel={formatDateLabel}
                    gridCols={gridCols}
                    selectedFiles={selectedFiles}
                    selectionMode={selectionMode}
                    handleJobClick={onJobClick}
                    handleImageClick={onImageClick}
                    toggleSelection={onToggleSelection}
                    isFavorite={isFavorite}
                    handleToggleFavorite={onToggleFavorite}
                    handleDelete={onDelete}
                    handleJobDelete={onJobDelete}
                    onQuickReuse={onQuickReuse}
                />
            )}

            <div ref={sentinelRef} className="h-4" />

            {isFetchingNextPage && (
                <div className="flex justify-center py-8">
                    <Loader2 className="animate-spin text-gray-400" size={32} />
                </div>
            )}

            {isRefreshing && !silentRefresh && (
                <div data-testid="gallery-refreshing" className="flex justify-center items-center gap-2 py-2 text-xs text-gray-500">
                    <Loader2 className="animate-spin" size={12} /> Refreshing…
                </div>
            )}
        </>
    );
});
