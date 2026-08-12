import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useQueryClient } from '@tanstack/react-query';
import { motion } from 'framer-motion';

// API Layer
import { filesApi } from '../api';
import { jobsApi } from '../api/jobs';
import { cancelJob as cancelJobWs } from '../api/websocket';
import * as ws from '../api/websocket';

// Hooks
import { useGallery } from '../hooks/useGallery';
import { useDashboardItems } from '../hooks/useDashboardItems';
import { useFavorites } from '../hooks/useFavorites';
import { useSelectedImageState } from '../hooks/useSelectedImageState';
import { useActiveJobs } from '../hooks/useActiveJobs';
import {
    useCollections,
    useCollectionImages,
    useAddImagesToCollection,
    useRemoveImagesFromCollection
} from '../hooks/useCollections';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { useDashboardModals } from '../hooks/useDashboardModals';
import { useDashboardSelection } from '../hooks/useDashboardSelection';
import { useInfiniteScroll } from '../hooks/useInfiniteScroll';
import { usePullToRefresh, PullToRefreshIndicator } from '../hooks/usePullToRefresh';
import { useGalleryAutoRefresh } from '../hooks/useGalleryAutoRefresh';

// Stores
import { useConfirmation } from '../store/confirmationStore';
import useSettingsStore from '../store/settingsStore';
import useStore from '../store/useStore';

// Components
import QueueVisualization from '../components/QueueVisualization';
import GeneratorFloatingButton from '../components/dashboard/GeneratorFloatingButton';
import DashboardOverlays from '../components/dashboard/DashboardOverlays';
import DashboardGalleryGrid from '../components/dashboard/DashboardGalleryGrid';
import DashboardHeaderToolbar from '../components/dashboard/DashboardHeaderToolbar';

// Utils
import {
    applyGeneratorStateFromMetadata,
} from '../utils/reuseParameters';

