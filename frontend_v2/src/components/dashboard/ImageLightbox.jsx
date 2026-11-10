import { useState, useCallback, useEffect, useRef, memo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { X, Download, Trash2, Loader2, RefreshCw, ChevronLeft, ChevronRight, Clock, Server, Hash, Maximize2, Minimize2, Expand, Shrink, Copy, Check } from 'lucide-react';
import { jobsApi } from '../../api/jobs';
import ProgressiveImage from '../ProgressiveImage';
import { getProviderDisplayName } from '../../utils/providerUtils';
import { assetUrl, assetPath } from '../../utils/assetUrl';
import { formatBytes } from '../../utils/bytes';
import { copyToClipboard } from '../../utils/clipboard';
import toast from 'react-hot-toast';
import ModalOverlay from '../common/ModalOverlay';
import AssetTagEditor from './AssetTagEditor';
import GenerationTelemetry from '../common/GenerationTelemetry';
// ⚡ Bolt: Wrap ImageLightbox in React.memo to prevent unnecessary re-renders when parent Dashboard updates
// A dot per image is fine for a 4-image job batch and absurd for a 16k-image
// gallery, so past this many the dots are replaced by the "12 / 340" counter
// alone.
const MAX_DOT_INDICATORS = 10;

export default memo(function ImageLightbox({
    image,
    images = [], // Array of images for carousel navigation
    currentIndex = 0, // Current index in the carousel
    onNavigate, // Callback for navigation: onNavigate(newIndex)
    metadata,
    loadingMeta,
    job, // Job info associated with this image
    onClose,
    onDelete,
    onReuseParameters,
    reuseInProgress = false,
    // The gallery is infinitely scrolled, so `images` is only the loaded prefix.
    // At the end of it, next fetches another page instead of wrapping, then
    // stops for good once the real end is reached.
    hasMore = false,
    onLoadMore = null,
    isLoadingMore = false,
}) {
    const [imgIndex, setImgIndex] = useState(currentIndex);
    // "Focus" mode is in-app: it drops the details sidebar so the image gets
    // the whole window. It needs no browser API, so it works on iPhone Safari,
    // in an iframe, and in the installed PWA — where requestFullscreen does not.
    const [isFocusMode, setIsFocusMode] = useState(false);
    // True browser fullscreen, tracked from the document rather than assumed,
    // because the user (or Escape, or F11, or another tab) can leave it without
    // going through our button.
    const [isNativeFullscreen, setIsNativeFullscreen] = useState(false);
    const dialogRef = useRef(null);
    const touchStartRef = useRef(null);
    // Set when next walks off the end of the loaded prefix; the effect below
    const pendingAdvanceRef = useRef(false);

    const indexedImage = images.length > 0 ? images[imgIndex] : undefined;
    const displayImage = indexedImage || image;
    const displayPath = assetPath(displayImage);

    const activeJobId = job?.id || metadata?.job_id || displayImage?.metadata?.job_id;
    const { data: fetchedJob } = useQuery({
        queryKey: ['job', activeJobId],
        queryFn: () => jobsApi.get(activeJobId),
        enabled: !job && !!activeJobId,
        staleTime: 60000,
    });

    const effectiveJob = job || fetchedJob;
    const timings = effectiveJob?.timings || metadata?.timings || displayImage?.metadata?.timings || metadata?.job?.timings || effectiveJob?.diagnostics?.timings || metadata?.diagnostics?.timings;
    const effectiveProvider = effectiveJob?.provider_id || metadata?.provider || displayImage?.metadata?.provider || timings?.provider_id;
    // call is optional-chained and the UI simply does not light up without it.
    const supportsNativeFullscreen =
        typeof document !== 'undefined' && typeof document.documentElement?.requestFullscreen === 'function';

    useEffect(() => {
        if (!supportsNativeFullscreen) return undefined;
        const sync = () => setIsNativeFullscreen(document.fullscreenElement === dialogRef.current);
        document.addEventListener('fullscreenchange', sync);
        return () => document.removeEventListener('fullscreenchange', sync);
    }, [supportsNativeFullscreen]);

    // Closing the viewer (or navigating it away) must not strand the document
    // in fullscreen with no element filling the screen.
    useEffect(() => {
        return () => {
            if (document.fullscreenElement && typeof document.exitFullscreen === 'function') {
                document.exitFullscreen().catch(() => {});
            }
        };
    }, []);

    const toggleFocusMode = useCallback(() => setIsFocusMode((v) => !v), []);

    const toggleNativeFullscreen = useCallback(() => {
        if (document.fullscreenElement) {
            document.exitFullscreen?.().catch(() => {});
            return;
        }
        dialogRef.current?.requestFullscreen?.().catch(() => {});
    }, []);

    // ModalOverlay owns Escape and calls this for both Escape and a backdrop
    // click. While the browser owns the screen it also owns Escape, so the
    // keypress never reaches the page and the browser leaves fullscreen on its
    // own — a second Escape then closes the viewer. This guard only matters for
    // the browsers that do deliver the key, and it deliberately does not
    // affect the close button, which calls `onClose` directly.
    const handleOverlayDismiss = useCallback(() => {
        if (isNativeFullscreen) return;
        onClose?.();
    }, [isNativeFullscreen, onClose]);

    // Use image from images array if available, otherwise use the single image prop.
    // An out-of-range index falls back to `image` rather than yielding undefined:
    // a null render would return early here while `useSelectedImageState` still
    // held the body scroll lock, leaving an unscrollable page with no lightbox
    // on it.
    // A single loaded image is still navigable when more pages exist.
    const hasMultiple = images.length > 1 || hasMore;
    const isFirst = imgIndex <= 0;
    const isLastLoaded = imgIndex >= images.length - 1;
    const canLoadMore = hasMore && !isLoadingMore && !!onLoadMore;
    const canGoNext = !isLastLoaded || canLoadMore;

    // Sync internal index with external currentIndex prop
    useEffect(() => {
        setImgIndex(currentIndex);
    }, [currentIndex]);

    // Consume a "next past the end" request once more images have arrived.
    useEffect(() => {
        if (!pendingAdvanceRef.current) return;
        if (imgIndex >= images.length - 1) return; // list has not grown yet
        pendingAdvanceRef.current = false;
        const newIndex = imgIndex + 1;
        setImgIndex(newIndex);
        onNavigate?.(newIndex);
    }, [images.length, imgIndex, onNavigate]);

    // Navigation handlers. Neither wraps: wrapping on a large gallery throws
    // the user far from where they were, and it is indistinguishable from a
    // bug when the list is a loaded prefix of something much longer.
    const goToPrev = useCallback((e) => {
        e?.stopPropagation();
        if (imgIndex <= 0) return;
        const newIndex = imgIndex - 1;
        setImgIndex(newIndex);
        onNavigate?.(newIndex);
    }, [imgIndex, onNavigate]);

    const goToNext = useCallback((e) => {
        e?.stopPropagation();
        if (imgIndex < images.length - 1) {
            const newIndex = imgIndex + 1;
            setImgIndex(newIndex);
            onNavigate?.(newIndex);
            return;
        }
        if (canLoadMore) {
            // The effect above advances once the page lands, so the viewer
            // keeps the cursor on the image the user is looking at meanwhile.
            pendingAdvanceRef.current = true;
            onLoadMore();
        }
    }, [imgIndex, images.length, canLoadMore, onLoadMore, onNavigate]);

    const handleTouchStart = useCallback((event) => {
        const touch = event.touches?.[0];
        if (touch) {
            touchStartRef.current = { x: touch.clientX, y: touch.clientY };
        }
    }, []);

    const handleTouchEnd = useCallback((event) => {
        const start = touchStartRef.current;
        const touch = event.changedTouches?.[0];
        touchStartRef.current = null;
        if (!start || !touch || !hasMultiple) return;
        const deltaX = touch.clientX - start.x;
        const deltaY = touch.clientY - start.y;
        if (Math.abs(deltaX) < 50 || Math.abs(deltaX) <= Math.abs(deltaY)) return;
        if (deltaX < 0) {
            goToNext();
        } else {
            goToPrev();
        }
    }, [goToNext, goToPrev, hasMultiple]);

    // Escape is deliberately NOT handled here: <ModalOverlay> owns it, so the
    // lightbox dismisses through the topmost-wins registry instead of closing
    // itself out from under a dialog stacked on top of it.
    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.key === 'ArrowLeft' && hasMultiple) goToPrev();
            else if (e.key === 'ArrowRight' && hasMultiple) goToNext();
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [hasMultiple, goToPrev, goToNext, onClose]);

    if (!displayImage) return null;

    // Calculate job duration if available
    const getJobDuration = () => {
        if (!effectiveJob?.started_at || !effectiveJob?.completed_at) return null;
        const start = new Date(effectiveJob.started_at);
        const end = new Date(effectiveJob.completed_at);
        const diffMs = end - start;
        if (isNaN(diffMs) || diffMs < 0) return null;
        const seconds = Math.floor(diffMs / 1000);
        if (seconds < 60) return `${seconds}s`;
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        return `${minutes}m ${remainingSeconds}s`;
    };

    return (
        // The backdrop never dismissed the lightbox (only the close button and
        // the arrow keys did), so closeOnBackdrop stays false.
        <ModalOverlay onClose={handleOverlayDismiss} closeOnBackdrop={false} className="z-50 bg-black/95">
            <div className="absolute top-4 right-4 z-10 flex items-center gap-2">
                <button
                    onClick={toggleFocusMode}
                    aria-pressed={isFocusMode}
                    title={isFocusMode ? 'Show image details' : 'Full screen (hide details)'}
                    className={`p-2 rounded-full transition-colors outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                        isFocusMode ? 'bg-blue-600/70 text-white hover:bg-blue-500' : 'bg-gray-800/50 text-white hover:bg-gray-700'
                    }`}
                    aria-label="Toggle focus mode"
                >
                    {isFocusMode ? <Minimize2 size={20} aria-hidden="true" /> : <Maximize2 size={20} aria-hidden="true" />}
                </button>

                {supportsNativeFullscreen && (
                    <button
                        onClick={toggleNativeFullscreen}
                        aria-pressed={isNativeFullscreen}
                        title={isNativeFullscreen ? 'Exit browser fullscreen' : 'Browser fullscreen'}
                        className={`p-2 rounded-full transition-colors outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                            isNativeFullscreen ? 'bg-blue-600/70 text-white hover:bg-blue-500' : 'bg-gray-800/50 text-white hover:bg-gray-700'
                        }`}
                        aria-label="Toggle browser fullscreen"
                    >
                        {isNativeFullscreen ? <Shrink size={20} aria-hidden="true" /> : <Expand size={20} aria-hidden="true" />}
                    </button>
                )}

                <button
                    onClick={onClose}
                    className="p-2 bg-gray-800/50 rounded-full text-white hover:bg-gray-700 outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                    aria-label="Close lightbox"
                >
                    <X size={24} aria-hidden="true" />
                </button>
            </div>

            <div
                ref={dialogRef}
                role="dialog"
                aria-modal="true"
                aria-label="Image lightbox"
                className={`flex flex-col lg:flex-row w-full h-full overflow-hidden bg-black ${
                    isFocusMode ? '' : 'gap-4 max-w-7xl'
                }`}
            >
                {/* Image Container with carousel navigation */}
                <div
                    data-testid="lightbox-swipe-area"
                    onTouchStart={handleTouchStart}
                    onTouchEnd={handleTouchEnd}
                    style={{ touchAction: 'pan-y' }}
                    className="flex-1 flex flex-col items-center justify-center p-2 overflow-hidden bg-black relative"
                >
                    {/* Carousel Navigation - Previous (inside image container) */}
                    {hasMultiple && (
                        <button
                            onClick={goToPrev}
                            disabled={isFirst}
                            className={`absolute left-4 top-1/2 -translate-y-1/2 z-10 p-3 rounded-full text-white transition-colors outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                                isFirst
                                    ? 'bg-gray-800/30 cursor-default text-gray-600'
                                    : 'bg-gray-800/70 hover:bg-gray-700'
                            }`}
                            aria-label="Previous image"
                        >
                            <ChevronLeft size={28} aria-hidden="true" />
                        </button>
                    )}

                    {/* Carousel Navigation - Next (inside image container) */}
                    {hasMultiple && (
                        <button
                            onClick={goToNext}
                            disabled={!canGoNext}
                            className={`absolute right-4 top-1/2 -translate-y-1/2 z-10 p-3 rounded-full text-white transition-colors outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                                !canGoNext
                                    ? 'bg-gray-800/30 cursor-default text-gray-600'
                                    : 'bg-gray-800/70 hover:bg-gray-700'
                            }`}
                            aria-label="Next image"
                        >
                            <ChevronRight size={28} aria-hidden="true" />
                        </button>
                    )}
                    <ProgressiveImage
                        blurhash={displayImage.blurhash}
                        src={assetUrl(displayPath)}
                        thumb={displayImage.thumb ? `${displayImage.thumb}` : null}
                        medium={displayImage.medium ? `${displayImage.medium}` : null}
                        alt={displayImage.name}
                        size="full"
                        aspectRatio="auto"
                        className="max-w-full max-h-full object-contain"
                    />

                    {/* Carousel Indicators */}
                    {hasMultiple && (
                        <div className="flex items-center gap-2 mt-4">
                            {images.length <= MAX_DOT_INDICATORS && images.map((_, idx) => (
                                <button
                                    key={idx}
                                    onClick={() => {
                                        setImgIndex(idx);
                                        onNavigate?.(idx);
                                    }}
                                    className={`w-2 h-2 rounded-full transition-colors outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-black ${idx === imgIndex ? 'bg-blue-500' : 'bg-gray-600 hover:bg-gray-500'
                                        }`}
                                    aria-label={`Go to image ${idx + 1}`}
                                    aria-pressed={idx === imgIndex}
                                />
                            ))}
                            {/* "+" because the gallery is a loaded prefix: the
                                total is not known until the pages run out. */}
                            <span className="ml-2 text-xs text-gray-400">
                                {imgIndex + 1} / {hasMore ? `${images.length}+` : images.length}
                            </span>
                        </div>
                    )}
                </div>

                {/* Sidebar. Hidden in focus mode — that is the whole point of
                    focus mode, and the image container above keeps its own
                    navigation, so nothing becomes unreachable. */}
                {!isFocusMode && (
                <div className="w-full lg:w-80 h-[42%] lg:h-full bg-gray-900 border-t lg:border-t-0 lg:border-l border-gray-800 p-4 lg:p-6 overflow-y-auto flex-shrink-0">
                    <div className="space-y-4 md:space-y-6">
                        <div>
                            <h3 className="font-bold text-lg mb-2">Details</h3>
                            <p className="text-sm text-gray-400 break-all">{displayImage.name}</p>
                            <p className="text-sm text-gray-500 mt-1">
                                {Number.isFinite(Number(displayImage.size))
                                    ? formatBytes(Number(displayImage.size))
                                    : (Number.isFinite(Number(displayImage.width)) && Number.isFinite(Number(displayImage.height))
                                          ? `${displayImage.width} x ${displayImage.height}`
                                          : 'Unknown size')}
                            </p>
                        </div>

                        {/* Primary Top Action Group: Reuse Parameters & Copy Prompt */}
                        <div className="space-y-2">
                            {metadata && (
                                <button
                                    type="button"
                                    onClick={onReuseParameters}
                                    disabled={reuseInProgress}
                                    aria-label="Reuse parameters from this image"
                                    className="w-full bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 disabled:opacity-60 disabled:cursor-not-allowed py-2.5 px-4 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 transition-all shadow-lg shadow-blue-900/20"
                                >
                                    {reuseInProgress ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
                                    {reuseInProgress ? 'Loading Parameters...' : 'Reuse Parameters'}
                                </button>
                            )}

                            <div className="flex gap-2">
                                {metadata?.prompt && (
                                    <button
                                        type="button"
                                        onClick={async () => {
                                            const ok = await copyToClipboard(metadata.prompt);
                                            if (ok) toast.success('Prompt copied to clipboard');
                                            else toast.error('Failed to copy prompt');
                                        }}
                                        aria-label="Copy prompt"
                                        title="Copy positive prompt"
                                        className="flex-1 bg-gray-800 hover:bg-gray-700 py-2 px-3 rounded-lg text-sm font-medium flex items-center justify-center gap-1.5 transition-colors text-gray-200 hover:text-white"
                                    >
                                        <Copy size={15} aria-hidden="true" />
                                        <span>Copy</span>
                                    </button>
                                )}
                                <a
                                    href={assetUrl(displayPath)}
                                    download
                                    aria-label="Download image"
                                    className="flex-1 bg-gray-800 hover:bg-gray-700 py-2 px-3 rounded-lg text-sm font-medium flex items-center justify-center gap-1.5 transition-colors text-gray-200 hover:text-white"
                                >
                                    <Download size={15} aria-hidden="true" />
                                    <span>Download</span>
                                </a>
                                <button
                                    type="button"
                                    onClick={() => onDelete(displayPath)}
                                    aria-label="Delete image"
                                    className="bg-red-900/20 hover:bg-red-900/40 text-red-400 p-2 rounded-lg text-sm font-medium flex items-center justify-center transition-colors"
                                    title="Delete image"
                                >
                                    <Trash2 size={16} aria-hidden="true" />
                                </button>
                            </div>
                        </div>

                        {/* Generation Telemetry Breakdown (Elevated to top of details) */}
                        {timings && (
                            <GenerationTelemetry
                                timings={timings}
                                steps={metadata?.steps || displayImage?.metadata?.steps || effectiveJob?.metadata?.steps}
                                providerId={effectiveProvider}
                            />
                        )}

                        {/* Job Information */}
                        {effectiveJob ? (
                            <div className="bg-gray-800/50 p-4 rounded-lg border border-gray-700">
                                <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Job Info</h4>
                                <div className="space-y-2 text-sm">
                                    <div className="flex items-center gap-2 text-gray-400">
                                        <Hash size={14} className="text-gray-500" />
                                        <span className="font-mono text-xs">{effectiveJob.id?.substring(0, 8)}...</span>
                                    </div>
                                    {effectiveJob.provider_id && (
                                        <div className="flex items-center gap-2 text-purple-400">
                                            <Server size={14} />
                                            <span>{getProviderDisplayName(effectiveJob.provider_id)}</span>
                                        </div>
                                    )}
                                    {getJobDuration() && (
                                        <div className="flex items-center gap-2 text-green-400">
                                            <Clock size={14} />
                                            <span>{getJobDuration()}</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        ) : (metadata?.job_id || metadata?.provider || displayImage?.metadata?.job_id || displayImage?.metadata?.provider) ? (
                            <div className="bg-gray-800/50 p-4 rounded-lg border border-gray-700">
                                <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Job Info</h4>
                                <div className="space-y-2 text-sm">
                                    {(metadata?.job_id || displayImage?.metadata?.job_id) && (
                                        <div className="flex items-center gap-2 text-gray-400">
                                            <Hash size={14} className="text-gray-500" />
                                            <span className="font-mono text-xs">{(metadata?.job_id || displayImage?.metadata?.job_id).substring(0, 8)}...</span>
                                        </div>
                                    )}
                                    {(metadata?.provider || displayImage?.metadata?.provider) && (
                                        <div className="flex items-center gap-2 text-purple-400">
                                            <Server size={14} />
                                            <span>{getProviderDisplayName(metadata?.provider || displayImage?.metadata?.provider)}</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        ) : null}

                        <AssetTagEditor key={displayImage?.id || 'no-asset'} assetId={displayImage?.id} />
                        {loadingMeta ? (
                            <div className="flex justify-center py-4">
                                <Loader2 className="animate-spin text-gray-500" />
                            </div>
                        ) : metadata ? (
                            <div className="space-y-4 md:space-y-6">
                                {/* Main Stats */}
                                <div className="grid grid-cols-2 gap-3">
                                    <div className="bg-gray-800 p-3 rounded-lg border border-gray-700">
                                        <span className="text-xs text-gray-500 uppercase block mb-1">Seed</span>
                                        <span className="text-sm font-mono text-white break-all">{metadata.seed}</span>
                                    </div>
                                    <div className="bg-gray-800 p-3 rounded-lg border border-gray-700">
                                        <span className="text-xs text-gray-500 uppercase block mb-1">Steps / CFG</span>
                                        <span className="text-sm text-white">{metadata.steps} / {metadata.cfg}</span>
                                    </div>
                                    <div className="bg-gray-800 p-3 rounded-lg border border-gray-700">
                                        <span className="text-xs text-gray-500 uppercase block mb-1">Sampler</span>
                                        <span className="text-sm text-white truncate" title={metadata.sampler}>{metadata.sampler}</span>
                                    </div>
                                    <div className="bg-gray-800 p-3 rounded-lg border border-gray-700">
                                        <span className="text-xs text-gray-500 uppercase block mb-1">Scheduler</span>
                                        <span className="text-sm text-white truncate" title={metadata.scheduler}>{metadata.scheduler}</span>
                                    </div>
                                    <div className="bg-gray-800 p-3 rounded-lg border border-gray-700 col-span-2">
                                        <span className="text-xs text-gray-500 uppercase block mb-1">Model</span>
                                        <span className="text-sm text-white truncate block" title={typeof metadata.checkpoint === 'object' ? (metadata.checkpoint.display_name || metadata.checkpoint.name) : metadata.checkpoint}>
                                            {typeof metadata.checkpoint === 'object' ? (metadata.checkpoint.display_name || metadata.checkpoint.name) : metadata.checkpoint || "Unknown"}
                                        </span>
                                    </div>
                                </div>

                                {/* LoRAs */}
                                {metadata.loras?.length > 0 && (
                                    <div>
                                        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">LoRAs</h4>
                                        <div className="flex flex-wrap gap-2">
                                            {metadata.loras.map((lora, i) => (
                                                <span key={i} className="px-2 py-1 bg-purple-500/20 text-purple-300 rounded text-xs border border-purple-500/30" title={lora.name}>
                                                    {lora.display_name || lora.name} ({lora.strength})
                                                </span>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* ControlNet */}
                                {metadata.controlnets?.length > 0 && (
                                    <div>
                                        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">ControlNet</h4>
                                        <div className="flex flex-wrap gap-2">
                                            {metadata.controlnets.map((cn, i) => (
                                                <span key={i} className="px-2 py-1 bg-cyan-500/20 text-cyan-300 rounded text-xs border border-cyan-500/30 flex items-center gap-1" title={cn.name}>
                                                    <span className="font-medium truncate max-w-[180px]">{cn.name ? cn.name.split('/').pop() : 'ControlNet'}</span>
                                                    <span className="text-cyan-400/80 font-mono">({cn.strength ?? 1.0})</span>
                                                </span>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* IP-Adapter */}
                                {metadata.ipAdapters?.length > 0 && (
                                    <div>
                                        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">IP-Adapter</h4>
                                        <div className="flex flex-wrap gap-2">
                                            {metadata.ipAdapters.map((ip, i) => (
                                                <span key={i} className="px-2 py-1 bg-violet-500/20 text-violet-300 rounded text-xs border border-violet-500/30 flex items-center gap-1" title={ip.model}>
                                                    <span className="font-medium truncate max-w-[180px]">{ip.model ? ip.model.split('/').pop() : 'IP-Adapter'}</span>
                                                    <span className="text-violet-400/80 font-mono">({ip.weight ?? 1.0})</span>
                                                </span>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* Enhancements */}
                                {(metadata.hiresFix || metadata.adetailer || metadata.enableFreeU || metadata.enablePAG) && (
                                    <div>
                                        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Enhancements</h4>
                                        <div className="flex flex-wrap gap-2">
                                            {metadata.hiresFix && (
                                                <span className="px-2 py-1 bg-amber-500/20 text-amber-300 rounded text-xs border border-amber-500/30 flex items-center gap-1">
                                                    <span className="font-medium">✨ Hi-Res Fix:</span>
                                                    <span className="text-amber-200 font-mono">
                                                        {metadata.hiresUpscaler || "Active"}
                                                        {metadata.hiresUpscale ? ` (${metadata.hiresUpscale}x)` : ''}
                                                        {metadata.hiresDenoise !== undefined && metadata.hiresDenoise !== null ? ` • Denoise ${metadata.hiresDenoise}` : ''}
                                                        {metadata.hiresSteps ? ` • ${metadata.hiresSteps} steps` : ''}
                                                    </span>
                                                </span>
                                            )}
                                            {metadata.adetailer && (
                                                <span className="px-2 py-1 bg-emerald-500/20 text-emerald-300 rounded text-xs border border-emerald-500/30 flex items-center gap-1">
                                                    <span className="font-medium">👤 Face Detailer:</span>
                                                    <span className="text-emerald-200 font-mono">
                                                        {metadata.adetailerModel || "Active"}
                                                        {metadata.adetailerDenoise !== undefined && metadata.adetailerDenoise !== null ? ` • Denoise ${metadata.adetailerDenoise}` : ''}
                                                    </span>
                                                </span>
                                            )}
                                            {metadata.enableFreeU && (
                                                <span className="px-2 py-1 bg-indigo-500/20 text-indigo-300 rounded text-xs border border-indigo-500/30 font-medium">
                                                    FreeU
                                                </span>
                                            )}
                                            {metadata.enablePAG && (
                                                <span className="px-2 py-1 bg-pink-500/20 text-pink-300 rounded text-xs border border-pink-500/30 font-medium">
                                                    PAG ({metadata.pagScale ?? 3.0})
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                )}

                                {/* Prompts */}
                                <div>
                                    <div className="flex items-center justify-between mb-2">
                                        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Prompt</h4>
                                        {metadata.prompt && (
                                            <button
                                                type="button"
                                                onClick={async () => {
                                                    const ok = await copyToClipboard(metadata.prompt);
                                                    if (ok) toast.success('Prompt copied');
                                                }}
                                                aria-label="Copy prompt text"
                                                className="text-2xs text-gray-400 hover:text-white flex items-center gap-1 transition-colors"
                                            >
                                                <Copy size={11} aria-hidden="true" />
                                                <span>Copy</span>
                                            </button>
                                        )}
                                    </div>
                                    <p className="text-sm text-gray-300 bg-gray-800 p-3 rounded-lg border border-gray-700 max-h-40 overflow-y-auto">{metadata.prompt}</p>
                                </div>
                                {metadata.negativePrompt && (
                                    <div>
                                        <div className="flex items-center justify-between mb-2">
                                            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Negative Prompt</h4>
                                            <button
                                                type="button"
                                                onClick={async () => {
                                                    const ok = await copyToClipboard(metadata.negativePrompt);
                                                    if (ok) toast.success('Negative prompt copied');
                                                }}
                                                aria-label="Copy negative prompt text"
                                                className="text-2xs text-gray-400 hover:text-white flex items-center gap-1 transition-colors"
                                            >
                                                <Copy size={11} aria-hidden="true" />
                                                <span>Copy</span>
                                            </button>
                                        </div>
                                        <p className="text-sm text-gray-400 bg-gray-800 p-3 rounded-lg border border-gray-700 max-h-40 overflow-y-auto">{metadata.negativePrompt}</p>
                                    </div>
                                )}

                            </div>
                        ) : (
                            <div className="text-center py-8 text-gray-500 text-sm">No metadata available</div>
                        )}
                     </div>
                 </div>
                )}
            </div>
        </ModalOverlay>
    );
});
