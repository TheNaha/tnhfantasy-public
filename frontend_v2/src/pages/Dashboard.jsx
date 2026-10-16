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
import { useLightboxNavigation, identityOf } from '../hooks/useLightboxNavigation';
import { useFavorites } from '../hooks/useFavorites';
import { useSelectedImageState } from '../hooks/useSelectedImageState';
import { useActiveJobs } from '../hooks/useActiveJobs';
import {
    useCollections,
    useCollectionImages,
    useAddImagesToCollection,
    useRemoveImagesFromCollection,
    useMoveImagesBetweenCollections
} from '../hooks/useCollections';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { hasOpenEscapeDialog } from '../hooks/useEscapeKey';
import { useDashboardModals } from '../hooks/useDashboardModals';
import { useDashboardSelection } from '../hooks/useDashboardSelection';
import { useInfiniteScroll } from '../hooks/useInfiniteScroll';
import { usePullToRefresh, PullToRefreshIndicator } from '../hooks/usePullToRefresh';
import { useGalleryAutoRefresh } from '../hooks/useGalleryAutoRefresh';
import { flattenSessionPages, useSessions } from '../hooks/useSessions';

// Stores
import { useConfirmation } from '../store/confirmationStore';
import useSettingsStore, { SESSION_VIEW_MODE } from '../store/settingsStore';
import useStore from '../store/useStore';

// Components
import QueueVisualization from '../components/QueueVisualization';
import FailedJobsPanel from '../components/dashboard/FailedJobsPanel';
import DashboardOverlays from '../components/dashboard/DashboardOverlays';
import DashboardGalleryGrid from '../components/dashboard/DashboardGalleryGrid';
import GalleryDateRail from '../components/dashboard/GalleryDateRail';
import GalleryFilterPanel from '../components/dashboard/GalleryFilterPanel';
import DashboardHeaderToolbar from '../components/dashboard/DashboardHeaderToolbar';
import SessionPanel, { SessionViewPlaceholder } from '../components/dashboard/SessionPanel';

// Utils
import {
    applyGeneratorStateFromMetadata,
} from '../utils/reuseParameters';
import { buildSessionGroupedEntries } from '../utils/dashboardItems';