export default function Dashboard() {
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const defaultGridColumns = useSettingsStore((state) => state.settings.ui.defaultGridColumns);
    const autoRefreshOnJobComplete = useSettingsStore((state) => state.settings.gallery.autoRefreshOnJobComplete);
    const toastSuccessDuration = useSettingsStore((state) => state.settings.ui.toastSuccessDuration);
    const toastErrorDuration = useSettingsStore((state) => state.settings.ui.toastErrorDuration);
    
    const { favorites, isFavorite: fastIsFavorite, toggleFavorite } = useFavorites();
    const activeCollection = useStore((state) => state.activeCollection);
    const setActiveCollection = useStore((state) => state.setActiveCollection);
    
    // React Query / WebSocket state
    const { data: activeJobs = [] } = useActiveJobs();
    const { data: collections = {} } = useCollections();
    const { data: activeCollectionImages = [] } = useCollectionImages(activeCollection);
    
    const addImagesToCollectionMutation = useAddImagesToCollection();
    const removeImagesFromCollectionMutation = useRemoveImagesFromCollection();

    const collectionsWithImages = useMemo(() => {
        if (!activeCollection || !collections[activeCollection]) return collections;
        return {
            ...collections,
            [activeCollection]: {
                ...collections[activeCollection],
                images: activeCollectionImages
            }
        };
    }, [collections, activeCollection, activeCollectionImages]);

    const addToCollection = useCallback(async (collectionId, images) => {
        const imagesArray = Array.isArray(images) ? images : [images];
        await addImagesToCollectionMutation.mutateAsync({ collectionId, images: imagesArray });
    }, [addImagesToCollectionMutation]);

    const removeFromCollection = useCallback(async (collectionId, images) => {
        const imagesArray = Array.isArray(images) ? images : [images];
        await removeImagesFromCollectionMutation.mutateAsync({ collectionId, images: imagesArray });
    }, [removeImagesFromCollectionMutation]);

    const cancelJob = useCallback(async (jobId) => {
        try {
            await cancelJobWs(jobId);
            queryClient.setQueryData(['jobs', 'active'], (old = []) => old.filter(j => j.id !== jobId));
        } catch (error) {
            console.error('Failed to cancel job:', error);
            toast.error('Failed to cancel job');
        }
    }, [queryClient]);

    const [lastCompletedJob, setLastCompletedJob] = useState(null);
    useEffect(() => {
        return ws.on(ws.EventTypes.JOB_COMPLETED, (event) => {
            const job = event.data?.job || event;
            if (!Array.isArray(job.outputs) || job.outputs.length === 0) {
                return;
            }
            const autoRefreshEnabled = useSettingsStore.getState().settings.gallery.autoRefreshOnJobComplete;
            if (!autoRefreshEnabled) {
                return;
            }
            setLastCompletedJob(job);
        });
    }, []);

    // Local State
    const viewMode = useSettingsStore((state) => state.settings.ui.defaultViewMode);
    const setViewMode = useCallback((mode) => {
        useSettingsStore.getState().updateSetting('ui', 'defaultViewMode', mode);
    }, []);
    const [gridCols, setGridCols] = useState(defaultGridColumns);

    // Filters
    const [showFavorites, setShowFavorites] = useState(false);
    const [filters, setFilters] = useState({ search: '' });

    const { confirm } = useConfirmation();

    const {
        selectedJobId,
        setSelectedJobId,
        showCollectionsPanel,
        setShowCollectionsPanel,
        showSelectCollection,
        setShowSelectCollection,
        showComparison,
        setShowComparison,
        deleteJob,
        retryJob,
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
        confirm,
        activeCollection,
        removeFromCollection,
        setShowSelectCollection
    });

    const handleSetSelectionMode = useCallback((mode) => {
        setSelectionMode(mode);
        if (mode) setSelectedFiles(new Set());
    }, [setSelectionMode, setSelectedFiles]);

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

    const handleToggleFavorite = useCallback((filename) => {
        const wasFavorite = fastIsFavorite(filename);
        toggleFavorite(filename);
        toast.success(
            wasFavorite ? "Removed from favorites" : "Added to favorites",
            { icon: '⭐' }
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
    }, [refetch]);
    
    useGalleryAutoRefresh({
        lastCompletedJob,
        autoRefreshOnJobComplete,
        queryClient,
        galleryQueryKey: ['gallery', filters],
    });

    useKeyboardShortcuts({
        onEscape: () => {
            if (selectedImage) closeSelectedImage();
            else if (selectedJobId) setSelectedJobId(null);
            else if (selectionMode) handleCancelSelectionMode();
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
        collections: collectionsWithImages,
        showFavorites,
        favorites,
        sort: filters.sort || 'date_desc',
    });

    const handleDelete = useCallback(async (filename) => {
        const accepted = await confirm({
            title: 'Delete Image',
            message: `Are you sure you want to delete ${filename}? This action cannot be undone.`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!accepted) return;
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
    }, [closeSelectedImage, confirm, queryClient, selectedImage, toastErrorDuration, toastSuccessDuration, filters]);

    const handleJobDelete = useCallback(async (jobId) => {
        const accepted = await confirm({
            title: 'Remove Job',
            message: 'Are you sure you want to remove this job from history? The generated images will remain in your gallery.',
            confirmText: 'Remove',
            isDangerous: true,
        });
        if (!accepted) return;
        try {
            await deleteJob(jobId);
            toast.success('Job removed from history');
        } catch (e) {
            toast.error(e.message || 'Failed to remove job');
        }
    }, [confirm, deleteJob]);

    const useParameters = useCallback(async () => {
        if (reuseParametersLockRef.current) return;
        if (!metadata) return;

        reuseParametersLockRef.current = true;
        setIsReusingParameters(true);
        try {
            const applied = await applyGeneratorStateFromMetadata(metadata);
            if (!applied) {
                toast.error('Could not parse reusable parameters from this image.', {
                    icon: '⚠️',
                    duration: toastErrorDuration,
                });
                return;
            }

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

    const handleClearFilters = useCallback(() => {
        if (showFavorites) {
            setShowFavorites(false);
        } else if (activeCollection) {
            setActiveCollection(null);
        } else if (filters.search) {
            setFilters({ search: '' });
        }
    }, [showFavorites, activeCollection, filters, setShowFavorites, setActiveCollection, setFilters]);

    const handleClearHistory = useCallback(async () => {
        const accepted = await confirm({
            title: 'Clear Job History',
            message: 'Are you sure you want to clear all job history? This will remove all job records but keep the generated images.',
            confirmText: 'Clear History',
            isDangerous: true,
        });
        if (!accepted) return;
        await jobsApi.clear();
        queryClient.setQueryData(['jobs', 'active'], []);
        refetch();
    }, [confirm, queryClient, refetch]);

    const handleSelectCollection = useCallback((collectionId) => {
        addToCollection(collectionId, Array.from(selectedFiles));
        toast.success(`Added ${selectedFiles.size} images to collection`, { icon: '📁' });
        setSelectedFiles(new Set());
        setSelectionMode(false);
    }, [addToCollection, selectedFiles, setSelectedFiles, setSelectionMode]);

    const comparisonImages = useMemo(() => {
        return allItems.filter(item => selectedFiles.has(item.name));
    }, [allItems, selectedFiles]);

    const activeCollectionName = useMemo(() => {
        return activeCollection && collections[activeCollection] ? collections[activeCollection].name : null;
    }, [activeCollection, collections]);

    const location = useLocation();
    useEffect(() => {
        if (location.pathname !== '/') return;

        const handleKeyPress = (e) => {
            if (
                e.target.tagName === 'INPUT' ||
                e.target.tagName === 'TEXTAREA' ||
                e.target.isContentEditable
            ) {
                return;
            }

            const key = e.key.toLowerCase();

            if (e.ctrlKey || e.metaKey) {
                if (key === 'a' && selectionMode) {
                    e.preventDefault();
                    const allNames = displayedItems.map(item => item.name);
                    setSelectedFiles(new Set(allNames));
                }
                return;
            }

            if (e.altKey) return;

            if (key === 's') {
                e.preventDefault();
                handleSetSelectionMode(!selectionMode);
            } else if (key === 'r') {
                e.preventDefault();
                refetch();
            } else if (key === ' ' || key === 'spacebar') {
                if (selectedImage) {
                    e.preventDefault();
                    closeSelectedImage();
                }
            } else if (e.key === 'Delete' || e.key === 'Backspace') {
                if (selectionMode && selectedFiles.size > 0) {
                    e.preventDefault();
                    handleBatchDelete();
                } else if (selectedImage) {
                    e.preventDefault();
                    handleDelete(selectedImage.name);
                }
            }
        };

        window.addEventListener('keydown', handleKeyPress);
        return () => window.removeEventListener('keydown', handleKeyPress);
    }, [
        location.pathname, selectionMode, handleSetSelectionMode, refetch,
        selectedFiles, displayedItems, setSelectedFiles, handleBatchDelete,
        selectedImage, closeSelectedImage, handleDelete
    ]);

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
            <div className="max-w-7xl mx-auto space-y-4 md:space-y-8">
                <QueueVisualization onJobClick={handleJobClick} />

                <DashboardHeaderToolbar
                    viewMode={viewMode}
                    setViewMode={setViewMode}
                    gridCols={gridCols}
                    setGridCols={setGridCols}
                    selectionMode={selectionMode}
                    setSelectionMode={handleSetSelectionMode}
                    selectedFiles={selectedFiles}
                    onRefetch={refetch}
                    showFavorites={showFavorites}
                    setShowFavorites={setShowFavorites}
                    favoritesCount={favorites.length}
                    activeCollection={activeCollection}
                    activeCollectionName={activeCollectionName}
                    setShowCollectionsPanel={setShowCollectionsPanel}
                    onClearHistory={handleClearHistory}
                    onBatchDownload={handleBatchDownload}
                    onBatchDelete={handleBatchDelete}
                    onBatchFavorite={handleBatchFavorite}
                    onBatchAddToCollection={handleAddSelectionToCollection}
                    onBatchRemoveFromCollection={handleRemoveSelectionFromCollection}
                    onCancelSelectionMode={handleCancelSelectionMode}
                    filters={filters}
                    onFilterChange={setFilters}
                />

                <DashboardGalleryGrid
                    isLoading={isLoading}
                    viewMode={viewMode}
                    displayedItems={displayedItems}
                    showFavorites={showFavorites}
                    activeCollection={activeCollection}
                    filters={filters}
                    onClearFilters={handleClearFilters}
                    allItems={allItems}
                    onImageClick={handleImageClick}
                    onJobClick={handleJobClick}
                    selectionMode={selectionMode}
                    selectedFiles={selectedFiles}
                    onToggleSelection={toggleSelection}
                    isFavorite={fastIsFavorite}
                    onToggleFavorite={handleToggleFavorite}
                    sortedGroupedEntries={sortedGroupedEntries}
                    formatDateLabel={formatDateLabel}
                    gridCols={gridCols}
                    onDelete={handleDelete}
                    onJobDelete={handleJobDelete}
                    sentinelRef={sentinelRef}
                    isFetchingNextPage={isFetchingNextPage}
                />
            </div>

            <DashboardOverlays
                selectedImage={selectedImage}
                lightboxImages={lightboxImages}
                onLightboxNavigate={handleLightboxNavigate}
                metadata={metadata}
                loadingMeta={loadingMeta}
                onLightboxClose={closeSelectedImage}
                onLightboxDelete={handleDelete}
                onLightboxReuseParameters={useParameters}
                reuseInProgress={isReusingParameters}
                selectedJob={selectedJob}
                onJobDetailsClose={handleJobDetailsClose}
                onJobCancel={cancelJob}
                onJobDelete={deleteJob}
                onJobRetry={retryJob}
                showComparison={showComparison}
                onComparisonClose={() => setShowComparison(false)}
                comparisonImages={comparisonImages}
                showCollectionsPanel={showCollectionsPanel}
                onCollectionsPanelClose={() => setShowCollectionsPanel(false)}
                showSelectCollection={showSelectCollection}
                onSelectCollectionClose={() => setShowSelectCollection(false)}
                collections={collections}
                onSelectCollection={handleSelectCollection}
            />

            <GeneratorFloatingButton onClick={() => navigate('/generate')} />
        </motion.div>
    );
}
