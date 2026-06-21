import { AnimatePresence } from 'framer-motion';
import { DashboardHeader } from './DashboardHeader';
import { DashboardToolbar } from './DashboardToolbar';
import SelectionToolbar from './SelectionToolbar';
import { FilterBar } from './FilterBar';

/**
 * DashboardHeaderToolbar Component
 * @param {object} props
 * @param {string} props.viewMode - Current view mode
 * @param {(mode: string) => void} props.setViewMode - Callback to change view mode
 * @param {number} props.gridCols - Grid column count
 * @param {(cols: number) => void} props.setGridCols - Callback to change grid columns
 * @param {boolean} props.selectionMode - Whether selection mode is enabled
 * @param {(mode: boolean) => void} props.setSelectionMode - Callback to change selection mode
 * @param {Set<string>} props.selectedFiles - Selected files set
 * @param {() => void} props.onRefetch - Callback to refetch gallery
 * 
 * @param {boolean} props.showFavorites - Whether showFavorites filter is active
 * @param {(val: boolean) => void} props.setShowFavorites - Callback to change showFavorites filter
 * @param {number} props.favoritesCount - Total favorites count
 * @param {string|null} props.activeCollection - Active collection ID or null
 * @param {string|null} props.activeCollectionName - Active collection name or null
 * @param {(val: boolean) => void} props.setShowCollectionsPanel - Callback to show/hide collections panel
 * @param {() => Promise<void>} props.onClearHistory - Callback to clear job history
 * 
 * @param {() => void} props.onBatchDownload - Callback to download selected files
 * @param {() => Promise<void>} props.onBatchDelete - Callback to delete selected files
 * @param {() => Promise<void>} props.onBatchFavorite - Callback to toggle favorite on selected files
 * @param {() => void} props.onBatchAddToCollection - Callback to add selected files to a collection
 * @param {() => Promise<void>} props.onBatchRemoveFromCollection - Callback to remove selected files from collection
 * @param {() => void} props.onCancelSelectionMode - Callback to cancel selection mode
 * 
 * @param {object} props.filters - Active filters state
 * @param {(filters: object) => void} props.onFilterChange - Callback to change filters state
 */
export default function DashboardHeaderToolbar({
    viewMode,
    setViewMode,
    gridCols,
    setGridCols,
    selectionMode,
    setSelectionMode,
    selectedFiles,
    onRefetch,

    showFavorites,
    setShowFavorites,
    favoritesCount,
    activeCollection,
    activeCollectionName,
    setShowCollectionsPanel,
    onClearHistory,

    onBatchDownload,
    onBatchDelete,
    onBatchFavorite,
    onBatchAddToCollection,
    onBatchRemoveFromCollection,
    onCancelSelectionMode,

    filters,
    onFilterChange,
}) {
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-4">
                <DashboardHeader
                    viewMode={viewMode}
                    setViewMode={setViewMode}
                    gridCols={gridCols}
                    setGridCols={setGridCols}
                    selectionMode={selectionMode}
                    setSelectionMode={setSelectionMode}
                    selectedFilesCount={selectedFiles.size}
                    onRefetch={onRefetch}
                />

                <DashboardToolbar
                    showFavorites={showFavorites}
                    setShowFavorites={setShowFavorites}
                    favoritesCount={favoritesCount}
                    activeCollection={activeCollection}
                    activeCollectionName={activeCollectionName}
                    setShowCollectionsPanel={setShowCollectionsPanel}
                    onClearHistory={onClearHistory}
                />

                <AnimatePresence>
                    {selectionMode && (
                        <SelectionToolbar
                            selectedFiles={selectedFiles}
                            onDownload={onBatchDownload}
                            onDelete={onBatchDelete}
                            onFavorite={onBatchFavorite}
                            onAddToCollection={onBatchAddToCollection}
                            onRemoveFromCollection={onBatchRemoveFromCollection}
                            onCancel={onCancelSelectionMode}
                            activeCollection={activeCollection}
                        />
                    )}
                </AnimatePresence>
            </div>

            <FilterBar filters={filters} onFilterChange={onFilterChange} />
        </div>
    );
}
