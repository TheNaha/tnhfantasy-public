import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { Image as ImageIcon, Loader2, Trash2, RefreshCw, Check, LayoutGrid, List, Square, Star, FolderOpen, BarChart3, LineChart } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';

// API Layer
import { filesApi } from '../api';

import { useGallery } from '../hooks/useGallery';
import { useDashboardItems } from '../hooks/useDashboardItems';
import { useSelectedImageState } from '../hooks/useSelectedImageState';
import { useJobStore } from '../store/jobStore';
import { useGeneratorStore } from '../store/generatorStore';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
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

export default function Dashboard() {
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const defaultViewMode = useSettingsStore((state) => state.settings.ui.defaultViewMode);
    const defaultGridColumns = useSettingsStore((state) => state.settings.ui.defaultGridColumns);
    const autoRefreshOnJobComplete = useSettingsStore((state) => state.settings.gallery.autoRefreshOnJobComplete);
    const toastSuccessDuration = useSettingsStore((state) => state.settings.ui.toastSuccessDuration);
    const toastErrorDuration = useSettingsStore((state) => state.settings.ui.toastErrorDuration);
    const updateSetting = useSettingsStore((state) => state.updateSetting);
    // Global State - now uses WebSocket for real-time updates
    const activeJobs = useJobStore((state) => state.jobs);
    const clearJobs = useJobStore((state) => state.clearJobs);
    const storeDeleteJob = useJobStore((state) => state.deleteJob);
    const retryJob = useJobStore((state) => state.retryJob);
    const cancelJob = useJobStore((state) => state.cancelJob);
    const { favorites, toggleFavorite, collections, activeCollection, addToCollection, removeFromCollection, setActiveCollection } = useStore();

    // Local State
    const [viewMode, setViewMode] = useState(() => defaultViewMode);

    // Confirmation Modal
    const [confirmModal, setConfirmModal] = useState({
        isOpen: false,
        title: '',
        message: '',
        isDangerous: false,
        confirmText: 'Confirm',
        onConfirm: () => { }
    });

    // Wrapped deleteJob to handle query invalidation
    const deleteJob = useCallback(async (jobId) => {
        await storeDeleteJob(jobId);
        queryClient.invalidateQueries({ queryKey: ['gallery'] });
    }, [storeDeleteJob, queryClient]);

    // Wrapped deleteJob with confirmation modal for card dismiss button
    const handleJobDelete = useCallback((jobId) => {
        setConfirmModal({
            isOpen: true,
            title: 'Remove Job',
            message: 'Are you sure you want to remove this job from history? The generated images will remain in your gallery.',
            isDangerous: true,
            confirmText: 'Remove',
            onConfirm: async () => {
                try {
                    await deleteJob(jobId);
                    toast.success('Job removed from history');
                } catch (e) {
                    toast.error(e.message || 'Failed to remove job');
                }
            }
        });
    }, [deleteJob]);
    const [selectedJobId, setSelectedJobId] = useState(null);  // Store ID, not object
    const [gridCols, setGridCols] = useState(defaultGridColumns);
    const [showCollectionsPanel, setShowCollectionsPanel] = useState(false);
    const [showSelectCollection, setShowSelectCollection] = useState(false);
    const [showStatsPanel, setShowStatsPanel] = useState(false);
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

    const handleJobDetailsClose = useCallback(() => setSelectedJobId(null), [setSelectedJobId]);

    const lightboxImages = React.useMemo(() => {
        if (!selectedImage) return [];
        return selectedImage.siblingImages || [selectedImage];
    }, [selectedImage]);


    // Filters
    const [showFavorites, setShowFavorites] = useState(false);
    const [filters, setFilters] = useState({
        search: '',
        model: '',
        sampler: '',
        aspect_ratio: ''
    });

    // Batch Operations
    const [selectionMode, setSelectionMode] = useState(false);
    const [selectedFiles, setSelectedFiles] = useState(new Set());
    const [showComparison, setShowComparison] = useState(false);

    // ⚡ Bolt: Pre-compute a Set of favorites to prevent O(N*M) performance degradation during rendering
    // when calling `isFavorite` for every item in large galleries.
    const favoritesSet = useMemo(() => new Set(favorites), [favorites]);
    const fastIsFavorite = useCallback((filename) => favoritesSet.has(filename), [favoritesSet]);

    // Stable handler for toggling favorite
    const handleToggleFavorite = useCallback((filename) => {
        toggleFavorite(filename);
        toast.success(
            fastIsFavorite(filename) ? "Removed from favorites" : "Added to favorites",
            { icon: fastIsFavorite(filename) ? '*' : '*' }
        );
    }, [toggleFavorite, fastIsFavorite]);

    // Stable handler for job click
    const handleJobClick = useCallback((job) => {
        const jobId = typeof job === 'string' ? job : job?.id;
        if (jobId) setSelectedJobId(jobId);
    }, []);

    // Stable handler for image click
    const handleImageClick = useCallback((image) => {
        selectImage(image);
    }, [selectImage]);

    // Track last completed job to avoid duplicate refreshes
    const lastCompletedJobRef = useRef(null);

    // Data Fetching
    const {
        data,
        fetchNextPage,
        hasNextPage,
        isFetchingNextPage,
        isLoading,
        refetch
    } = useGallery(filters);

    // Infinite scroll sentinel
    const sentinelRef = useInfiniteScroll({
        hasMore: hasNextPage,
        onLoadMore: fetchNextPage,
        loading: isFetchingNextPage,
        rootMargin: '600px' // Load 2 screens ahead
    });

    // Refetch gallery on mount to ensure fresh data.
    const hasInitializedRef = useRef(false);
    useEffect(() => {
        if (hasInitializedRef.current) {
            return;
        }
        hasInitializedRef.current = true;
        void refetch();
    }, [refetch]);

    // Auto-refresh gallery when any job completes
    // Use lastCompletedJob from store which gets set when job.completed WebSocket event fires
    const lastCompletedJob = useJobStore(state => state.lastCompletedJob);
    
    useEffect(() => {
        if (lastCompletedJob && lastCompletedJob.outputs && lastCompletedJob.outputs.length > 0) {
            // Check if this is a new completion we haven't handled yet
            if (lastCompletedJobRef.current !== lastCompletedJob.id) {
                lastCompletedJobRef.current = lastCompletedJob.id;
                if (autoRefreshOnJobComplete) {
                    // Invalidate all gallery queries regardless of filters
                    queryClient.invalidateQueries({ queryKey: ['gallery'] });
                    toast.success("🎉 Generation complete! Gallery updated.", {
                        duration: toastSuccessDuration,
                    });
                }
            }
        }
    }, [lastCompletedJob, queryClient, autoRefreshOnJobComplete, toastSuccessDuration]);

    // Keyboard shortcuts (ESC to close modals)
    useKeyboardShortcuts({
        onEscape: () => {
            if (selectedImage) closeSelectedImage();
            else if (selectedJob) setSelectedJobId(null);
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

    // Handlers
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
                    queryClient.invalidateQueries({ queryKey: ['gallery'] });
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
    }, [closeSelectedImage, queryClient, selectedImage, toastErrorDuration, toastSuccessDuration]);

    const useParameters = useCallback(() => {
        if (!metadata) return;

        useGeneratorStore.getState().setAll({
            prompt: metadata.prompt,
            negativePrompt: metadata.negativePrompt,
            seed: metadata.seed,
            steps: metadata.steps,
            cfg: metadata.cfg,
            sampler: metadata.sampler,
            scheduler: metadata.scheduler,
            width: metadata.width,
            height: metadata.height,
            selectedCheckpoint: metadata.checkpoint,
            selectedLoras: metadata.loras || [],
            hiresFix: metadata.hiresFix,
            hiresUpscaler: metadata.hiresUpscaler,
            adetailer: metadata.adetailer,
            adetailerModel: metadata.adetailerModel
        });

        useSettingsStore.getState().updateSetting('generator', 'autoRandomizeSeed', false);

        toast.success('Parameters loaded! Auto-randomize seed disabled for reproduction.', {
            icon: '🎯',
            duration: toastSuccessDuration
        });
        navigate('/generate');
    }, [metadata, navigate, toastSuccessDuration]);

    const handlePullToRefresh = useCallback(async () => {
        await refetch();
        await new Promise(resolve => setTimeout(resolve, 500));
    }, [refetch]);

    const toggleSelection = useCallback((filename) => {
        setSelectedFiles(prev => {
            const newSet = new Set(prev);
            if (newSet.has(filename)) newSet.delete(filename);
            else newSet.add(filename);
            return newSet;
        });
    }, []);

    const handleBatchDownload = useCallback(() => {
        setConfirmModal({
            isOpen: true,
            title: 'Download Images',
            message: `Download ${selectedFiles.size} images to your computer?`,
            isDangerous: false,
            confirmText: 'Download',
            onConfirm: async () => {
                const filesToDownload = Array.from(selectedFiles);
                toast.promise(
                    (async () => {
                        for (const filename of filesToDownload) {
                            const link = document.createElement('a');
                            link.href = `/api/view/output/${filename}`;
                            link.download = filename;
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                            await new Promise(resolve => setTimeout(resolve, 500));
                        }
                    })(),
                    {
                        loading: `Downloading ${filesToDownload.length} images...`,
                        success: `Downloaded ${filesToDownload.length} images!`,
                        error: 'Download failed'
                    }
                );
                setSelectionMode(false);
                setSelectedFiles(new Set());
            }
        });
    }, [selectedFiles]);

    const handleBatchFavorite = useCallback(() => {
        Array.from(selectedFiles).forEach(filename => {
            if (!favorites.includes(filename)) {
                toggleFavorite(filename);
            }
        });
        toast.success(`Added ${selectedFiles.size} images to favorites`, { icon: '⭐' });
    }, [favorites, selectedFiles, toggleFavorite]);

    const handleAddSelectionToCollection = useCallback(() => {
        setShowSelectCollection(true);
    }, []);

    const handleRemoveSelectionFromCollection = useCallback(() => {
        selectedFiles.forEach(filename => {
            removeFromCollection(activeCollection, filename);
        });
        toast.success(`Removed ${selectedFiles.size} images from collection`);
        setSelectedFiles(new Set());
    }, [activeCollection, removeFromCollection, selectedFiles]);

    const handleBatchDelete = useCallback(() => {
        setConfirmModal({
            isOpen: true,
            title: `Delete ${selectedFiles.size} Images`,
            message: 'Are you sure you want to delete these images? This action cannot be undone.',
            isDangerous: true,
            confirmText: 'Delete Images',
            onConfirm: async () => {
                try {
                    await filesApi.deleteMultiple(Array.from(selectedFiles));
                    queryClient.invalidateQueries({ queryKey: ['gallery'] });
                    setSelectedFiles(new Set());
                    setSelectionMode(false);
                    toast.success(`Deleted ${selectedFiles.size} images`);
                } catch (e) {
                    console.error(e);
                    toast.error(`Failed to delete: ${e.message}`);
                }
            }
        });
    }, [queryClient, selectedFiles]);

    const handleCancelSelectionMode = useCallback(() => {
        setSelectionMode(false);
        setSelectedFiles(new Set());
    }, []);

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
            className=""
        >
            <PullToRefreshIndicator
                pullDistance={pullDistance}
                isRefreshing={isRefreshing}
                isPulling={isPulling}
                threshold={80}
            />
            <div className="max-w-7xl mx-auto space-y-8">
                <QueueVisualization onJobClick={(jobId) => {
                    const job = activeJobs.find(j => j.id === jobId);
                    if (job) setSelectedJobId(job.id);
                }} />

                <div className="flex flex-col gap-4">
                    <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                        <div>
                            <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-500">
                                Gallery
                            </h1>
                            <p className="text-gray-400 mt-1 text-sm">Your generations and active jobs</p>
                        </div>

                        <div className="flex items-center gap-2 flex-wrap">
                            <div className="bg-gray-800 rounded-lg p-1 flex gap-1">
                                {['grid', 'list', 'feed', 'timeline'].map(mode => (
                                    <button
                                        key={mode}
                                        onClick={() => {
                                            setViewMode(mode);
                                            updateSetting('ui', 'defaultViewMode', mode);
                                        }}
                                        aria-label={`${mode.charAt(0).toUpperCase() + mode.slice(1)} View`}
                                        className={`p-2 rounded-md transition-all ${viewMode === mode ? 'bg-gray-700 text-white shadow-sm' : 'text-gray-400 hover:text-white'}`}
                                        type="button"
                                        title={mode === 'timeline' ? 'Timeline View - Chronological history' : `${mode.charAt(0).toUpperCase() + mode.slice(1)} View`}
                                    >
                                        {mode === 'grid' ? <LayoutGrid size={18} aria-hidden="true" /> :
                                            mode === 'list' ? <List size={18} aria-hidden="true" /> :
                                                mode === 'feed' ? <Square size={18} aria-hidden="true" /> :
                                                    <LineChart size={18} aria-hidden="true" />}
                                    </button>
                                ))}
                            </div>

                            {viewMode === 'grid' && (
                                <div className="hidden sm:flex items-center gap-2 bg-gray-800 px-3 py-2 rounded-lg border border-gray-700">
                                    <span className="text-xs text-gray-400 font-medium">Cols</span>
                                    <input
                                        type="range"
                                        min="2"
                                        max="8"
                                        value={gridCols}
                                        onChange={(e) => setGridCols(parseInt(e.target.value))}
                                        className="w-20 h-1 bg-gray-600 rounded-lg appearance-none cursor-pointer accent-blue-500"
                                        title="Adjust Grid Size"
                                        aria-label={`Grid columns: ${gridCols}. Adjust to change number of columns`}
                                        aria-valuemin="2"
                                        aria-valuemax="8"
                                        aria-valuenow={gridCols}
                                    />
                                    <span className="text-xs text-gray-400 font-medium">{gridCols}</span>
                                </div>
                            )}

                            <div className="hidden sm:block h-6 w-px bg-gray-700" />

                            <motion.button
                                whileHover={{ scale: 1.02 }}
                                whileTap={{ scale: 0.98 }}
                                onClick={() => {
                                    setSelectionMode(!selectionMode);
                                    if (selectionMode) {
                                        setSelectedFiles(new Set());
                                    }
                                }}
                                className={`px-4 py-2 rounded-lg font-medium transition-all flex items-center gap-2 ${selectionMode ? 'bg-blue-600 text-white hover:bg-blue-500' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'}`}
                                type="button"
                                aria-pressed={selectionMode}
                                aria-label={selectionMode ? 'Exit selection mode' : 'Enter selection mode to select multiple images'}
                            >
                                <Check size={16} aria-hidden="true" />
                                <span className="hidden sm:inline">{selectionMode ? `Selected (${selectedFiles.size})` : 'Select'}</span>
                                <span className="sm:hidden">{selectedFiles.size > 0 ? selectedFiles.size : 'Select'}</span>
                            </motion.button>

                            <button
                                onClick={() => refetch()}
                                className="p-2 bg-gray-800 rounded-lg hover:bg-gray-700 text-gray-400 hover:text-white transition-colors"
                                title="Refresh gallery"
                                aria-label="Refresh gallery to load latest images"
                                type="button"
                            >
                                <RefreshCw size={20} aria-hidden="true" />
                            </button>
                        </div>
                    </div>

                    <div className="flex items-center gap-2 flex-wrap">
                        <button
                            onClick={() => setShowFavorites(!showFavorites)}
                            className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors text-sm ${showFavorites ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30' : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-yellow-400 border border-gray-700'}`}
                            title={showFavorites ? 'Show All Images' : 'Show Favorites Only'}
                            aria-label={showFavorites ? `Showing ${favorites.length} favorites. Click to show all images` : `Show favorites only. ${favorites.length} images favorited`}
                            aria-pressed={showFavorites}
                            type="button"
                        >
                            <Star size={16} className={showFavorites ? 'fill-current' : ''} aria-hidden="true" />
                            <span>Favorites</span>
                            {favorites.length > 0 && (
                                <span className="px-1.5 py-0.5 bg-yellow-500/30 rounded text-xs font-medium">{favorites.length}</span>
                            )}
                        </button>

                        <button
                            onClick={() => setShowCollectionsPanel(true)}
                            className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors text-sm ${activeCollection ? 'bg-purple-500/20 text-purple-400 border border-purple-500/30' : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-purple-400 border border-gray-700'}`}
                            title={activeCollection && collections[activeCollection] ? `Viewing collection: ${collections[activeCollection].name}` : 'Browse collections'}
                            aria-label={activeCollection && collections[activeCollection] ? `Currently viewing ${collections[activeCollection].name} collection. Click to manage collections` : 'Open collections panel to organize images'}
                            aria-pressed={!!activeCollection}
                            type="button"
                        >
                            <FolderOpen size={16} aria-hidden="true" />
                            <span className="hidden sm:inline">
                                {activeCollection && collections[activeCollection] ? collections[activeCollection].name : 'Collections'}
                            </span>
                            <span className="sm:hidden">Collections</span>
                        </button>

                        <div className="flex-1" />

                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => setShowStatsPanel(true)}
                                className="p-2 bg-gray-800 rounded-lg hover:bg-gray-700 text-gray-400 hover:text-white transition-colors"
                                title="View Statistics"
                                aria-label="View generation statistics and analytics"
                                type="button"
                            >
                                <BarChart3 size={20} aria-hidden="true" />
                            </button>
                            <button
                                onClick={() => {
                                    setConfirmModal({
                                        isOpen: true,
                                        title: 'Clear Job History',
                                        message: 'Are you sure you want to clear all job history? This will remove all job records but keep the generated images.',
                                        isDangerous: true,
                                        confirmText: 'Clear History',
                                        onConfirm: async () => {
                                            await clearJobs();
                                            refetch();
                                        }
                                    });
                                }}
                                className="p-2 bg-gray-800 rounded-lg hover:bg-gray-700 text-gray-400 hover:text-white transition-colors"
                                title="Clear Job History"
                                aria-label="Clear Job History"
                                type="button"
                            >
                                <Trash2 size={20} aria-hidden="true" />
                            </button>
                        </div>
                    </div>

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

                {/* Content */}
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
                    // Timeline View - doesn't need date grouping since TimelineView handles it
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

                {/* Infinite Scroll Sentinel */}
                <div ref={sentinelRef} className="h-4" />

                {/* Infinite Scroll Loading Indicator */}
                {isFetchingNextPage && (
                    <div className="flex justify-center py-8">
                        <Loader2 className="animate-spin text-gray-400" size={32} />
                    </div>
                )}
            </div>

            {/* Lightbox - Using Enhanced ImageLightbox Component */}
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
                />
            )}

            {/* Job Details Modal */}
            {selectedJob && (
                <JobDetailsModal
                    job={selectedJob}
                    onClose={handleJobDetailsClose}
                    onCancel={cancelJob}
                    onDelete={deleteJob}
                    onRetry={retryJob}
                />
            )}

            {/* Confirmation Modal */}
            <ConfirmationModal
                isOpen={confirmModal.isOpen}
                title={confirmModal.title}
                message={confirmModal.message}
                isDangerous={confirmModal.isDangerous}
                confirmText={confirmModal.confirmText}
                onConfirm={confirmModal.onConfirm}
                onCancel={() => setConfirmModal((prev) => ({ ...prev, isOpen: false }))}
            />

            {/* Image Comparison Modal */}
            {showComparison && (
                <ImageComparison
                    images={allItems.filter(item => selectedFiles.has(item.name))}
                    onClose={() => setShowComparison(false)}
                />
            )}

            {/* Collections Panel */}
            <CollectionsPanel
                isOpen={showCollectionsPanel}
                onClose={() => setShowCollectionsPanel(false)}
            />

            {/* Quick Nav to Generator (Mobile) */}
            <button
                onClick={() => navigate('/generate')}
                className="fixed bottom-6 right-6 z-40 md:hidden bg-blue-600 hover:bg-blue-500 text-white p-4 rounded-full shadow-lg transition-all transform hover:scale-110 flex items-center gap-2"
                title="Go to Generator"
                aria-label="Go to Generator"
            >
                <ImageIcon size={24} />
            </button>

            {/* Select Collection Modal */}
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

            {/* Statistics Panel */}
            <StatsPanel
                isOpen={showStatsPanel}
                onClose={() => setShowStatsPanel(false)}
            />


        </motion.div>
    );
}

