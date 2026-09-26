import { useState } from 'react';
import { X, AlertCircle, ExternalLink, Wand2, RefreshCw } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import DOMPurify from 'dompurify';
import { api } from '../../api';
import ModalOverlay from '../common/ModalOverlay';
import CivitaiSearchModal from './CivitaiSearchModal';
import AutopopulateSelector from './AutopopulateSelector';
import { copyToClipboard } from '../../utils/clipboard';

export default function ModelDetailsModal({ file, providers = [], onClose }) {
    const [activeImageIndex, setActiveImageIndex] = useState(null);
    const [selectedVersionId, setSelectedVersionId] = useState(null);
    const [showSearchModal, setShowSearchModal] = useState(false);
    const [showAutopopulateSelector, setShowAutopopulateSelector] = useState(false);
    const [refreshing, setRefreshing] = useState(false);
    const queryClient = useQueryClient();
    
    if (!file) return null;

    // V2 format: data is at root level, not nested in metadata
    const displayName = file.display_name || file.name;
    const modelType = file.type || "Unknown Type";
    const tags = file.tags || [];
    const stats = file.stats || {};
    const civitaiId = file.civitai_id;
    const modelDescription = file.description; // Model-level description
    const versions = file.versions || [];
    const images = file.images || [];
    const creator = file.creator || {};

    // Get selected version (default to first/default version)
    const selectedVersion = selectedVersionId
        ? versions.find(v => v.id === selectedVersionId || v.civitai_version_id === selectedVersionId)
        : versions.find(v => v.is_default) || versions[0];

    // Get version-specific data
    const versionName = selectedVersion?.name || file.default_version || "";
    const baseModel = selectedVersion?.base_model || file.base_model || "Unknown";
    const trainedWords = selectedVersion?.trained_words || file.trained_words || [];
    const versionDescription = selectedVersion?.description || file.version_description;
    const versionImages = selectedVersion?.images || images;
    const versionIdForPreview = selectedVersion?.civitai_version_id || selectedVersion?.id;

    const versionImageItems = versionImages.map((img, index) => {
        const directUrl = img?.url || null;
        if (!directUrl && !civitaiId) {
            return null;
        }

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
        };
    }).filter(Boolean);

    // Get active image or first preview
    const getPreviewUrl = () => {
        const activeItem = activeImageIndex !== null ? versionImageItems[activeImageIndex] : null;
        if (activeItem?.cachedUrl || activeItem?.directUrl) {
            return activeItem.cachedUrl || activeItem.directUrl;
        }

        const firstVersionImage = versionImageItems[0];
        if (firstVersionImage?.cachedUrl || firstVersionImage?.directUrl) {
            return firstVersionImage.cachedUrl || firstVersionImage.directUrl;
        }

        if (file.preview) return file.preview;
        if (civitaiId) {
            const params = new URLSearchParams({ image_index: '0' });
            if (versionIdForPreview) {
                params.set('version_id', String(versionIdForPreview));
            }
            return `/api/v2/models/preview/${civitaiId}?${params.toString()}`;
        }
        return null;
    };

    const previewUrl = getPreviewUrl();
    const previewFallbackUrl = (
        (activeImageIndex !== null ? versionImageItems[activeImageIndex]?.directUrl : null)
        || versionImageItems[0]?.directUrl
        || file.preview
        || null
    );

    const isAutoDiscovered = modelDescription?.includes("Auto-discovered");

    const handleAutopopulate = async (civitaiId = null) => {
        if (!file.model_id) {
            toast.error("Model has no database ID");
            return;
        }
        try {
            const payload = civitaiId ? { civitai_id: civitaiId } : {};
            await api.post(`/api/v2/models/${file.model_id}/autopopulate`, payload);
            toast.success(isAutoDiscovered ? "Model details autopopulated!" : "Model metadata refetched!");
            queryClient.invalidateQueries({ queryKey: ['models'] });
            queryClient.invalidateQueries({ queryKey: ['model', file.model_id] });
            setShowSearchModal(false);
            onClose();
        } catch (e) {
            toast.error("Failed to sync metadata: " + (e.message || "Unknown error"));
        }
    };

    const handleDirectRefresh = async () => {
        if (!file.model_id) {
            toast.error("Model has no database ID");
            return;
        }
        setRefreshing(true);
        try {
            await api.post(`/api/v2/models/maintenance/${file.model_id}/resync`);
            toast.success("Model metadata refreshed from CivitAI!");
            queryClient.invalidateQueries({ queryKey: ['models'] });
            queryClient.invalidateQueries({ queryKey: ['model', file.model_id] });
            onClose();
        } catch (e) {
            toast.error("Failed to refresh metadata: " + (e.message || "Unknown error"));
        } finally {
            setRefreshing(false);
        }
    };

    // Check if we have any meaningful data
    const hasData = displayName || civitaiId || baseModel !== "Unknown";

    return (
        <ModalOverlay onClose={onClose} className="z-50 bg-black/80 backdrop-blur-sm">
            <div
                role="dialog"
                aria-modal="true"
                aria-label={displayName}
                className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-4xl max-h-[90vh] overflow-y-auto flex flex-col md:flex-row" onClick={e => e.stopPropagation()}>

                {/* Left: Images */}
                <div className="w-full md:w-1/3 bg-black/50 p-4 space-y-4 overflow-y-auto border-r border-gray-800">
                    {previewUrl && (
                        <div className="aspect-[2/3] rounded-lg overflow-hidden border border-gray-800 bg-gray-900">
                            <img
                                src={previewUrl}
                                alt={displayName}
                                className="w-full h-full object-contain"
                                decoding="async"
                                onError={(e) => {
                                    if (previewFallbackUrl && e.currentTarget.src !== previewFallbackUrl) {
                                        e.currentTarget.src = previewFallbackUrl;
                                        return;
                                    }
                                    e.target.style.display = 'none';
                                }}
                            />
                        </div>
                    )}

                    {/* Image Gallery */}
                    {versionImageItems.length > 1 && (
                        <div className="grid grid-cols-3 gap-2">
                            {versionImageItems.map((img, i) => (
                                <button
                                    key={i}
                                    onClick={() => setActiveImageIndex(i)}
                                    className={`aspect-square rounded-lg overflow-hidden border ${activeImageIndex === i ? 'border-blue-500' : 'border-gray-800'} hover:border-gray-600 transition-all`}
                                    aria-label={`View preview image ${i + 1}`}
                                    aria-pressed={activeImageIndex === i}
                                >
                                    <img
                                        src={img.cachedUrl || img.directUrl}
                                        alt={`Preview ${i}`}
                                        className="w-full h-full object-cover"
                                        loading="lazy"
                                        decoding="async"
                                        fetchPriority="low"
                                        onError={(e) => {
                                            if (img.directUrl && e.currentTarget.src !== img.directUrl) {
                                                e.currentTarget.src = img.directUrl;
                                                return;
                                            }
                                            e.currentTarget.style.display = 'none';
                                        }}
                                    />
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                {/* Right: Details */}
                <div className="flex-1 p-6 space-y-4 md:space-y-6 overflow-y-auto">
                    <div className="flex justify-between items-start">
                        <div>
                            <h2 className="text-2xl font-bold text-white">{displayName}</h2>
                            <div className="flex items-center gap-2 mt-1 text-sm text-gray-400 flex-wrap">
                                <span className="px-2 py-0.5 bg-gray-800 rounded border border-gray-700">{modelType}</span>
                                {baseModel && baseModel !== "Unknown" && (
                                    <span className="px-2 py-0.5 bg-purple-800/50 rounded border border-purple-700/50">{baseModel}</span>
                                )}
                                {creator?.username && (
                                    <span className="text-gray-500">by {creator.username}</span>
                                )}
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
                            {file.model_id && (
                                <>
                                    {civitaiId && !isAutoDiscovered && (
                                        <button
                                            onClick={handleDirectRefresh}
                                            disabled={refreshing}
                                            className="flex items-center gap-2 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-gray-300 hover:text-white hover:border-gray-500 transition-colors disabled:opacity-50 text-sm font-medium"
                                            title="Refresh metadata from CivitAI"
                                        >
                                            <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
                                            {refreshing ? 'Refreshing...' : 'Resync Metadata'}
                                        </button>
                                    )}
                                    <button
                                        onClick={() => isAutoDiscovered ? setShowAutopopulateSelector(true) : setShowSearchModal(true)}
                                        className="p-2 bg-blue-900 border border-blue-700 rounded-lg text-blue-300 hover:text-white hover:border-blue-500 transition-colors"
                                        title={isAutoDiscovered ? "Match with CivitAI" : "Search CivitAI for match"}
                                        aria-label={isAutoDiscovered ? "Match with CivitAI" : "Search CivitAI for this model"}
                                    >
                                        <Wand2 size={20} />
                                    </button>
                                </>
                            )}
                            <button onClick={onClose} className="p-2 hover:bg-gray-800 rounded-full transition-colors" aria-label="Close modal">
                                <X size={24} />
                            </button>
                        </div>
                    </div>

                    {/* Version Selector - only show if multiple versions */}
                    {versions.length > 1 && (
                        <div className="bg-gray-800/50 p-3 rounded-xl border border-gray-700">
                            <label className="block text-xs font-medium text-gray-500 mb-2">Installed Version</label>
                            <select
                                value={selectedVersionId || selectedVersion?.id || ''}
                                onChange={(e) => {
                                    setSelectedVersionId(parseInt(e.target.value));
                                    setActiveImageIndex(null);
                                }}
                                className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                            >
                                {versions.map(v => (
                                    <option key={v.id || v.civitai_version_id} value={v.id || v.civitai_version_id}>
                                        {v.name}{v.base_model ? ` (${v.base_model})` : ''}{v.is_default ? ' • Default' : ''}
                                    </option>
                                ))}
                            </select>
                        </div>
                    )}

                    {hasData ? (
                        <>
                            {/* Stats */}
                            <div className="grid grid-cols-3 gap-4 bg-gray-800/50 p-4 rounded-xl border border-gray-700">
                                <div className="text-center">
                                    <div className="text-lg font-bold text-white">{(stats.downloads || 0).toLocaleString()}</div>
                                    <div className="text-xs text-gray-500">Downloads</div>
                                </div>
                                <div className="text-center">
                                    <div className="text-lg font-bold text-green-400">{(stats.thumbsUp || 0).toLocaleString()}</div>
                                    <div className="text-xs text-gray-500">Likes</div>
                                </div>
                                <div className="text-center">
                                    <div className="text-lg font-bold text-white">{baseModel}</div>
                                    <div className="text-xs text-gray-500">Base Model</div>
                                </div>
                            </div>

                            {/* Trigger Words */}
                            {trainedWords.length > 0 && (
                                <div>
                                    <h3 className="text-sm font-medium text-gray-400 mb-2">Trigger Words</h3>
                                    <div className="flex flex-wrap gap-2">
                                        {trainedWords.map(word => (
                                            <span key={word} className="px-2 py-1 bg-blue-500/20 text-blue-300 rounded text-xs border border-blue-500/30 select-all cursor-pointer hover:bg-blue-500/30"
                                                onClick={async () => {
                                                    await copyToClipboard(word);
                                                    toast.success("Copied!");
                                                }}
                                            >
                                                {word}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Model Description */}
                            {modelDescription && (
                                <div>
                                    <h3 className="text-sm font-medium text-gray-400 mb-2">Model Description</h3>
                                    <div
                                        className="prose prose-invert prose-sm max-w-none text-gray-300 bg-gray-950/30 p-4 rounded-xl border border-gray-800/50 break-words max-h-40 overflow-y-auto"
                                        dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(modelDescription) }}
                                    />
                                </div>
                            )}

                            {/* Version Description */}
                            {versionDescription && (
                                <div>
                                    <h3 className="text-sm font-medium text-gray-400 mb-2">
                                        Version Notes {versionName && <span className="text-gray-500">({versionName})</span>}
                                    </h3>
                                    <div
                                        className="prose prose-invert prose-sm max-w-none text-gray-300 bg-blue-950/20 p-4 rounded-xl border border-blue-800/30 break-words max-h-40 overflow-y-auto"
                                        dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(versionDescription) }}
                                    />
                                </div>
                            )}

                            {/* Provider Status */}
                            {file.provider_statuses && Object.keys(file.provider_statuses).length > 0 && (
                                <div className="mt-6 pt-4 border-t border-gray-800">
                                    <h3 className="text-sm font-medium text-gray-400 mb-3">Provider Status</h3>
                                    <div className="space-y-2">
                                        {Object.entries(file.provider_statuses)
                                            .filter(([providerId]) => {
                                                const p = providers.find(p => p.id === providerId);
                                                if (!p) return true; // keep if provider info is missing
                                                const isLlmFile = file.path?.startsWith('models/llm');
                                                if (isLlmFile && p.worker_type !== 'llm') return false;
                                                if (!isLlmFile && p.worker_type === 'llm') return false;
                                                return true;
                                            })
                                            .map(([providerId, statusData]) => {
                                            const status = typeof statusData === 'object' ? statusData.status : statusData;
                                            const colorClass = {
                                                ready: 'text-green-400 bg-green-500/20 border-green-500/30',
                                                installed: 'text-green-400 bg-green-500/20 border-green-500/30',
                                                partial: 'text-amber-400 bg-amber-500/20 border-amber-500/30',
                                                downloading: 'text-yellow-400 bg-yellow-500/20 border-yellow-500/20',
                                                pending: 'text-gray-400 bg-gray-500/20 border-gray-500/30',
                                                failed: 'text-red-400 bg-red-500/20 border-red-500/30'
                                            }[status] || 'text-gray-400 bg-gray-500/20 border-gray-500/30';

                                            return (
                                                <div key={providerId} className={`flex items-center justify-between px-3 py-2 rounded-lg border ${colorClass}`}>
                                                    <span className="text-sm">{providerId.replace('modal-', '')}</span>
                                                    <span className="text-xs font-medium capitalize">{status}</span>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}

                            {/* Autopopulate prompt for auto-discovered models with partial data */}
                            {isAutoDiscovered && file.model_id && (
                                <div className="bg-yellow-900/20 border border-yellow-700/30 rounded-xl p-4">
                                    <div className="flex items-start gap-3">
                                        <AlertCircle className="text-yellow-400 mt-0.5 shrink-0" size={18} />
                                        <div className="flex-1">
                                            <p className="text-sm text-yellow-300 font-medium">Auto-discovered Model</p>
                                            <p className="text-xs text-yellow-400/70 mt-1">This model was auto-discovered from provider storage. Some details may be incomplete.</p>
                                            <button
                                                onClick={() => setShowAutopopulateSelector(true)}
                                                className="mt-2 text-xs px-3 py-1.5 bg-blue-900 border border-blue-700 rounded-lg text-blue-300 hover:text-white hover:border-blue-500 transition-colors inline-flex items-center gap-1"
                                            >
                                                <Wand2 size={12} />
                                                Match with CivitAI
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Tags */}
                            {tags.length > 0 && (
                                <div>
                                    <h3 className="text-sm font-medium text-gray-400 mb-2">Tags</h3>
                                    <div className="flex flex-wrap gap-2">
                                        {tags.map(tag => (
                                            <span key={tag} className="px-2 py-1 bg-gray-800 text-gray-400 rounded-full text-xs border border-gray-700">
                                                {tag}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* File Info */}
                            <div className="text-xs text-gray-500 pt-4 border-t border-gray-800 space-y-1">
                                <p>Filename: <span className="text-gray-400">{file.name}</span></p>
                                <p>Size: <span className="text-gray-400">{file.size > 0 ? (file.size / 1024 / 1024 / 1024).toFixed(2) + " GB" : "Unknown"}</span></p>
                                {civitaiId && (
                                    <a
                                        href={`https://civitai.com/models/${civitaiId}`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300"
                                    >
                                        View on CivitAI <ExternalLink size={12} />
                                    </a>
                                )}
                            </div>
                        </>
                    ) : (
                        <div className="text-center py-10 text-gray-500">
                            <AlertCircle className="mx-auto mb-2 opacity-50" />
                            <p>No metadata available for this model.</p>
                            <p className="text-xs mt-2">This model may have been added before V2 migration.</p>
                            {file.model_id && (
                                <button
                                    onClick={() => setShowAutopopulateSelector(true)}
                                    className="mt-4 px-4 py-2 bg-blue-900 border border-blue-700 rounded-lg text-blue-300 hover:text-white hover:border-blue-500 transition-colors text-sm"
                                >
                                    <Wand2 size={16} className="inline mr-2" />
                                    Match with CivitAI
                                </button>
                            )}
                        </div>
                    )}
                </div>
            </div>
            
            {showAutopopulateSelector && (
                <AutopopulateSelector
                    modelId={file.model_id}
                    modelName={displayName}
                    modelType={modelType}
                    modelDirectory={file.directory}
                    onClose={() => setShowAutopopulateSelector(false)}
                    onComplete={() => {
                        queryClient.invalidateQueries({ queryKey: ['models'] });
                        queryClient.invalidateQueries({ queryKey: ['model', file.model_id] });
                    }}
                />
            )}
            {showSearchModal && (
                <CivitaiSearchModal 
                    initialQuery={displayName}
                    onClose={() => setShowSearchModal(false)}
                    onSelect={(selectedModel) => handleAutopopulate(selectedModel.id)}
                />
            )}
        </ModalOverlay>
    );
}
