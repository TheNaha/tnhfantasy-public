import { Loader2 } from 'lucide-react';
import { GallerySkeleton } from '../Skeleton';
import EmptyState from '../EmptyState';
import { TimelineView } from './TimelineView';
import GroupedDashboardContent from './GroupedDashboardContent';

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
 */
export default function DashboardGalleryGrid({
    isLoading,
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

    sentinelRef,
    isFetchingNextPage,
}) {
    if (isLoading) {
        return <GallerySkeleton count={12} mode={viewMode} />;
    }

    if (displayedItems.length === 0) {
        return (
            <EmptyState
                type={
                    showFavorites ? 'favorites' :
                        activeCollection ? 'collection' :
                            (filters.search || filters.model || filters.sampler || filters.aspect_ratio) ? 'search' :
                                'gallery'
                }
                onAction={onClearFilters}
                showTutorialHint={!showFavorites && !activeCollection && allItems.length === 0}
            />
        );
    }

    return (
        <>
            {viewMode === 'timeline' ? (
                <TimelineView
                    items={displayedItems}
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
                />
            )}

            <div ref={sentinelRef} className="h-4" />

            {isFetchingNextPage && (
                <div className="flex justify-center py-8">
                    <Loader2 className="animate-spin text-gray-400" size={32} />
                </div>
            )}
        </>
    );
}
