import React, { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import { Image as ImageIcon, Loader2, X, Download, Trash2, RefreshCw, Check, Calendar, LayoutGrid, List, Square, ChevronDown, ArrowLeftRight, Star, FolderOpen, Plus, BarChart3, LineChart } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { VirtuosoGrid } from 'react-virtuoso';

// API Layer
import { filesApi, getApiUrl } from '../api';

import { useGallery } from '../hooks/useGallery';
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

const GridList = React.forwardRef(({ style, children, context, ...props }, ref) => (
    <div
        ref={ref}
        {...props}
        className="grid gap-4 pb-20"
        style={{ ...style, gridTemplateColumns: `repeat(${context.gridCols}, minmax(0, 1fr))` }}
    >
        {children}
    </div>
));

const GridItem = React.forwardRef(({ children, ...props }, ref) => {
    const isHeader = children?.props?.className?.includes('date-header-marker');
    return (
        <div ref={ref} {...props} style={{ ...props.style, gridColumn: isHeader ? '1 / -1' : undefined }}>
            {children}
        </div>
    );
});
GridItem.displayName = 'GridItem';


// Helper to generate a local date key
const getLocalDateKey = (dateObj) => {
    const year = dateObj.getFullYear();
    const month = String(dateObj.getMonth() + 1).padStart(2, '0');
    const day = String(dateObj.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
};

export default function Dashboard() {

    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const settings = useSettings();

    // Global State - now uses WebSocket for real-time updates
    const { connect, disconnect, jobs: activeJobs, clearJobs, deleteJob: storeDeleteJob, retryJob, cancelJob } = useJobStore();
    const { favorites, toggleFavorite, isFavorite, collections, activeCollection, addToCollection, removeFromCollection, setActiveCollection } = useStore();

    // Wrapped deleteJob to handle query invalidation
    const deleteJob = useCallback(async (jobId) => {
        await storeDeleteJob(jobId);
        queryClient.invalidateQueries(['gallery']);
    }, [storeDeleteJob, queryClient]);

    // Stable handler for toggling favorite
    const handleToggleFavorite = useCallback((filename) => {
        toggleFavorite(filename);
        toast.success(
            isFavorite(filename) ? "Removed from favorites" : "Added to favorites",
            { icon: isFavorite(filename) ? '💔' : '⭐' }
        );
    }, [toggleFavorite, isFavorite]);

    // Stable handler for job click
    const handleJobClick = useCallback((job) => {
        const jobId = typeof job === 'string' ? job : job?.id;
        if (jobId) setSelectedJobId(jobId);
    }, []);

    // Stable handler for image click
    const handleImageClick = useCallback((image) => {
        setSelectedImage(image);
    }, []);

    // Local State
    const [viewMode, setViewMode] = useState(() => localStorage.getItem('galleryViewMode') || settings.ui.defaultViewMode);
    const [selectedImage, setSelectedImage] = useState(null);
    const [selectedJobId, setSelectedJobId] = useState(null);  // Store ID, not object
    const [gridCols, setGridCols] = useState(settings.ui.defaultGridColumns);
    const [metadata, setMetadata] = useState(null);
    const [loadingMeta, setLoadingMeta] = useState(false);
    const [showCollectionsPanel, setShowCollectionsPanel] = useState(false);
    const [showSelectCollection, setShowSelectCollection] = useState(false);
    const [showStatsPanel, setShowStatsPanel] = useState(false);

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

    // Derive selectedJob from activeJobs to get live updates
    const selectedJob = selectedJobId ? activeJobs.find(j => j.id === selectedJobId) : null;

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

    // Note: Mobile polling fallback removed - WebSocket handles reconnection reliably
    const { fetchJobs } = useJobStore();

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
            if (selectedImage) setSelectedImage(null);
            else if (selectedJob) setSelectedJobId(null);
        }
    });

    // Persist View Mode
    useEffect(() => {
        localStorage.setItem('galleryViewMode', viewMode);
    }, [viewMode]);

    // Flatten data and merge with real-time updates
    const allItems = useMemo(() => {
        const historicalFiles = data ? data.pages.flatMap(page => page.files.map(f => ({ ...f, type: 'image', date: f.date || f.mtime }))) : [];
        const historicalJobs = data ? data.pages.flatMap(page => page.jobs.map(j => ({ ...j, type: 'job', date: j.created_at || j.updated_at || (Date.now() / 1000) }))) : [];

        // Create a map of WebSocket jobs for easy lookup
        // activeJobs comes from the store (WebSocket) and contains the latest state of all jobs
        const activeJobsMap = new Map(activeJobs.map(j => [j.id, { ...j, type: 'job', date: j.created_at || j.updated_at || (Date.now() / 1000) }]));

        // Merge jobs: Use active job if available, otherwise use historical
        const mergedJobs = new Map();
        historicalJobs.forEach(j => mergedJobs.set(j.id, j));
        activeJobsMap.forEach((j, id) => mergedJobs.set(id, j));

        // Group images by job_id from metadata
        const imagesByJobId = new Map();
        historicalFiles.forEach(img => {
            const jobId = img.metadata?.job_id;
            if (jobId) {
                if (!imagesByJobId.has(jobId)) {
                    imagesByJobId.set(jobId, []);
                }
                imagesByJobId.get(jobId).push(img);
            }
        });

        // Build combined list
        const jobsArray = Array.from(mergedJobs.values());
        const combined = [];
        const usedImages = new Set();
        const usedJobIds = new Set();

        // First pass: Handle jobs
        jobsArray.forEach(job => {
            if (job.status === 'completed' && job.outputs && job.outputs.length > 0) {
                // Check if this job has grouped images
                const groupedImages = imagesByJobId.get(job.id);

                if (groupedImages && groupedImages.length > 1) {
                    // Multiple images - create a group
                    combined.push({
                        type: 'imageGroup',
                        images: groupedImages,
                        job: job,
                        date: job.created_at || groupedImages[0].date,
                        id: `group-${job.id}`
                    });
                    groupedImages.forEach(img => usedImages.add(img.name));
                    usedJobIds.add(job.id);
                } else if (groupedImages && groupedImages.length === 1) {
                    // Single image with job_id match - show as regular image
                    const img = groupedImages[0];
                    combined.push({
                        ...img,
                        type: 'image',
                        date: job.created_at || img.date,
                        _replacedJobId: job.id,
                        _job: job
                    });
                    usedImages.add(img.name);
                    usedJobIds.add(job.id);
                } else {
                    // Fallback: Find by output filename
                    const outputFilename = job.outputs[0];
                    const matchingImage = historicalFiles.find(img => img.name === outputFilename);
                    if (matchingImage && !usedImages.has(matchingImage.name)) {
                        combined.push({
                            ...matchingImage,
                            type: 'image',
                            date: job.created_at || matchingImage.date,
                            _replacedJobId: job.id,
                            _job: job
                        });
                        usedImages.add(matchingImage.name);
                    }
                }
            } else if (job.status !== 'completed') {
                // Keep non-completed jobs (pending, processing, failed)
                combined.push(job);
            }
        });

        // Second pass: Add remaining images not associated with any job
        historicalFiles.forEach(img => {
            if (!usedImages.has(img.name)) {
                // Check if this image is part of a group that wasn't handled
                const jobId = img.metadata?.job_id;
                if (jobId && !usedJobIds.has(jobId)) {
                    // This image has a job_id but the job wasn't in our list
                    // Check if we already created a group for this job_id
                    const existingGroup = combined.find(item => item.type === 'imageGroup' && item.id === `group-${jobId}`);
                    if (!existingGroup) {
                        const groupedImages = imagesByJobId.get(jobId);
                        if (groupedImages && groupedImages.length > 1) {
                            // Create a group without job info
                            combined.push({
                                type: 'imageGroup',
                                images: groupedImages,
                                job: null,
                                date: groupedImages[0].date,
                                id: `group-${jobId}`
                            });
                            groupedImages.forEach(i => usedImages.add(i.name));
                            usedJobIds.add(jobId);
                        } else {
                            combined.push(img);
                            usedImages.add(img.name);
                        }
                    }
                } else if (!jobId) {
                    // No job_id, just add the image
                    combined.push(img);
                }
            }
        });

        // Sort by date descending (newest first)
        const parseDate = (date) => {
            if (typeof date === 'string') {
                const isoDate = date.endsWith('Z') || date.includes('+') || date.includes('-', 10)
                    ? date
                    : date + 'Z';
                return new Date(isoDate);
            }
            return new Date((date || 0) * 1000);
        };

        const sorted = combined.sort((a, b) => {
            const dateA = parseDate(a.date);
            const dateB = parseDate(b.date);
            return dateB - dateA;
        });

        return sorted;
    }, [data, activeJobs, showFavorites, favorites]);

    // Filter for favorites and collections
    const displayedItems = useMemo(() => {
        let items = allItems;

        // Apply collection filter
        if (activeCollection && collections[activeCollection]) {
            const collectionImages = collections[activeCollection].images;
            items = items.filter(item => item.type === 'image' && collectionImages.includes(item.name));
        }

        // Apply favorites filter
        if (showFavorites) {
            items = items.filter(item => item.type === 'image' && favorites.includes(item.name));
        }
        return items;
    }, [allItems, showFavorites, favorites, activeCollection, collections]);

    // Group by Date - handle both ISO strings and UNIX timestamps
    // Use local-based date keys to ensure consistent grouping relative to user's timezone
    const grouped = useMemo(() => {
        return displayedItems.reduce((acc, item) => {
            let dateValue = item.date || item.mtime || Date.now() / 1000;
            // If it's an ISO string (from V2 backend), parse directly
            // If it's a number (UNIX timestamp), multiply by 1000
            let dateObj;
            if (typeof dateValue === 'string') {
                dateObj = new Date(dateValue); // ISO string
            } else {
                dateObj = new Date(dateValue * 1000); // UNIX timestamp
            }
            // Use local date as key
            // Format: YYYY-MM-DD (e.g., "2024-12-09")
            const d = getLocalDateKey(dateObj);
            if (!acc[d]) acc[d] = [];
            acc[d].push(item);
            return acc;
        }, {});
    }, [displayedItems]);

    const flattenedGridItems = useMemo(() => {
        const flat = [];
        Object.entries(grouped)
            .sort(([dateA], [dateB]) => new Date(dateB).getTime() - new Date(dateA).getTime())
            .forEach(([date, groupItems]) => {
                flat.push({ isHeader: true, date, id: `header-${date}` });
                groupItems.forEach(item => flat.push(item));
            });
        return flat;
    }, [grouped]);

    // Helper to format date keys for display
    const formatDateLabel = (localDateKey) => {
        const [year, month, day] = localDateKey.split('-');
        const date = new Date(year, month - 1, day);

        const today = new Date();
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);

        // Compare local dates
        const todayKey = getLocalDateKey(today);
        const yesterdayKey = getLocalDateKey(yesterday);

        if (localDateKey === todayKey) return 'Today';
        if (localDateKey === yesterdayKey) return 'Yesterday';
        return date.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
    };


    // Metadata Fetching for Lightbox
    // Priority: 1) Use metadata already loaded from file list, 2) Fallback to API for legacy images
    useEffect(() => {
        if (selectedImage) {
            // Use metadata from file listing if available (new system with embedded PNG metadata)
            if (selectedImage.metadata && Object.keys(selectedImage.metadata).length > 0) {
                setMetadata(selectedImage.metadata);
                setLoadingMeta(false);
            } else {
                // Fallback: fetch from legacy sidecar JSON or dedicated endpoint
                setLoadingMeta(true);
                setMetadata(null);
                fetch(`/api/view/output/${selectedImage.name}.json`)
                    .then(res => res.ok ? res.json() : null)
                    .then(data => {
                        setMetadata(data);
                        setLoadingMeta(false);
                    })
                    .catch(() => setLoadingMeta(false));
            }
        }
    }, [selectedImage]);

    // Lock Scroll
    useEffect(() => {
        document.body.style.overflow = selectedImage ? 'hidden' : 'unset';
        return () => { document.body.style.overflow = 'unset'; };
    }, [selectedImage]);

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
                    if (selectedImage?.name === filename) setSelectedImage(null);
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
    }, [selectedImage, queryClient]);

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

    const handleBatchDelete = useCallback(() => {
        setConfirmModal({
            isOpen: true,
            title: "Delete Multiple Images",
            message: `Are you sure you want to delete ${selectedFiles.size} images? This action cannot be undone.`,
            isDangerous: true,
            confirmText: `Delete ${selectedFiles.size} Images`,
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
    }, [selectedFiles, queryClient]);

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
                            <motion.div
                                initial={{ opacity: 0, y: -10 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, y: -10 }}
                                transition={{ duration: 0.2 }}
                                className="flex items-center gap-2 p-3 bg-blue-900/20 border border-blue-500/30 rounded-lg flex-wrap"
                            >
                                <span className="text-sm text-blue-300 font-medium">
                                    {selectedFiles.size} selected
                                </span>

                                <div className="h-4 w-px bg-blue-500/30" />

                                <button
                                    onClick={handleBatchDownload}
                                    className="px-3 py-1.5 bg-blue-600 rounded-lg text-sm font-medium hover:bg-blue-500 flex items-center gap-2 transition-colors"
                                    disabled={selectedFiles.size === 0}
                                >
                                    <Download size={14} aria-hidden="true" />
                                    Download
                                </button>

                                <button
                                    onClick={() => {
                                        Array.from(selectedFiles).forEach(filename => {
                                            if (!favorites.includes(filename)) {
                                                toggleFavorite(filename);
                                            }
                                        });
                                        toast.success(`Added ${selectedFiles.size} images to favorites`, { icon: '⭐' });
                                    }}
                                    className="px-3 py-1.5 bg-yellow-600 rounded-lg text-sm font-medium hover:bg-yellow-500 flex items-center gap-2 transition-colors"
                                    disabled={selectedFiles.size === 0}
                                >
                                    <Star size={14} aria-hidden="true" />
                                    <span className="hidden sm:inline">Add to Favorites</span>
                                    <span className="sm:hidden">Favorite</span>
                                </button>

                                <button
                                    onClick={() => setShowSelectCollection(true)}
                                    className="px-3 py-1.5 bg-purple-600 rounded-lg text-sm font-medium hover:bg-purple-500 flex items-center gap-2 transition-colors"
                                    disabled={selectedFiles.size === 0}
                                >
                                    <Plus size={14} aria-hidden="true" />
                                    <span className="hidden sm:inline">Add to Collection</span>
                                    <span className="sm:hidden">Collection</span>
                                </button>

                                {activeCollection && (
                                    <button
                                        onClick={() => {
                                            selectedFiles.forEach(filename => {
                                                removeFromCollection(activeCollection, filename);
                                            });
                                            toast.success(`Removed ${selectedFiles.size} images from collection`);
                                            setSelectedFiles(new Set());
                                        }}
                                        className="px-3 py-1.5 bg-orange-600 rounded-lg text-sm font-medium hover:bg-orange-500 flex items-center gap-2 transition-colors"
                                        disabled={selectedFiles.size === 0}
                                    >
                                        <X size={14} aria-hidden="true" />
                                        <span className="hidden sm:inline">Remove from Collection</span>
                                        <span className="sm:hidden">Remove</span>
                                    </button>
                                )}

                                <button
                                    onClick={() => {
                                        setConfirmModal({
                                            isOpen: true,
                                            title: `Delete ${selectedFiles.size} Images`,
                                            message: "Are you sure you want to delete these images? This action cannot be undone.",
                                            isDangerous: true,
                                            confirmText: "Delete Images",
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
                                    }}
                                    className="px-3 py-1.5 bg-red-600 rounded-lg text-sm font-medium hover:bg-red-500 flex items-center gap-2 transition-colors"
                                    disabled={selectedFiles.size === 0}
                                >
                                    <Trash2 size={14} aria-hidden="true" />
                                    Delete
                                </button>

                                <div className="flex-1" />

                                <button
                                    onClick={() => {
                                        setSelectionMode(false);
                                        setSelectedFiles(new Set());
                                    }}
                                    className="px-3 py-1.5 bg-gray-700 rounded-lg text-sm font-medium hover:bg-gray-600 text-gray-300 transition-colors"
                                >
                                    Cancel
                                </button>
                            </motion.div>
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
                                <VirtuosoGrid
                                    useWindowScroll
                                    data={flattenedGridItems}
                                    context={{ gridCols }}
                                    components={{ List: GridList, Item: GridItem }}
                                    itemContent={(index, item) => {
                                        if (item.isHeader) {
                                            return (
                                                <h3 className="text-gray-500 font-medium mb-4 flex items-center gap-2 date-header-marker">
                                                    <Calendar size={16} /> {formatDateLabel(item.date)}
                                                </h3>
                                            );
                                        }

                                        return (
                                            <motion.div
                                                layout
                                                initial={{ opacity: 0, scale: 0.8 }}
                                                animate={{ opacity: 1, scale: 1 }}
                                                exit={{ opacity: 0, scale: 0.8 }}
                                                transition={{ duration: 0.2 }}
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
                                                            // Toggle all images in group
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
                                                        {/* Selection Mode Checkbox */}
                                                        {selectionMode && (
                                                            <div className={`absolute top-2 right-2 p-1.5 rounded-full ${selectedFiles.has(item.name) ? 'bg-blue-500 text-white' : 'bg-black/50 text-gray-400'}`}>
                                                                <Check size={14} />
                                                            </div>
                                                        )}

                                                        {/* Favorite Star Button */}
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
                                        );
                                    }}
                                />
                            ) : (
                                Object.entries(grouped)
                                    .sort(([dateA], [dateB]) => new Date(dateB).getTime() - new Date(dateA).getTime())
                                    .map(([date, groupItems]) => (
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
                            setSelectedImage({
                                ...selectedImage.siblingImages[newIndex],
                                siblingImages: selectedImage.siblingImages,
                                associatedJob: selectedImage.associatedJob
                            });
                        }
                    }}
                    metadata={metadata}
                    loadingMeta={loadingMeta}
                    job={selectedImage.associatedJob}
                    onClose={() => setSelectedImage(null)}
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
