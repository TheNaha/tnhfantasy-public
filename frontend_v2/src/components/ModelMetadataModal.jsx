import { X, Copy, Check, ExternalLink } from 'lucide-react';
import { useState } from 'react';
import toast from 'react-hot-toast';
import { copyToClipboard } from '../utils/clipboard';

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
                className="p-2 hover:bg-gray-800 rounded-full text-gray-400 hover:text-white transition-colors flex-shrink-0"
            >
                <X size={24} />
            </button>
        </div>
    );
}

export default function ModelMetadataModal({ metadata, onClose }) {
    const [copied, setCopied] = useState(null);
    const [activeImage, setActiveImage] = useState(null);

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

    // Get preview image
    const getPreviewImage = () => {
        if (activeImage) return activeImage;
        // V2 format
        if (isV2Format && metadata.preview) return metadata.preview;
        if (metadata.images?.length > 0) return metadata.images[0].url;
        if (civitaiId) return `/api/v2/models/preview/${civitaiId}`;
        // V1 format  
        if (metadata.modelVersions?.[0]?.images?.[0]?.url) return metadata.modelVersions[0].images[0].url;
        return null;
    };

    // Get gallery images - V2 format uses images array, V1 uses modelVersions
    const galleryImages = isV2Format
        ? (metadata.images || [])
        : (metadata.modelVersions?.[0]?.images || []);



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
        <div className="fixed inset-0 z-[60] bg-black/80 backdrop-blur-sm overflow-y-auto" onClick={onClose}>
            <div className="min-h-full md:min-h-0 flex items-center justify-center p-0 md:p-4">
                <div className="bg-gray-900 w-full max-w-5xl md:max-h-[calc(90*var(--vh,1vh))] rounded-none md:rounded-2xl border-x-0 md:border md:border-gray-700 flex flex-col md:flex-row shadow-2xl overflow-visible md:overflow-hidden" onClick={e => e.stopPropagation()}>

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
                                    onError={(e) => { e.target.style.display = 'none'; }}
                                />
                            </div>
                        )}

                        {/* Gallery thumbnails - 3 cols on mobile (Vertical look) */}
                        {galleryImages.length > 1 && (
                            <div className="grid grid-cols-3 gap-2">
                                {galleryImages.slice(0, 9).map((img, i) => (
                                    <button
                                        key={i}
                                        onClick={() => setActiveImage(img.url)}
                                        className={`aspect-square rounded overflow-hidden border ${activeImage === img.url ? 'border-blue-500' : 'border-gray-800'} hover:border-gray-600 transition-all`}
                                    >
                                        <img src={img.url} alt={`Preview ${i}`} className="w-full h-full object-cover" loading="lazy" />
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
                    <div className="p-4 md:p-6 space-y-4 md:space-y-6">
                        {/* Stats */}
                        <div className="grid grid-cols-3 gap-4 bg-gray-800/30 p-4 rounded-xl border border-gray-700/50">
                            <div className="text-center">
                                <div className="text-lg font-bold text-white">{(stats.downloads || 0).toLocaleString()}</div>
                                <div className="text-xs text-gray-500 uppercase tracking-wider">Downloads</div>
                            </div>
                            <div className="text-center">
                                <div className="text-lg font-bold text-green-400">{(stats.thumbsUp || 0).toLocaleString()}</div>
                                <div className="text-xs text-gray-500 uppercase tracking-wider">Likes</div>
                            </div>
                            <div className="text-center">
                                <div className="text-lg font-bold text-blue-400">{baseModel}</div>
                                <div className="text-xs text-gray-500 uppercase tracking-wider">Base Model</div>
                            </div>
                        </div>

                        {/* Trigger Words */}
                        {trainedWords.length > 0 && (
                            <div className="space-y-2">
                                <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Trigger Words</h3>
                                <div className="flex flex-wrap gap-2">
                                    {trainedWords.map(word => (
                                        <button
                                            key={word}
                                            onClick={() => handleCopy(word, `word-${word}`)}
                                            className="group flex items-center gap-2 px-3 py-1.5 bg-blue-500/10 text-blue-300 rounded-lg text-sm border border-blue-500/20 hover:bg-blue-500/20 transition-all"
                                        >
                                            {word}
                                            {copied === `word-${word}` ? <Check size={12} /> : <Copy size={12} className="opacity-0 group-hover:opacity-100 transition-opacity" />}
                                        </button>
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
                                    dangerouslySetInnerHTML={{ __html: description }}
                                />
                            </div>
                        )}

                        {/* Version Description */}
                        {metadata.version_description && (
                            <div className="space-y-2">
                                <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Version Notes</h3>
                                <div
                                    className="prose prose-invert prose-sm max-w-none text-gray-300 bg-blue-950/20 p-4 rounded-xl border border-blue-800/30 break-words max-h-40 overflow-y-auto overflow-x-hidden select-text cursor-text [&_pre]:overflow-x-auto [&_pre]:max-w-full [&_pre]:text-xs [&_code]:break-all [&_code]:text-xs"
                                    dangerouslySetInnerHTML={{ __html: metadata.version_description }}
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
        </div>
    </div>
    );
}