export default function Dashboard() {
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const defaultGridColumns = useSettingsStore((state) => state.settings.ui.defaultGridColumns);
    const autoRefreshOnJobComplete = useSettingsStore((state) => state.settings.gallery.autoRefreshOnJobComplete);
    const toastSuccessDuration = useSettingsStore((state) => state.settings.ui.toastSuccessDuration);
    const toastErrorDuration = useSettingsStore((state) => state.settings.ui.toastErrorDuration);
    
    const { favorites, isFavorite: fastIsFavorite, toggleFavorite, addFavorites } = useFavorites();
    const activeCollection = useStore((state) => state.activeCollection);
    const setActiveCollection = useStore((state) => state.setActiveCollection);
    
    // React Query / WebSocket state
    const { data: activeJobs = [] } = useActiveJobs();
    const { data: collections = {} } = useCollections();
    const { data: activeCollectionImages = [] } = useCollectionImages(activeCollection);
    
    const addImagesToCollectionMutation = useAddImagesToCollection();
    const moveImagesMutation = useMoveImagesBetweenCollections();
    const [moveSelectionMode, setMoveSelectionMode] = useState(false);
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
        } catch {
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
    //
    // The live view is its own key, distinct from the `default*` preferences.
    // They used to be the same key, so every in-page toggle rewrote the user's
    // default — the setting could not survive a session — and `session` (a
    // live-only mode with no `<option>` anywhere) left the Settings select
    // rendering blank. `null` means "no choice made yet", so both fall back to
    // the stored default and an install upgrading into this shape behaves as
    // before until the user actually toggles something.
    const defaultViewMode = useSettingsStore((state) => state.settings.ui.defaultViewMode);
    const liveViewMode = useSettingsStore((state) => state.settings.ui.viewMode);
    const viewMode = liveViewMode || defaultViewMode;
    const setViewMode = useCallback((mode) => {
        useSettingsStore.getState().updateSetting('ui', 'viewMode', mode);
    }, []);
    // Grid columns live in the settings store (not local state) so a change made
    // on /settings is already in force here instead of after a reload — but the
    // live count is separate from the default, for the same reason as the view.
    const liveGridCols = useSettingsStore((state) => state.settings.ui.gridColumns);
    const gridCols = liveGridCols || defaultGridColumns;
    const setGridCols = useCallback((cols) => {
        useSettingsStore.getState().updateSetting('ui', 'gridColumns', cols);
    }, []);
    const [showSessionPanel, setShowSessionPanel] = useState(false);

    const isSessionView = viewMode === SESSION_VIEW_MODE;
    const sessionsQuery = useSessions({}, { enabled: isSessionView });
    const sessions = useMemo(
        () => flattenSessionPages(sessionsQuery.data),
        [sessionsQuery.data],
    );

    // Filters
    const [showFavorites, setShowFavorites] = useState(false);
    const [filters, setFilters] = useState(() => {
        try {
            const saved = localStorage.getItem('dashboard_filters');
            if (saved) return JSON.parse(saved);
        } catch {
            // ignore corrupt localStorage
        }
        return { search: '', sort: 'date_desc' };
    });

    useEffect(() => {
        localStorage.setItem('dashboard_filters', JSON.stringify(filters));
    }, [filters]);
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
        addFavorites,
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

    // `siblings` is the group an image was opened from — for the session view
    // that is the session's own images, and the lightbox navigates within
    // them. Null for a gallery image, which navigates the gallery.
    const [lightboxSiblings, setLightboxSiblings] = useState(null);

    const handleImageClick = useCallback((image, siblings = null) => {
        setLightboxSiblings(siblings);
        selectImage(image);
    }, [selectImage]);

    // Data Fetching
    //
    // `isError`/`error` are load-bearing, not defensive. The gallery query
    // destructured neither, and the grid below falls back to `displayedItems
    // .length === 0` — which a 503 satisfies — so a failed fetch rendered
    // "No images yet / Start creating amazing AI-generated images…" with a
    // working Generate CTA, while the facet panel 40 lines up printed
    // "Matching total unavailable" from the same query. The page contradicted
    // itself and told the user their library was empty. Reproduced live by
    // intercepting the facet GET and answering 503.
    const {
        data,
        error: galleryError,
        fetchNextPage,
        hasNextPage,
        isError: isGalleryError,
        isFetching,
        isFetchingNextPage,
        isLoading,
        refetch
    } = useGallery(filters);

    const galleryQueryKey = useMemo(() => ['gallery', filters], [filters]);

    const handleToggleFavorite = useCallback((filename) => {
        const wasFavorite = fastIsFavorite(filename);
        toggleFavorite(filename);
        toast.success(
            wasFavorite ? "Removed from favorites" : "Added to favorites",
            { icon: '⭐' }
        );
    }, [toggleFavorite, fastIsFavorite]);

    const sentinelRef = useInfiniteScroll({
        // In session view the sentinel pages SESSIONS, not assets. It used to be
        // switched off there entirely (`hasMore: false`), on the reasoning that
        // sessions "paginate from the drawer" — so scrolling a 1,411-session
        // library could never reach page two, and the view looked like it only
        // ever had the handful the virtualizer happened to mount. The drawer
        // curates sessions; it is not the only way to see more of them.
        hasMore: isSessionView ? sessionsQuery.hasNextPage : hasNextPage,
        onLoadMore: isSessionView ? sessionsQuery.fetchNextPage : fetchNextPage,
        loading: isSessionView ? sessionsQuery.isFetchingNextPage : isFetchingNextPage,
        rootMargin: '160px 0px'
    });

    useGalleryAutoRefresh({
        lastCompletedJob,
        autoRefreshOnJobComplete,
        queryClient,
        // Stable identity: the hook keys its effect on this, and an inline
        // array re-ran the effect on every Dashboard render.
        galleryQueryKey,
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
        sortedGroupedEntries: imageGroupedEntries,
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

    const sessionGroupedEntries = useMemo(
        () => buildSessionGroupedEntries(sessions, { sort: filters.sort || 'date_desc' }),
        [filters.sort, sessions],
    );

    const sortedGroupedEntries = isSessionView ? sessionGroupedEntries : imageGroupedEntries;
    const sessionPlaceholder = isSessionView && sessions.length === 0;

    // The lightbox navigates the list the user is actually looking at, not one
    // job's batch. It was only ever handed `siblingImages`, so every ordinary
    // single-image click got a one-item "carousel" and the arrows, swipe and
    // counter were all inert.
    const lightboxNav = useLightboxNavigation({
        sortedGroupedEntries,
        selectedImage,
        hasMore: hasNextPage,
        onLoadMore: fetchNextPage,
        isLoadingMore: isFetchingNextPage,
        images: lightboxSiblings,
    });

    const handleLightboxNavigate = useCallback((newIndex) => {
        const target = lightboxNav.resolveTarget(newIndex);
        if (target) selectImage(target);
    }, [lightboxNav, selectImage]);

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
            queryClient.invalidateQueries({ queryKey: ['gallery', filters] });
            // Compare IDENTITIES, not names.
            //
            // This was `if (selectedImage?.name === filename)`, and it never
            // fired — not on the sibling path, not on the plain gallery path,
            // ever. The lightbox deletes the currently DISPLAYED image, which it
            // hands over as `assetPath(displayImage)`; `assetPath` prefers
            // `relative_path`, which the backend builds as
            // `<workspace>/<path>`. `selectedImage.name` is the basename. The two
            // are never equal, so the modal stayed open over a deleted image.
            //
            // `identityOf` is the helper that resolves exactly this divergence:
            // two assets in different workspaces can share a basename, so the
            // basename is not an identity at all.
            //
            // `selectedImage` is the right thing to close unconditionally, for a
            // second reason: `handleLightboxNavigate` selects the sibling being
            // navigated to, so the open modal IS the deleted image's modal.
            if (selectedImage && identityOf(selectedImage) === identityOf(filename)) {
                closeSelectedImage();
            }
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
            // Functional update: replacing the object dropped `sort` (and the
            // persisted copy of it in localStorage) along with the search text.
            setFilters((current) => ({ ...current, search: '' }));
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
        // Invalidate the whole `jobs` subtree, not just `['jobs','active']`.
        // The failed-jobs banner reads `['jobs','failed']` and the queue panel
        // reads `['jobs','queue']`; neither was touched here, so both kept
        // rendering rows for jobs the server had just deleted, and
        // `refetchOnWindowFocus` is globally off, so it was not a
        // self-healing staleness. The sibling single-delete path
        // (`useDashboardModals`) already invalidated `['jobs']`.
        await queryClient.invalidateQueries({ queryKey: ['jobs'] });
        refetch();
    }, [confirm, queryClient, refetch]);

    const handleSelectCollection = useCallback(async (collectionId) => {
        if (moveSelectionMode) {
            setMoveSelectionMode(false);
            const images = Array.from(selectedFiles);
            toast.promise(
                moveImagesMutation.mutateAsync({
                    fromCollectionId: activeCollection,
                    toCollectionId: collectionId,
                    images,
                }),
                {
                    loading: `Moving ${images.length} image${images.length !== 1 ? 's' : ''}...`,
                    success: (data) => `Moved ${data?.moved ?? images.length} image${images.length !== 1 ? 's' : ''}`,
                    error: 'Move failed',
                }
            );
            setSelectedFiles(new Set());
            setSelectionMode(false);
            return;
        }
        // Awaited, and the success toast only on success. `addToCollection` awaits
        // `mutateAsync` internally, so not awaiting it made a rejected PATCH
        // produce an unhandled rejection *and* a toast telling the user their
        // images were saved.
        try {
            await addToCollection(collectionId, Array.from(selectedFiles));
            toast.success(`Added ${selectedFiles.size} images to collection`, { icon: '📁' });
            setSelectedFiles(new Set());
            setSelectionMode(false);
        } catch {
            toast.error('Failed to add images to collection');
        }
    }, [moveSelectionMode, moveImagesMutation, activeCollection, addToCollection, selectedFiles, setSelectedFiles, setSelectionMode]);

    const handleMoveSelectionToCollection = useCallback(() => {
        if (!activeCollection) return;
        if (selectedFiles.size === 0) return;
        setMoveSelectionMode(true);
        setShowSelectCollection(true);
    }, [activeCollection, selectedFiles, setShowSelectCollection]);

    const comparisonImages = useMemo(() => {
        return allItems.filter(item => selectedFiles.has(item.name));
    }, [allItems, selectedFiles]);

    const activeCollectionName = useMemo(() => {
        return activeCollection && collections[activeCollection] ? collections[activeCollection].name : null;
    }, [activeCollection, collections]);

    const location = useLocation();
    useEffect(() => {
        if (location.pathname !== '/' && location.pathname !== '/gallery') return;

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

            // Same guard as the global shortcut registry: while any dialog is
            // open, these keys belong to the dialog. `Delete`/`Backspace`
            // reached `handleDelete` with a confirmation dialog already on
            // screen, which is exactly the action the pointer path asks
            // confirmation for.
            if (hasOpenEscapeDialog()) return;

            if (key === 's') {
                e.preventDefault();
                handleSetSelectionMode(!selectionMode);
            } else if (key === 'r') {
                e.preventDefault();
                refetch();
            } else if (key === ' ' || key === 'spacebar') {
                // The shortcuts modal documents Space as "Open/close image", but
                // only the close path existed. Opening is a card activation, so it
                // reuses handleImageClick rather than reaching into the lightbox.
                if (selectedImage) {
                    e.preventDefault();
                    closeSelectedImage();
                } else if (!selectionMode && displayedItems.length > 0) {
                    e.preventDefault();
                    handleImageClick(displayedItems[0]);
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
        selectedImage, closeSelectedImage, handleDelete, handleImageClick
    ]);

    return (
        <motion.div
            ref={containerRef}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            style={{ position: 'relative' }}
        >
            <PullToRefreshIndicator
                pullDistance={pullDistance}
                isRefreshing={isRefreshing}
                isPulling={isPulling}
                threshold={80}
            />
            <div className="max-w-7xl mx-auto space-y-4 md:space-y-8">
                <QueueVisualization onJobClick={handleJobClick} />
                <FailedJobsPanel />

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
                    onMoveToCollection={handleMoveSelectionToCollection}
                    onCancelSelectionMode={handleCancelSelectionMode}
                    filters={filters}
                    onFilterChange={setFilters}
                    isSessionView={isSessionView}
                    onOpenSessionPanel={() => setShowSessionPanel(true)}
                    onToggleViewMode={() => setViewMode(isSessionView ? 'grid' : SESSION_VIEW_MODE)}
                />

                {/* Faceted search. Both panels read page one only — the counts
                    cannot change between pages of one scroll — and both write into
                    the same `filters` the grid and the list already share, so
                    there is one source of truth for what is being shown. */}
                <GalleryDateRail
                    filters={filters}
                    onChange={setFilters}
                />

                <GalleryFilterPanel
                    facets={data?.pages?.[0]?.facets}
                    filters={filters}
                    onChange={setFilters}
                    totalMatched={data?.pages?.[0]?.totalMatched}
                />

                {sessionPlaceholder && (
                    <SessionViewPlaceholder
                        isLoading={sessionsQuery.isLoading}
                        error={sessionsQuery.isError ? sessionsQuery.error : null}
                        onOpenPanel={() => setShowSessionPanel(true)}
                    />
                )}

                {!sessionPlaceholder && (
                    <DashboardGalleryGrid
                        isLoading={isLoading}
                        isError={isGalleryError}
                        error={galleryError}
                        onRetry={refetch}
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
                        isRefreshing={isFetching && !isLoading}
                    />
                )}
            </div>

            <SessionPanel
                isOpen={showSessionPanel}
                onClose={() => setShowSessionPanel(false)}
            />

            <DashboardOverlays
                selectedImage={selectedImage}
                lightboxNav={lightboxNav}
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

        </motion.div>
    );
}
