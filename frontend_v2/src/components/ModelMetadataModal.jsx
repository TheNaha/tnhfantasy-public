import { X, Copy, Check, ExternalLink, AlertCircle, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import toast from 'react-hot-toast';
import { sanitizeHtml } from '../utils/sanitize';
import { copyToClipboard } from '../utils/clipboard';
import { getProviderDisplayName } from '../utils/providerUtils';
import CivitaiSearchModal from './model-manager/CivitaiSearchModal';
import ModalOverlay from './common/ModalOverlay';
import StatCard from './ui/StatCard';
import { useAutopopulateModel } from '../hooks/useAutopopulate';
import {
    ONLINE_RUNTIME_STATES,
    AVAILABLE_MODEL_STATES,
    normalizeModelStatus,
    isProviderOnline,
    formatAvailabilityBadgeLabel,
    availabilityTone,
    getModelAvailabilitySummary
} from '../utils/modelAvailability';

function modelStatusTone(status) {
    if (AVAILABLE_MODEL_STATES.has(status)) {
        return 'text-green-300 bg-green-500/15 border-green-500/30';
    }
    if (status === 'partial') {
        return 'text-amber-300 bg-amber-500/15 border-amber-500/30';
    }
    if (status === 'downloading') {
        return 'text-yellow-300 bg-yellow-500/15 border-yellow-500/30';
    }
    if (status === 'failed') {
        return 'text-red-300 bg-red-500/15 border-red-500/30';
    }
    return 'text-gray-300 bg-gray-500/15 border-gray-500/30';
}

function ModelMetadataHeader({
    className,
    showCreator = false,
    displayName,
    modelType,
    baseModel,
    creator,
    onClose,
}) {
    return (
        <div className={`p-4 border-b border-gray-800 flex justify-between items-start bg-gray-900 ${className}`}>
            <div className="min-w-0 flex-1 mr-4">
                <h2 className="text-lg md:text-2xl font-bold text-white truncate">{displayName}</h2>
                <div className="flex items-center gap-2 mt-1 md:mt-2 text-xs md:text-sm text-gray-400 flex-wrap">
                    <span className="px-1.5 py-0.5 bg-gray-800 rounded border border-gray-700 whitespace-nowrap">{modelType}</span>
                    {baseModel && baseModel !== "Unknown" && (
                        <span className="px-1.5 py-0.5 bg-purple-800/50 rounded border border-purple-700/50">{baseModel}</span>
                    )}
                    {showCreator && creator && (
                        <span className="truncate">by <span className="text-blue-400 font-medium">{creator.username}</span></span>
                    )}
                </div>
            </div>
            <button
                onClick={onClose}
                className="p-2 hover:bg-gray-800 rounded-full text-gray-400 hover:text-white transition-colors flex-shrink-0 focus-visible:ring-2 focus-visible:ring-blue-500 outline-none"
                aria-label="Close details"
            >
                <X size={24} aria-hidden="true" />
            </button>
        </div>
    );
}

export default function ModelMetadataModal({ metadata, onClose, providers = [], providersLoading = false, onAddTriggerWords = null }) {
    const [copied, setCopied] = useState(null);
    const [activeImage, setActiveImage] = useState(null);
    const [showSearchModal, setShowSearchModal] = useState(false);

    /**
     * `useAutopopulateModel` owns the request AND both invalidations.
     *
     * This file's hand-written copy had to remember the model-list invalidation
     * and the installed-versions one, and it also resolved with `res.data` (the
     * nested payload) — the shared hook resolves with the same value, so nothing
     * downstream changes. Only the transport and the invalidation moved, and the
     * toasts ride along as per-call callbacks rather than as hook options so the
     * hook itself stays a single, unopinionated mutation.
     */
    const autopopulateMutation = useAutopopulateModel();

    const runAutopopulate = (civitaiId = null) => autopopulateMutation.mutate(
        { modelId: metadata?.id || metadata?.model_id, civitaiId },
        {
            onSuccess: () => {
                toast.success("Model details autopopulated!");
                setShowSearchModal(false);
            },
            onError: (err) => {
                toast.error(err.message || 'Failed to autopopulate');
            },
        },
    );

    if (!metadata) return null;

    // Handle both V1 (CivitAI raw) and V2 (flattened) formats
    const isV2Format = metadata.civitai_id !== undefined || metadata.display_name !== undefined;

    // Extract fields from either format
    const displayName = isV2Format
        ? (metadata.display_name || metadata.name)
        : (metadata.name || "Unknown Model");

    const modelType = isV2Format
        ? (metadata.type || "Unknown")
        : (metadata.type || "Model");

    const baseModel = isV2Format
        ? (metadata.base_model || "Unknown")
        : (metadata.modelVersions?.[0]?.baseModel || "Unknown");

    const trainedWords = isV2Format
        ? (metadata.trained_words || [])
        : (metadata.modelVersions?.[0]?.trainedWords || []);

    const tags = metadata.tags || [];

    const stats = isV2Format
        ? metadata.stats || {}
        : { downloads: metadata.stats?.downloadCount, thumbsUp: metadata.stats?.thumbsUpCount };

    const civitaiId = isV2Format
        ? metadata.civitai_id
        : metadata.id;

    const description = metadata.description;

    const creator = isV2Format
        ? (metadata.creator?.username ? metadata.creator : null)
        : metadata.creator;

    const versionIdForPreview = metadata.civitai_version_id || metadata.version_id || metadata.modelVersions?.[0]?.id;

    // Get gallery images - V2 format uses images array, V1 uses modelVersions
    const rawGalleryImages = isV2Format
        ? (metadata.images || [])
        : (metadata.modelVersions?.[0]?.images || []);

    const galleryItems = rawGalleryImages.map((img, index) => {
        const directUrl = typeof img === 'string' ? img : img?.url;
        let cachedUrl = null;
        if (civitaiId) {
            const params = new URLSearchParams({ image_index: String(index) });
            if (versionIdForPreview) {
                params.set('version_id', String(versionIdForPreview));
            }
            cachedUrl = `/api/v2/models/preview/${civitaiId}?${params.toString()}`;
        }
        return {
            cachedUrl,
            directUrl,
            url: cachedUrl || directUrl,
        };
    }).filter(item => item.url);

    // Get preview image
    const getPreviewImage = () => {
        if (activeImage) return activeImage;
        if (galleryItems.length > 0) return galleryItems[0].cachedUrl || galleryItems[0].directUrl;
        // V2 format
        if (isV2Format && metadata.preview) return metadata.preview;
        if (civitaiId) return `/api/v2/models/preview/${civitaiId}`;
        // V1 format  
        if (metadata.modelVersions?.[0]?.images?.[0]?.url) return metadata.modelVersions[0].images[0].url;
        return null;
    };
    const providerStatuses = metadata.provider_statuses && typeof metadata.provider_statuses === 'object'
        ? metadata.provider_statuses
        : {};
    const runtimeProviders = Array.isArray(providers) ? providers : [];
    const runtimeProviderById = new Map(runtimeProviders.map((provider) => [provider.id, provider]));
    const onlineProviderIds = new Set(
        runtimeProviders
            .filter((provider) => isProviderOnline(provider))
            .map((provider) => provider.id)
    );

    const allProviderIds = Array.from(
        new Set([
            ...Object.keys(providerStatuses),
            ...runtimeProviders.map((provider) => provider.id),
        ])
    );

    const providerRows = allProviderIds
        .map((providerId) => {
            const runtimeProvider = runtimeProviderById.get(providerId);
            const runtimeStatus = runtimeProvider?.runtime_state?.status || 'offline';
            const modelStatus = normalizeModelStatus(providerStatuses[providerId]);
            return {
                providerId,
                providerName: getProviderDisplayName(providerId),
                online: onlineProviderIds.has(providerId),
                runtimeStatus,
                modelStatus,
            };
        })
        .sort((left, right) => {
            if (left.online !== right.online) {
                return left.online ? -1 : 1;
            }
            return left.providerName.localeCompare(right.providerName);
        });

    const onlineProviderCount = runtimeProviders.filter((provider) => isProviderOnline(provider)).length;
    const totalProviderCount = runtimeProviders.length;
    const availableOnlineCount = providerRows.filter(
        (row) => row.online && AVAILABLE_MODEL_STATES.has(row.modelStatus)
    ).length;

    const availabilitySummary = getModelAvailabilitySummary(providerStatuses, runtimeProviders, { providersLoading });
    const modelAvailability = formatAvailabilityBadgeLabel(availabilitySummary.label);



    const handleCopy = async (text, key) => {
        const success = await copyToClipboard(text);
        if (success) {
            setCopied(key);
            toast.success("Copied to clipboard!");
            setTimeout(() => setCopied(null), 2000);
        } else {
            toast.error("Failed to copy");
        }
    };

    return (
        // Full-bleed scrolling sheet: the panel wrapper below does its own
        // centring, so the overlay contributes only the backdrop, the
        // backdrop click and the Escape registry entry.
        <ModalOverlay onClose={onClose} centered={false} className="z-[60] bg-black/80 backdrop-blur-sm overflow-y-auto">
            <div className="min-h-full md:min-h-0 flex items-center justify-center p-0 md:p-4">
                <div
                    role="dialog"
                    aria-modal="true"
                    aria-label={`${displayName} metadata`}
                    className="bg-gray-900 w-full max-w-5xl md:max-h-[calc(90*var(--vh,1vh))] rounded-none md:rounded-2xl border-x-0 md:border md:border-gray-700 flex flex-col md:flex-row shadow-2xl overflow-visible md:overflow-hidden" onClick={e => e.stopPropagation()}>

                     {/* Mobile Header - Sticky on mobile */}
                     <ModelMetadataHeader
                        className="sticky top-0 z-20 md:hidden shadow-lg flex-shrink-0"
                        displayName={displayName}
                        modelType={modelType}
                        baseModel={baseModel}
                        creator={creator}
                        onClose={onClose}
                     />

                    {/* Left: Images - Fixed on desktop, inline on mobile */}
                    <div className="w-full md:w-1/3 bg-black/50 p-4 space-y-4 md:overflow-y-auto border-b md:border-b-0 md:border-r border-gray-800 flex-shrink-0">
                        {getPreviewImage() && (
                            <div className="aspect-[2/3] rounded-lg overflow-hidden border border-gray-800 bg-gray-900">
                                <img
                                    src={getPreviewImage()}
                                    alt="Model Preview"
                                    className="w-full h-full object-contain"
                                    decoding="async"
                                    onError={(e) => {
                                        const fallback = galleryItems[0]?.directUrl || metadata.preview;
                                        if (fallback && e.currentTarget.src !== fallback) {
                                            e.currentTarget.src = fallback;
                                            return;
                                        }
                                        e.target.style.display = 'none';
                                    }}
                                />
                            </div>
                        )}

                        {/* Gallery thumbnails - 3 cols on mobile (Vertical look) */}
                        {galleryItems.length > 1 && (
                            <div className="grid grid-cols-3 gap-2">
                                {galleryItems.slice(0, 24).map((item, i) => (
                                    <button
                                        key={i}
                                        onClick={() => setActiveImage(item.cachedUrl || item.directUrl)}
                                        aria-label={`View image ${i + 1}`}
                                        aria-pressed={activeImage === (item.cachedUrl || item.directUrl)}
                                        className={`aspect-square rounded overflow-hidden border focus-visible:ring-2 focus-visible:ring-blue-500 outline-none ${activeImage === (item.cachedUrl || item.directUrl) ? 'border-blue-500' : 'border-gray-800'} hover:border-gray-600 transition-all`}
                                    >
                                        <img
                                            src={item.cachedUrl || item.directUrl}
                                            alt={`Preview ${i}`}
                                            className="w-full h-full object-cover"
                                            loading="lazy"
                                            decoding="async"
                                            fetchPriority="low"
                                            onError={(e) => {
                                                if (item.directUrl && e.currentTarget.src !== item.directUrl) {
                                                    e.currentTarget.src = item.directUrl;
                                                    return;
                                                }
                                                e.target.style.display = 'none';
                                            }}
                                        />
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Right: Details - Scrollable on desktop, inline on mobile */}
                    <div className="flex-1 md:overflow-y-auto min-h-0 bg-gray-900">
                        {/* Desktop Header - Hidden on mobile */}
                        <ModelMetadataHeader
                            className="hidden md:flex bg-gray-900/50 lg:sticky lg:top-0 z-10 backdrop-blur-md"
                            showCreator={true}
                            displayName={displayName}
                            modelType={modelType}
                            baseModel={baseModel}
                            creator={creator}
                            onClose={onClose}
                        />

                    {/* Content */}
                    <div className="p-4 md:p-6 space-y-4 md:space-y-4 md:space-y-6">
                        {metadata?.description?.includes("Auto-discovered") && (
                            <div className="p-4 bg-yellow-900/20 border border-yellow-700/30 rounded-xl flex justify-between items-center">
                                <div className="flex items-center gap-2 text-yellow-500">
                                    <AlertCircle size={16} />
                                    <span className="text-sm font-medium">Auto-discovered Model</span>
                                </div>
                                <button 
                                    onClick={() => setShowSearchModal(true)}
                                    disabled={autopopulateMutation.isPending}
                                    className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors"
                                >
                                    <RefreshCw size={14} className={autopopulateMutation.isPending ? "animate-spin" : ""} />
                                    {autopopulateMutation.isPending ? 'Fetching...' : 'Fetch Metadata'}
                                </button>
                            </div>
                        )}
                        {/* Stats */}
                        <div className="grid grid-cols-3 gap-4 bg-gray-800/30 p-4 rounded-xl border border-gray-700/50">
                            <StatCard
                                label="Downloads"
                                value={(stats.downloads || 0).toLocaleString()}
                                colorClass="text-white"
                                labelClass="text-xs text-gray-500 uppercase tracking-wider"
                            />
                            <StatCard
                                label="Likes"
                                value={(stats.thumbsUp || 0).toLocaleString()}
                                colorClass="text-green-400"
                                labelClass="text-xs text-gray-500 uppercase tracking-wider"
                            />
                            <StatCard
                                label="Base Model"
                                value={baseModel}
                                colorClass="text-blue-400"
                                labelClass="text-xs text-gray-500 uppercase tracking-wider"
                            />
                        </div>

                        {/* Provider Runtime + Model Availability */}
                        {(providerRows.length > 0 || totalProviderCount > 0 || Object.keys(providerStatuses).length > 0) && (
                            <div className="space-y-3">
                                <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Availability</h3>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                    <div className="bg-gray-800/30 p-4 rounded-xl border border-gray-700/50">
                                        <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">Provider Status</div>
                                        <div className="flex items-center gap-2 text-sm text-gray-200">
                                            <span className={`inline-block h-2 w-2 rounded-full ${providersLoading ? 'bg-blue-400 animate-pulse' : onlineProviderCount > 0 ? 'bg-green-400' : 'bg-gray-500'}`} />
                                            <span>{providersLoading ? 'Loading...' : `${onlineProviderCount}/${totalProviderCount} online`}</span>
                                        </div>
                                    </div>
                                    <div className="bg-gray-800/30 p-4 rounded-xl border border-gray-700/50">
                                        <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">Model Availability</div>
                                        <span className={`inline-flex items-center px-2.5 py-1 rounded-full border text-xs font-medium ${availabilityTone(modelAvailability)}`}>
                                            {modelAvailability}
                                        </span>
                                        {onlineProviderCount > 0 && (
                                            <div className="mt-2 text-xs text-gray-400">
                                                {availableOnlineCount}/{onlineProviderCount} online providers have this model ready
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {providerRows.length > 0 && (
                                    <div className="space-y-2">
                                        {providerRows.map((row) => (
                                            <div key={row.providerId} className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg border border-gray-700 bg-gray-900/50">
                                                <div className="flex items-center gap-2 min-w-0">
                                                    <span className={`inline-block h-2 w-2 rounded-full ${row.online ? 'bg-green-400' : 'bg-gray-500'}`} />
                                                    <span className="text-sm text-gray-200 truncate">{row.providerName}</span>
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-2xs capitalize ${row.online ? 'text-green-300 bg-green-500/10 border-green-500/30' : 'text-gray-300 bg-gray-500/10 border-gray-500/30'}`}>
                                                        {row.online ? 'online' : 'offline'}
                                                    </span>
                                                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-2xs capitalize ${modelStatusTone(row.modelStatus)}`}>
                                                        {row.modelStatus}
                                                    </span>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Trigger Words */}
                        {trainedWords.length > 0 && (
                            <div className="space-y-2">
                                <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Trigger Words</h3>
                                <div className="flex flex-wrap gap-2">
                                    {trainedWords.map(word => (
                                        <div key={word} className="flex items-center rounded-lg border border-blue-500/20 bg-blue-500/10 overflow-hidden">
                                            <button
                                                type="button"
                                                onClick={() => handleCopy(word, `word-${word}`)}
                                                aria-label={`Copy trigger word ${word}`}
                                                className="flex items-center gap-1.5 px-3 py-1.5 text-blue-300 hover:bg-blue-500/20 transition-all text-sm outline-none"
                                            >
                                                {word}
                                                {copied === `word-${word}` ? <Check size={12} aria-hidden="true" /> : <Copy size={12} className="opacity-60" aria-hidden="true" />}
                                            </button>
                                            {typeof onAddTriggerWords === 'function' && (
                                                <button
                                                    type="button"
                                                    onClick={() => {
                                                        onAddTriggerWords([word]);
                                                        toast.success(`Added "${word}" to prompt!`);
                                                    }}
                                                    className="px-2 py-1.5 text-xs font-semibold bg-blue-500/20 hover:bg-blue-500/30 text-blue-200 border-l border-blue-500/20 transition-colors"
                                                    title="Insert into prompt"
                                                >
                                                    + Insert
                                                </button>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                        {/* Model Description */}
                        {description && (
                            <div className="space-y-2">
                                <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Model Description</h3>
                                <div
                                    className="prose prose-invert prose-sm max-w-none text-gray-300 bg-gray-950/30 p-4 rounded-xl border border-gray-800/50 break-words max-h-40 overflow-y-auto overflow-x-hidden select-text cursor-text [&_pre]:overflow-x-auto [&_pre]:max-w-full [&_pre]:text-xs [&_code]:break-all [&_code]:text-xs"
                                    dangerouslySetInnerHTML={{ __html: sanitizeHtml(description) }}
                                />
                            </div>
                        )}

                        {/* Version Description */}
                        {metadata.version_description && (
                            <div className="space-y-2">
                                <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Version Notes</h3>
                                <div
                                    className="prose prose-invert prose-sm max-w-none text-gray-300 bg-blue-950/20 p-4 rounded-xl border border-blue-800/30 break-words max-h-40 overflow-y-auto overflow-x-hidden select-text cursor-text [&_pre]:overflow-x-auto [&_pre]:max-w-full [&_pre]:text-xs [&_code]:break-all [&_code]:text-xs"
                                    dangerouslySetInnerHTML={{ __html: sanitizeHtml(metadata.version_description) }}
                                />
                            </div>
                        )}

                        {/* Tags */}
                        {tags.length > 0 && (
                            <div className="space-y-2">
                                <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Tags</h3>
                                <div className="flex flex-wrap gap-2">
                                    {tags.map(tag => (
                                        <span key={tag} className="px-2 py-1 bg-gray-800 text-gray-400 rounded-full text-xs border border-gray-700">
                                            {tag}
                                        </span>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* CivitAI Link */}
                        {civitaiId && (
                            <div className="pt-4 border-t border-gray-800">
                                <a
                                    href={`https://civitai.com/models/${civitaiId}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-2 text-blue-400 hover:text-blue-300 text-sm"
                                >
                                    View on CivitAI <ExternalLink size={14} />
                                </a>
                            </div>
                        )}

                        {/* Raw JSON Toggle */}
                        <div className="pt-6 border-t border-gray-800">
                            <details className="group">
                                <summary className="cursor-pointer text-xs font-medium text-gray-500 uppercase tracking-wider hover:text-white transition-colors flex items-center gap-2">
                                    <span>Raw Metadata</span>
                                </summary>
                                <pre className="mt-4 bg-gray-950 p-4 rounded-lg overflow-x-auto text-xs text-gray-300 font-mono border border-gray-800">
                                    {JSON.stringify(metadata, null, 2)}
                                </pre>
                            </details>
                        </div>
                    </div>
                </div>
            </div>
            {showSearchModal && (
                <CivitaiSearchModal 
                    initialQuery={displayName}
                    onClose={() => setShowSearchModal(false)}
                    onSelect={(selectedModel) => runAutopopulate(selectedModel.id)}
                />
            )}
        </div>
    </ModalOverlay>
    );
}
