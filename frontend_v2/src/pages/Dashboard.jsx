import React, { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import { Image as ImageIcon, Loader2, Trash2, RefreshCw, Check, Calendar, LayoutGrid, List, Square, Star, FolderOpen, BarChart3, LineChart } from 'lucide-react';
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
import JobCard from '../components/dashboard/JobCard';
import ImageGroup from '../components/dashboard/ImageGroup';
import FeedCard from '../components/dashboard/FeedCard';
import ConfirmationModal from '../components/ConfirmationModal';
import { useSettings } from '../store/settingsStore';
import useSettingsStore from '../store/settingsStore';

import { FilterBar } from '../components/dashboard/FilterBar';
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
import ProgressiveImage from '../components/ProgressiveImage';
import QueueVisualization from '../components/QueueVisualization';
import { usePullToRefresh, PullToRefreshIndicator } from '../hooks/usePullToRefresh';

export default function Dashboard() {

    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const settings = useSettings();
    const _motion = motion;

    // Global State - now uses WebSocket for real-time updates
    const { connect, jobs: activeJobs, clearJobs, deleteJob: storeDeleteJob, retryJob, cancelJob } = useJobStore();
    const { favorites, toggleFavorite, isFavorite, collections, activeCollection, addToCollection, removeFromCollection, setActiveCollection } = useStore();

    // Wrapped deleteJob to handle query invalidation
    const deleteJob = useCallback(async (jobId) => {
        await storeDeleteJob(jobId);
        queryClient.invalidateQueries(['gallery']);
    }, [storeDeleteJob, queryClient]);
    // Local State
    const [viewMode, setViewMode] = useState(() => localStorage.getItem('galleryViewMode') || settings.ui.defaultViewMode);
    const [selectedJobId, setSelectedJobId] = useState(null);  // Store ID, not object
    const [gridCols, setGridCols] = useState(settings.ui.defaultGridColumns);
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
    // Stable handler for toggling favorite
    const handleToggleFavorite = useCallback((filename) => {
        toggleFavorite(filename);
        toast.success(
            isFavorite(filename) ? "Removed from favorites" : "Added to favorites",
            { icon: isFavorite(filename) ? '*' : '*' }
        );
    }, [toggleFavorite, isFavorite]);

    // Stable handler for job click
    const handleJobClick = useCallback((job) => {
        const jobId = typeof job === 'string' ? job : job?.id;
        if (jobId) setSelectedJobId(jobId);
    }, []);

    // Stable handler for image click
    const handleImageClick = useCallback((image) => {
        selectImage(image);
    }, [selectImage]);

    // Confirmation Modal
    const [confirmModal, setConfirmModal] = useState({
        isOpen: false,
        title: '',
        message: '',
        onConfirm: () => { },
        isDangerous: false
    });

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

    // Connect to WebSocket on mount and refetch gallery
    // Note: We don't disconnect on unmount because WebSocket is a global singleton
    // and React StrictMode double-renders would cause connection issues
    useEffect(() => {
        connect();
        // Refetch gallery on mount to ensure fresh data
        refetch();
        // No cleanup - WebSocket connection persists across component lifecycle
    }, [connect, refetch]);

    // Auto-refresh gallery when any job completes
    // Use lastCompletedJob from store which gets set when job.completed WebSocket event fires
    const lastCompletedJob = useJobStore(state => state.lastCompletedJob);
    
    useEffect(() => {
        if (lastCompletedJob && lastCompletedJob.outputs && lastCompletedJob.outputs.length > 0) {
            // Check if this is a new completion we haven't handled yet
            if (lastCompletedJobRef.current !== lastCompletedJob.id) {
                lastCompletedJobRef.current = lastCompletedJob.id;
                if (settings.gallery.autoRefreshOnJobComplete) {
                    // Invalidate all gallery queries regardless of filters
                    queryClient.invalidateQueries({ queryKey: ['gallery'] });
                    // Also trigger immediate refetch
                    refetch();
                    toast.success("🎉 Generation complete! Gallery updated.", {
                        duration: settings.ui.toastSuccessDuration,
                    });
                }
            }
        }
    }, [lastCompletedJob, queryClient, refetch, settings.gallery.autoRefreshOnJobComplete, settings.ui.toastSuccessDuration]);

    // Keyboard shortcuts (ESC to close modals)
    useKeyboardShortcuts({
        onEscape: () => {
            if (selectedImage) closeSelectedImage();
            else if (selectedJob) setSelectedJobId(null);
        }
    });

    // Persist View Mode
    useEffect(() => {
        localStorage.setItem('galleryViewMode', viewMode);
    }, [viewMode]);

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
            title: "Delete Image",
            message: `Are you sure you want to delete ${filename}? This action cannot be undone.`,
            isDangerous: true,
            confirmText: "Delete",
            onConfirm: async () => {
                try {
                    await filesApi.deleteMultiple([filename]);
                    queryClient.invalidateQueries(['gallery']);
                    if (selectedImage?.name === filename) closeSelectedImage();
                    toast.success(`Successfully deleted ${filename}`, {
                        icon: '🗑️',
                        duration: settings.ui.toastSuccessDuration,
                    });
                } catch (e) {
                    toast.error(`Failed to delete: ${e.message}`, {
                        icon: '❌',
                        duration: settings.ui.toastErrorDuration,
                    });
                }
            }
        });
    }, [selectedImage, queryClient, settings.ui.toastErrorDuration, settings.ui.toastSuccessDuration]);

    // Load parameters from metadata (reuse parameters)
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

        // Disable auto-randomize seed to allow reproduction of the same image
        useSettingsStore.getState().updateSetting('generator', 'autoRandomizeSeed', false);

        toast.success('Parameters loaded! Auto-randomize seed disabled for reproduction.', {
            icon: '🎯',
            duration: settings.ui.toastSuccessDuration
        });
        navigate('/generate');
    }, [metadata, navigate, settings.ui.toastSuccessDuration]);

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
            title: "Download Images",
            message: `Download ${selectedFiles.size} images to your computer?`,
            isDangerous: false,
            confirmText: "Download",
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
    }, [selectedFiles, setConfirmModal, setSelectionMode, setSelectedFiles]);

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
                    queryClient.invalidateQueries(['gallery']);
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

    // Pull to Refresh
    const { containerRef, pullDistance, isRefreshing, isPulling } = usePullToRefresh({
        onRefresh: async () => {
            await refetch();
            // Wait a bit to show success state
            await new Promise(resolve => setTimeout(resolve, 500));
        },
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
                {/* Queue Visualization - Shows pending/running jobs with ETA */}
                <QueueVisualization onJobClick={(jobId) => {
                    const job = activeJobs.find(j => j.id === jobId);
                    if (job) setSelectedJobId(job.id);
                }} />

                {/* Header */}
                <div className="flex flex-col gap-4">
                    {/* Main Header Row */}
                    <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                        {/* Title */}
                        <div>
                            <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-500">
                                Gallery
                            </h1>
                            <p className="text-gray-400 mt-1 text-sm">Your generations and active jobs</p>
                        </div>

                        {/* Primary Actions (Always Visible) */}
                        <div className="flex items-center gap-2 flex-wrap">
                            {/* View Mode Selector */}
                            <div className="bg-gray-800 rounded-lg p-1 flex gap-1">
                                {['grid', 'list', 'feed', 'timeline'].map(mode => (
                                    <button
                                        key={mode}
                                        onClick={() => setViewMode(mode)}
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

                            {/* Grid Size Slider (when in grid mode) */}
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

                            {/* Divider */}
                            <div className="hidden sm:block h-6 w-px bg-gray-700" />

                            {/* Selection Mode Toggle */}
                            <motion.button
                                whileHover={{ scale: 1.02 }}
                                whileTap={{ scale: 0.98 }}
                                onClick={() => {
                                    setSelectionMode(!selectionMode);
                                    if (selectionMode) {
                                        setSelectedFiles(new Set());
                                    }
                                }}
                                className={`px-4 py-2 rounded-lg font-medium transition-all flex items-center gap-2 ${selectionMode
                                    ? 'bg-blue-600 text-white hover:bg-blue-500'
                                    : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                                    }`}
                                type="button"
                                aria-pressed={selectionMode}
                                aria-label={selectionMode ? "Exit selection mode" : "Enter selection mode to select multiple images"}
                            >
                                <Check size={16} aria-hidden="true" />
                                <span className="hidden sm:inline">{selectionMode ? `Selected (${selectedFiles.size})` : 'Select'}</span>
                                <span className="sm:hidden">{selectedFiles.size > 0 ? selectedFiles.size : 'Select'}</span>
                            </motion.button>

                            {/* Utility Actions */}
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

                    {/* Filter Bar (Second Row) */}
                    <div className="flex items-center gap-2 flex-wrap">
                        {/* Favorites Filter */}
                        <button
                            onClick={() => setShowFavorites(!showFavorites)}
                            className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors text-sm ${showFavorites
                                ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
                                : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-yellow-400 border border-gray-700'
                                }`}
                            title={showFavorites ? "Show All Images" : "Show Favorites Only"}
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

                        {/* Collections Filter */}
                        <button
                            onClick={() => setShowCollectionsPanel(true)}
                            className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors text-sm ${activeCollection
                                ? 'bg-purple-500/20 text-purple-400 border border-purple-500/30'
                                : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-purple-400 border border-gray-700'
                                }`}
                            title={activeCollection && collections[activeCollection] ? `Viewing collection: ${collections[activeCollection].name}` : "Browse collections"}
                            aria-label={activeCollection && collections[activeCollection] ? `Currently viewing ${collections[activeCollection].name} collection. Click to manage collections` : "Open collections panel to organize images"}
                            aria-pressed={!!activeCollection}
                            type="button"
                        >
                            <FolderOpen size={16} aria-hidden="true" />
                            <span className="hidden sm:inline">
                                {activeCollection && collections[activeCollection] ? collections[activeCollection].name : 'Collections'}
                            </span>
                            <span className="sm:hidden">Collections</span>
                        </button>

                        {/* Spacer */}
                        <div className="flex-1" />

                        {/* Secondary Actions */}
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
                                        title: "Clear Job History",
                                        message: "Are you sure you want to clear all job history? This will remove all job records but keep the generated images.",
                                        isDangerous: true,
                                        confirmText: "Clear History",
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

                    {/* Selection Mode Toolbar (Sticky when active) */}
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
                            isFavorite={isFavorite}
                            onToggleFavorite={handleToggleFavorite}
                        />
                    ) : (
                        <div className="space-y-8">
                            {viewMode === 'grid' ? (
                                sortedGroupedEntries.map(([date, groupItems]) => (
                                    <div key={date}>
                                        <h3 className="text-gray-500 font-medium mb-4 flex items-center gap-2">
                                            <Calendar size={16} /> {formatDateLabel(date)}
                                        </h3>
                                        <div
                                            className="grid gap-4"
                                            style={{ gridTemplateColumns: `repeat(${gridCols}, minmax(0, 1fr))` }}
                                        >
                                            {groupItems.map((item) => (
                                                <motion.div
                                                    initial={{ opacity: 0, scale: 0.96 }}
                                                    animate={{ opacity: 1, scale: 1 }}
                                                    transition={{ duration: 0.18 }}
                                                    key={item.id || item.name}
                                                >
                                                    {item.type === 'job' ? (
                                                        <JobCard job={item} onClick={handleJobClick} />
                                                    ) : item.type === 'imageGroup' ? (
                                                        <ImageGroup
                                                            images={item.images}
                                                            job={item.job}
                                                            isSelected={item.images.some(img => selectedFiles.has(img.name))}
                                                            showSelectionCheckbox={selectionMode}
                                                            onSelectionToggle={() => {
                                                                item.images.forEach(img => toggleSelection(img.name));
                                                            }}
                                                            onClick={handleImageClick}
                                                        />
                                                    ) : (
                                                        <div
                                                            className={`group relative aspect-square bg-gray-800 rounded-xl overflow-hidden border transition-all ${selectedFiles.has(item.name) ? 'border-blue-500 ring-2 ring-blue-500/50' : 'border-gray-800 hover:border-gray-600'}`}
                                                            onClick={() => {
                                                                if (selectionMode) toggleSelection(item.name);
                                                                else handleImageClick(item);
                                                            }}
                                                            role="img"
                                                            aria-label={item.prompt ? `AI generated image: ${item.prompt.slice(0, 100)}${item.prompt.length > 100 ? '...' : ''}` : `Generated image ${item.name}`}
                                                        >
                                                            <div className="aspect-square bg-gray-800 rounded-xl overflow-hidden group relative">
                                                                <ProgressiveImage
                                                                    blurhash={item.blurhash}
                                                                    src={`/api/view/output/${item.name}`}
                                                                    medium={item.thumbnail_medium || `/api/thumbnail/medium/${item.name}`}
                                                                    alt={item.name}
                                                                    size="medium"
                                                                    className="w-full h-full"
                                                                />
                                                                <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200" />
                                                                {isFavorite(item.name) && (
                                                                    <div className="absolute top-2 right-2 text-yellow-400">
                                                                        <Star size={20} fill="currentColor" />
                                                                    </div>
                                                                )}
                                                            </div>
                                                            {selectionMode && (
                                                                <div className={`absolute top-2 right-2 p-1.5 rounded-full ${selectedFiles.has(item.name) ? 'bg-blue-500 text-white' : 'bg-black/50 text-gray-400'}`}>
                                                                    <Check size={14} />
                                                                </div>
                                                            )}

                                                            {!selectionMode && (
                                                                <button
                                                                    onClick={(e) => {
                                                                        e.stopPropagation();
                                                                        toggleFavorite(item.name);
                                                                        toast.success(
                                                                            isFavorite(item.name) ? "Removed from favorites" : "Added to favorites",
                                                                            { icon: isFavorite(item.name) ? '💔' : '⭐' }
                                                                        );
                                                                    }}
                                                                    className="absolute top-2 right-2 p-1.5 rounded-full bg-black/50 hover:bg-black/70 backdrop-blur-sm opacity-0 group-hover:opacity-100 transition-opacity"
                                                                    title={isFavorite(item.name) ? 'Remove from favorites' : 'Add to favorites'}
                                                                    aria-label={isFavorite(item.name) ? 'Remove from favorites' : 'Add to favorites'}
                                                                >
                                                                    <Star
                                                                        size={16}
                                                                        className={isFavorite(item.name) ? 'fill-yellow-400 text-yellow-400' : 'text-gray-300'}
                                                                    />
                                                                </button>
                                                            )}
                                                        </div>
                                                    )}
                                                </motion.div>
                                            ))}
                                        </div>
                                    </div>
                                ))
                            ) : (
                                sortedGroupedEntries.map(([date, groupItems]) => (
                                <div key={date}>
                                    <h3 className="text-gray-500 font-medium mb-4 flex items-center gap-2">
                                        <Calendar size={16} /> {formatDateLabel(date)}
                                    </h3>
                                    {viewMode === 'list' ? (
                                        <div className="space-y-2">
                                            {groupItems.map((item) => (
                                                item.type === 'job' ? (
                                                    <JobCard key={item.id} job={item} onClick={handleJobClick} />
                                                ) : item.type === 'imageGroup' ? (
                                                    <div
                                                        key={item.id}
                                                        className={`flex items-center gap-4 bg-gray-800/50 p-3 rounded-lg border transition-colors cursor-pointer ${item.images.some(img => selectedFiles.has(img.name)) ? 'border-blue-500 bg-blue-900/10' : 'border-gray-700 hover:bg-gray-800'}`}
                                                        onClick={() => handleImageClick({ ...item.images[0], siblingImages: item.images, associatedJob: item.job })}
                                                    >
                                                        {selectionMode && (
                                                            <div
                                                                className={`w-5 h-5 rounded border flex items-center justify-center ${item.images.some(img => selectedFiles.has(img.name)) ? 'bg-blue-500 border-blue-500' : 'border-gray-600'}`}
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    item.images.forEach(img => toggleSelection(img.name));
                                                                }}
                                                            >
                                                                {item.images.some(img => selectedFiles.has(img.name)) && <Check size={12} />}
                                                            </div>
                                                        )}
                                                        <div className="relative flex-shrink-0 w-32">
                                                            {/* Stacked preview */}
                                                            <div className="relative bg-gray-800 rounded-lg overflow-hidden">
                                                                <ProgressiveImage
                                                                    blurhash={item.images[0].blurhash}
                                                                    src={`/api/view/output/${item.images[0].name}`}
                                                                    medium={item.images[0].thumbnail_medium || `/api/thumbnail/medium/${item.images[0].name}`}
                                                                    alt={item.images[0].name}
                                                                    size="medium"
                                                                    aspectRatio="auto"
                                                                    className="w-full"
                                                                />
                                                            </div>
                                                            <div className="absolute -bottom-1 -right-1 bg-purple-500 text-white text-xs px-1.5 py-0.5 rounded font-medium">
                                                                {item.images.length}
                                                            </div>
                                                        </div>
                                                        <div className="flex-1 min-w-0">
                                                            <h4 className="text-sm font-medium text-white truncate">{item.images.length} images</h4>
                                                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1 text-xs text-gray-400">

                                                                <span>
                                                                    {(() => {
                                                                        const timestamp = item.date || item.mtime;
                                                                        if (!timestamp) return "Unknown date";
                                                                        let date;
                                                                        if (typeof timestamp === 'string') {
                                                                            date = new Date(timestamp.endsWith('Z') ? timestamp : timestamp + 'Z');
                                                                        } else if (timestamp > 1e12) {
                                                                            date = new Date(timestamp);
                                                                        } else if (timestamp > 0) {
                                                                            date = new Date(timestamp * 1000);
                                                                        } else {
                                                                            return "Unknown date";
                                                                        }
                                                                        return isNaN(date.getTime()) ? "Unknown date" : date.toLocaleString();
                                                                    })()}
                                                                </span>
                                                            </div>
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <div
                                                        key={item.name}
                                                        className={`flex items-center gap-4 bg-gray-800/50 p-3 rounded-lg border transition-colors cursor-pointer ${selectedFiles.has(item.name) ? 'border-blue-500 bg-blue-900/10' : 'border-gray-700 hover:bg-gray-800'}`}
                                                        onClick={() => {
                                                            if (selectionMode) toggleSelection(item.name);
                                                            else handleImageClick(item);
                                                        }}
                                                    >
                                                        {selectionMode && (
                                                            <div className={`w-5 h-5 rounded border flex items-center justify-center ${selectedFiles.has(item.name) ? 'bg-blue-500 border-blue-500' : 'border-gray-600'}`}>
                                                                {selectedFiles.has(item.name) && <Check size={12} />}
                                                            </div>
                                                        )}
                                                        <div onClick={() => handleImageClick(item)} className="flex-shrink-0 w-32 bg-gray-800 rounded-lg overflow-hidden cursor-pointer hover:ring-2 hover:ring-blue-500 transition-all">
                                                            <ProgressiveImage
                                                                blurhash={item.blurhash}
                                                                src={`/api/view/output/${item.name}`}
                                                                medium={item.thumbnail_medium || `/api/thumbnail/medium/${item.name}`}
                                                                alt={item.name}
                                                                size="medium"
                                                                aspectRatio="auto"
                                                                className="w-full"
                                                            />
                                                        </div>
                                                        <div className="flex-1 min-w-0">
                                                            <h4 className="text-sm font-medium text-white truncate">{item.name}</h4>
                                                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1 text-xs text-gray-400">
                                                                <span>{(item.size / 1024 / 1024).toFixed(2)} MB</span>
                                                                <span>
                                                                    {(() => {
                                                                        const timestamp = item.date || item.mtime;
                                                                        if (!timestamp || timestamp <= 0) return "Unknown date";
                                                                        const date = new Date(timestamp * 1000);
                                                                        return isNaN(date.getTime()) ? "Unknown date" : date.toLocaleString();
                                                                    })()}
                                                                </span>
                                                            </div>
                                                        </div>
                                                    </div>
                                                )
                                            ))}
                                        </div>
                                    ) : (
                                        <div className="space-y-8 max-w-3xl mx-auto">
                                            {groupItems.map((item) => (
                                                item.type === 'job' ? (
                                                    <JobCard key={item.id} job={item} onClick={handleJobClick} />
                                                ) : item.type === 'imageGroup' ? (
                                                    <div key={item.id} className="bg-gray-800/50 rounded-xl p-4 border border-gray-700">
                                                        <div className="flex items-center gap-2 mb-3">
                                                            <span className="text-sm text-gray-400">{item.images.length} images from batch</span>

                                                        </div>
                                                        <div className="grid grid-cols-2 gap-2">
                                                            {item.images.map((img) => (
                                                                <div
                                                                    key={img.name}
                                                                    className="aspect-square bg-gray-700 rounded-lg overflow-hidden cursor-pointer hover:ring-2 hover:ring-purple-500 transition-all"
                                                                    onClick={() => handleImageClick({ ...img, siblingImages: item.images, associatedJob: item.job })}
                                                                >
                                                                    <ProgressiveImage
                                                                        blurhash={img.blurhash}
                                                                        src={`/api/view/output/${img.name}`}
                                                                        medium={img.thumbnail_medium || `/api/thumbnail/medium/${img.name}`}
                                                                        alt={img.name}
                                                                        size="medium"
                                                                        className="w-full h-full"
                                                                    />
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <FeedCard
                                                        key={item.name}
                                                        item={item}
                                                        selected={selectedFiles.has(item.name)}
                                                        onSelect={toggleSelection}
                                                        onClick={handleImageClick}
                                                        selectionMode={selectionMode}
                                                        onDelete={handleDelete}
                                                    />
                                                )
                                            ))}
                                        </div>
                                    )}
                                </div>
                            ))
                            )}
                        </div>
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
                    images={selectedImage.siblingImages || [selectedImage]}
                    currentIndex={selectedImage.siblingImages?.findIndex(img => img.name === selectedImage.name) || 0}
                    onNavigate={(newIndex) => {
                        if (selectedImage.siblingImages?.[newIndex]) {
                            selectImage({
                                ...selectedImage.siblingImages[newIndex],
                                siblingImages: selectedImage.siblingImages,
                                associatedJob: selectedImage.associatedJob
                            });
                        }
                    }}
                    metadata={metadata}
                    loadingMeta={loadingMeta}
                    job={selectedImage.associatedJob}
                    onClose={closeSelectedImage}
                    onDelete={(name) => handleDelete(name)}
                    onReuseParameters={useParameters}
                />
            )}

            {/* Job Details Modal */}
            {selectedJob && (
                <JobDetailsModal
                    job={selectedJob}
                    onClose={() => setSelectedJobId(null)}
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
                onCancel={() => setConfirmModal({ ...confirmModal, isOpen: false })}
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

