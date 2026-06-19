import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { Image as ImageIcon, Loader2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';

// API Layer
import { filesApi } from '../api';
import { jobsApi } from '../api/jobs';

import { useGallery } from '../hooks/useGallery';
import { useDashboardItems } from '../hooks/useDashboardItems';
import { useSelectedImageState } from '../hooks/useSelectedImageState';
import { useJobStore } from '../store/jobStore';
import { useGeneratorStore } from '../store/generatorStore';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { useDashboardModals } from '../hooks/useDashboardModals';
import { useDashboardSelection } from '../hooks/useDashboardSelection';

import { GallerySkeleton } from '../components/Skeleton';
import ConfirmationModal from '../components/ConfirmationModal';
import useSettingsStore from '../store/settingsStore';

import { FilterBar } from '../components/dashboard/FilterBar';
import GroupedDashboardContent from '../components/dashboard/GroupedDashboardContent';
import { ImageComparison } from '../components/dashboard/ImageComparison';
import { TimelineView } from '../components/dashboard/TimelineView';
import SelectionToolbar from '../components/dashboard/SelectionToolbar';
import ImageLightbox from '../components/dashboard/ImageLightbox';
import JobDetailsModal from '../components/dashboard/JobDetailsModal';
import useStore from '../store/useStore';
import CollectionsPanel from '../components/collections/CollectionsPanel';
import SelectCollectionModal from '../components/collections/SelectCollectionModal';
import { useInfiniteScroll } from '../hooks/useInfiniteScroll';
import StatsPanel from '../components/stats/StatsPanel';
import EmptyState from '../components/EmptyState';
import QueueVisualization from '../components/QueueVisualization';
import { usePullToRefresh, PullToRefreshIndicator } from '../hooks/usePullToRefresh';
import { useGalleryAutoRefresh } from '../hooks/useGalleryAutoRefresh';
import { DashboardHeader } from '../components/dashboard/DashboardHeader';
import { DashboardToolbar } from '../components/dashboard/DashboardToolbar';
import {
    buildGeneratorStateFromMetadata,
    hydrateGeneratorStateModelVisuals,
} from '../utils/reuseParameters';

export default function Dashboard() {
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const defaultViewMode = useSettingsStore((state) => state.settings.ui.defaultViewMode);
    const defaultGridColumns = useSettingsStore((state) => state.settings.ui.defaultGridColumns);
    const autoRefreshOnJobComplete = useSettingsStore((state) => state.settings.gallery.autoRefreshOnJobComplete);
    const toastSuccessDuration = useSettingsStore((state) => state.settings.ui.toastSuccessDuration);
    const toastErrorDuration = useSettingsStore((state) => state.settings.ui.toastErrorDuration);
    
    // Global State
    const activeJobs = useJobStore((state) => state.jobs);
    const cancelJob = useJobStore((state) => state.cancelJob);
    const favorites = useStore((state) => state.favorites);
    const toggleFavorite = useStore((state) => state.toggleFavorite);
    const collections = useStore((state) => state.collections);
    const activeCollection = useStore((state) => state.activeCollection);
    const addToCollection = useStore((state) => state.addToCollection);
    const removeFromCollection = useStore((state) => state.removeFromCollection);
    const setActiveCollection = useStore((state) => state.setActiveCollection);
    const initCollections = useStore((state) => state.initCollections);
    const loadCollectionImages = useStore((state) => state.loadCollectionImages);

    // Local State
    const [viewMode, setViewMode] = useState(() => defaultViewMode);
    const [gridCols, setGridCols] = useState(defaultGridColumns);

    // Filters
    const [showFavorites, setShowFavorites] = useState(false);
    const [filters, setFilters] = useState({
        search: '',
        model: '',
        sampler: '',
        aspect_ratio: ''
    });

    const {
        confirmModal,
        setConfirmModal,
        selectedJobId,
        setSelectedJobId,
        showCollectionsPanel,
        setShowCollectionsPanel,
        showSelectCollection,
        setShowSelectCollection,
        showStatsPanel,
        setShowStatsPanel,
        showComparison,
        setShowComparison,
        deleteJob,
        retryJob,
        handleJobDelete,
        handleJobClick,
        handleJobDetailsClose,
    } = useDashboardModals({ queryClient, filters });

    const {
        selectionMode,
        setSelectionMode,
        selectedFiles,
        setSelectedFiles,
        toggleSelection,
        handleBatchDownload,
        handleBatchFavorite,
        handleAddSelectionToCollection,
        handleRemoveSelectionFromCollection,
        handleBatchDelete,
        handleCancelSelectionMode,
    } = useDashboardSelection({
        favorites,
        toggleFavorite,
        queryClient,
        filters,
        setConfirmModal,
        activeCollection,
        removeFromCollection,
        setShowSelectCollection
    });

    const [isReusingParameters, setIsReusingParameters] = useState(false);
    const reuseParametersLockRef = useRef(false);
    
    const {
        selectedImage,
        metadata,
        loadingMeta,
        selectImage,
        closeSelectedImage,
    } = useSelectedImageState();

    const handleLightboxNavigate = useCallback((newIndex) => {
        if (selectedImage?.siblingImages?.[newIndex]) {
            selectImage({
                ...selectedImage.siblingImages[newIndex],
                siblingImages: selectedImage.siblingImages,
                associatedJob: selectedImage.associatedJob
            });
        }
    }, [selectImage, selectedImage]);

    const lightboxImages = useMemo(() => {
        if (!selectedImage) return [];
        return selectedImage.siblingImages || [selectedImage];
    }, [selectedImage]);

    const favoritesSet = useMemo(() => new Set(favorites), [favorites]);
    const fastIsFavorite = useCallback((filename) => favoritesSet.has(filename), [favoritesSet]);

    const handleToggleFavorite = useCallback((filename) => {
        toggleFavorite(filename);
        toast.success(
            fastIsFavorite(filename) ? "Removed from favorites" : "Added to favorites",
            { icon: fastIsFavorite(filename) ? '⭐' : '⭐' }
        );
    }, [toggleFavorite, fastIsFavorite]);

    const handleImageClick = useCallback((image) => {
        selectImage(image);
    }, [selectImage]);

    // Data Fetching
    const {
        data,
        fetchNextPage,
        hasNextPage,
        isFetchingNextPage,
        isLoading,
        refetch
    } = useGallery(filters);

    const sentinelRef = useInfiniteScroll({
        hasMore: hasNextPage,
        onLoadMore: fetchNextPage,
        loading: isFetchingNextPage,
        rootMargin: '600px'
    });

    const hasInitializedRef = useRef(false);
    useEffect(() => {
        if (hasInitializedRef.current) return;
        hasInitializedRef.current = true;
        void refetch();
        void initCollections();
    }, [initCollections, refetch]);

    useEffect(() => {
        if (!activeCollection) return;
        const collection = collections[activeCollection];
        if (!collection) return;

        const imageCount = collection.imageCount ?? collection.images?.length ?? 0;
        if ((collection.images?.length ?? 0) === 0 && imageCount > 0) {
            void loadCollectionImages(activeCollection);
        }
    }, [activeCollection, collections, loadCollectionImages]);

    const lastCompletedJob = useJobStore(state => state.lastCompletedJob);
    
    useGalleryAutoRefresh({
        lastCompletedJob,
        autoRefreshOnJobComplete,
        queryClient,
        toastSuccessDuration,
        galleryQueryKey: ['gallery', filters],
    });

    useKeyboardShortcuts({
        onEscape: () => {
            if (selectedImage) closeSelectedImage();
            else if (selectedJobId) setSelectedJobId(null);
        }
    });

    const {
        allItems,
        displayedItems,
        selectedJob,
        sortedGroupedEntries,
        formatDateLabel,
    } = useDashboardItems({
        data,
        activeJobs,
        selectedJobId,
        activeCollection,
        collections,
        showFavorites,
        favorites,
    });

    const handleDelete = useCallback((filename) => {
        setConfirmModal({
            isOpen: true,
            title: 'Delete Image',
            message: `Are you sure you want to delete ${filename}? This action cannot be undone.`,
            isDangerous: true,
            confirmText: 'Delete',
            onConfirm: async () => {
                try {
                    await filesApi.deleteMultiple([filename]);
                    queryClient.invalidateQueries({ queryKey: ['gallery', filters], exact: true });
                    if (selectedImage?.name === filename) closeSelectedImage();
                    toast.success(`Successfully deleted ${filename}`, {
                        icon: '🗑️',
                        duration: toastSuccessDuration,
                    });
                } catch (e) {
                    toast.error(`Failed to delete: ${e.message}`, {
                        icon: '❌',
                        duration: toastErrorDuration,
                    });
                }
            }
        });
    }, [closeSelectedImage, queryClient, selectedImage, toastErrorDuration, toastSuccessDuration, filters, setConfirmModal]);

    const useParameters = useCallback(async () => {
        if (reuseParametersLockRef.current) return;
        if (!metadata) return;

        reuseParametersLockRef.current = true;
        setIsReusingParameters(true);
        try {
            const reuseState = buildGeneratorStateFromMetadata(metadata);
            if (Object.keys(reuseState).length === 0) {
                toast.error('Could not parse reusable parameters from this image.', {
                    icon: '⚠️',
                    duration: toastErrorDuration,
                });
                return;
            }

            const hydratedState = await hydrateGeneratorStateModelVisuals(reuseState);
            useGeneratorStore.getState().setAll(hydratedState);
            useSettingsStore.getState().updateSetting('generator', 'autoRandomizeSeed', false);

            toast.success('Parameters loaded! Auto-randomize seed disabled for reproduction.', {
                icon: '🎯',
                duration: toastSuccessDuration
            });
            navigate('/generate');
        } finally {
            reuseParametersLockRef.current = false;
            setIsReusingParameters(false);
        }
    }, [metadata, navigate, toastErrorDuration, toastSuccessDuration]);

    const handlePullToRefresh = useCallback(async () => {
        await refetch();
        await new Promise(resolve => setTimeout(resolve, 500));
    }, [refetch]);

    const { containerRef, pullDistance, isRefreshing, isPulling } = usePullToRefresh({
        onRefresh: handlePullToRefresh,
        threshold: 80
    });

    return (
        <motion.div
            ref={containerRef}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
        >
            <PullToRefreshIndicator
                pullDistance={pullDistance}
                isRefreshing={isRefreshing}
                isPulling={isPulling}
                threshold={80}
            />
            <div className="max-w-7xl mx-auto space-y-8">
                <QueueVisualization onJobClick={handleJobClick} />

                <div className="flex flex-col gap-4">
                    <DashboardHeader
                        viewMode={viewMode}
                        setViewMode={setViewMode}
                        gridCols={gridCols}
                        setGridCols={setGridCols}
                        selectionMode={selectionMode}
                        setSelectionMode={(mode) => {
                            setSelectionMode(mode);
                            if (mode) setSelectedFiles(new Set());
                        }}
                        selectedFilesCount={selectedFiles.size}
                        onRefetch={() => refetch()}
                    />

                    <DashboardToolbar
                        showFavorites={showFavorites}
                        setShowFavorites={setShowFavorites}
                        favoritesCount={favorites.length}
                        activeCollection={activeCollection}
                        activeCollectionName={activeCollection && collections[activeCollection] ? collections[activeCollection].name : null}
                        setShowCollectionsPanel={setShowCollectionsPanel}
                        setShowStatsPanel={setShowStatsPanel}
                        onClearHistory={() => {
                            setConfirmModal({
                                isOpen: true,
                                title: 'Clear Job History',
                                message: 'Are you sure you want to clear all job history? This will remove all job records but keep the generated images.',
                                isDangerous: true,
                                confirmText: 'Clear History',
                                onConfirm: async () => {
                                    await jobsApi.clear();
                                    useJobStore.setState({ jobs: [] });
                                    refetch();
                                }
                            });
                        }}
                    />

                    <AnimatePresence>
                        {selectionMode && (
                            <SelectionToolbar
                                selectedFiles={selectedFiles}
                                onDownload={handleBatchDownload}
                                onDelete={handleBatchDelete}
                                onFavorite={handleBatchFavorite}
                                onAddToCollection={handleAddSelectionToCollection}
                                onRemoveFromCollection={handleRemoveSelectionFromCollection}
                                onCancel={handleCancelSelectionMode}
                                activeCollection={activeCollection}
                            />
                        )}
                    </AnimatePresence>
                </div>

                <FilterBar filters={filters} onFilterChange={setFilters} />

                {isLoading ? (
                    <GallerySkeleton count={12} mode={viewMode} />
                ) : !isLoading && displayedItems.length === 0 ? (
                    <EmptyState
                        type={
                            showFavorites ? 'favorites' :
                                activeCollection ? 'collection' :
                                    filters.search || filters.model ? 'search' :
                                        'gallery'
                        }
                        onAction={() => {
                            if (showFavorites) {
                                setShowFavorites(false);
                            } else if (activeCollection) {
                                setActiveCollection(null);
                            } else if (filters.search || filters.model) {
                                setFilters({ search: '', model: '', sampler: '', aspect_ratio: '' });
                            }
                        }}
                        showTutorialHint={!showFavorites && !activeCollection && allItems.length === 0}
                    />
                ) : (
                    viewMode === 'timeline' ? (
                        <TimelineView
                            items={displayedItems}
                            onImageClick={handleImageClick}
                            onJobClick={handleJobClick}
                            selectionMode={selectionMode}
                            selectedFiles={selectedFiles}
                            onToggleSelection={toggleSelection}
                            isFavorite={fastIsFavorite}
                            onToggleFavorite={handleToggleFavorite}
                        />
                    ) : (
                        <GroupedDashboardContent
                            viewMode={viewMode}
                            sortedGroupedEntries={sortedGroupedEntries}
                            formatDateLabel={formatDateLabel}
                            gridCols={gridCols}
                            selectedFiles={selectedFiles}
                            selectionMode={selectionMode}
                            handleJobClick={handleJobClick}
                            handleImageClick={handleImageClick}
                            toggleSelection={toggleSelection}
                            isFavorite={fastIsFavorite}
                            handleToggleFavorite={handleToggleFavorite}
                            handleDelete={handleDelete}
                            handleJobDelete={handleJobDelete}
                        />
                    )
                )}

                <div ref={sentinelRef} className="h-4" />

                {isFetchingNextPage && (
                    <div className="flex justify-center py-8">
                        <Loader2 className="animate-spin text-gray-400" size={32} />
                    </div>
                )}
            </div>

            {selectedImage && (
                <ImageLightbox
                    image={selectedImage}
                    images={lightboxImages}
                    currentIndex={selectedImage.siblingImages?.findIndex(img => img.name === selectedImage.name) || 0}
                    onNavigate={handleLightboxNavigate}
                    metadata={metadata}
                    loadingMeta={loadingMeta}
                    job={selectedImage.associatedJob}
                    onClose={closeSelectedImage}
                    onDelete={handleDelete}
                    onReuseParameters={useParameters}
                    reuseInProgress={isReusingParameters}
                />
            )}

            {selectedJob && (
                <JobDetailsModal
                    job={selectedJob}
                    onClose={handleJobDetailsClose}
                    onCancel={cancelJob}
                    onDelete={deleteJob}
                    onRetry={retryJob}
                />
            )}

            <ConfirmationModal
                isOpen={confirmModal.isOpen}
                title={confirmModal.title}
                message={confirmModal.message}
                isDangerous={confirmModal.isDangerous}
                confirmText={confirmModal.confirmText}
                onConfirm={confirmModal.onConfirm}
                onCancel={() => setConfirmModal((prev) => ({ ...prev, isOpen: false }))}
            />

            {showComparison && (
                <ImageComparison
                    images={allItems.filter(item => selectedFiles.has(item.name))}
                    onClose={() => setShowComparison(false)}
                />
            )}

            <CollectionsPanel
                isOpen={showCollectionsPanel}
                onClose={() => setShowCollectionsPanel(false)}
            />

            <button
                onClick={() => navigate('/generate')}
                className="fixed bottom-6 right-6 z-40 md:hidden bg-blue-600 hover:bg-blue-500 text-white p-4 rounded-full shadow-lg transition-all transform hover:scale-110 flex items-center gap-2"
                title="Go to Generator"
                aria-label="Go to Generator"
            >
                <ImageIcon size={24} />
            </button>

            <SelectCollectionModal
                isOpen={showSelectCollection}
                onClose={() => setShowSelectCollection(false)}
                collections={collections}
                onSelect={(collectionId) => {
                    addToCollection(collectionId, Array.from(selectedFiles));
                    toast.success(`Added ${selectedFiles.size} images to collection`, { icon: '📁' });
                    setSelectedFiles(new Set());
                    setSelectionMode(false);
                }}
            />

            <StatsPanel
                isOpen={showStatsPanel}
                onClose={() => setShowStatsPanel(false)}
            />
        </motion.div>
    );
}
