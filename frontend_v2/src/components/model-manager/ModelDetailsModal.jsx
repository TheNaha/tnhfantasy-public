import { useState, useEffect } from 'react';
import { X, Loader2, AlertCircle, ExternalLink, ChevronDown } from 'lucide-react';
import toast from 'react-hot-toast';

export default function ModelDetailsModal({ file, onClose, onDelete }) {
    const [activeImage, setActiveImage] = useState(null);
    const [selectedVersionId, setSelectedVersionId] = useState(null);

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
    const versionCount = file.version_count || versions.length || 1;

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
    const primaryFile = selectedVersion?.primary_file || selectedVersion?.files?.[0];

    // Get active image or first preview
    const getPreviewUrl = () => {
        if (activeImage) return activeImage;
        if (versionImages.length > 0) return versionImages[0].url;
        if (file.preview) return file.preview;
        if (civitaiId) return `/api/v2/models/preview/${civitaiId}`;
        return null;
    };

    const previewUrl = getPreviewUrl();

    // Reset active image when version changes
    useEffect(() => {
        setActiveImage(null);
    }, [selectedVersionId]);

    // Check if we have any meaningful data
    const hasData = displayName || civitaiId || baseModel !== "Unknown";

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm" onClick={onClose}>
            <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-4xl max-h-[90vh] overflow-y-auto flex flex-col md:flex-row" onClick={e => e.stopPropagation()}>

                {/* Left: Images */}
                <div className="w-full md:w-1/3 bg-black/50 p-4 space-y-4 overflow-y-auto border-r border-gray-800">
                    {previewUrl && (
                        <div className="aspect-[2/3] rounded-lg overflow-hidden border border-gray-800 bg-gray-900">
                            <img
                                src={previewUrl}
                                alt={displayName}
                                className="w-full h-full object-contain"
                                onError={(e) => { e.target.style.display = 'none'; }}
                            />
                        </div>
                    )}

                    {/* Image Gallery */}
                    {versionImages.length > 1 && (
                        <div className="grid grid-cols-3 gap-2">
                            {versionImages.map((img, i) => (
                                <button
                                    key={i}
                                    onClick={() => setActiveImage(img.url)}
                                    className={`aspect-square rounded-lg overflow-hidden border ${activeImage === img.url ? 'border-blue-500' : 'border-gray-800'} hover:border-gray-600 transition-all`}
                                    aria-label={`View preview image ${i + 1}`}
                                    aria-pressed={activeImage === img.url}
                                >
                                    <img src={img.url} alt={`Preview ${i}`} className="w-full h-full object-cover" loading="lazy" />
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                {/* Right: Details */}
                <div className="flex-1 p-6 space-y-6 overflow-y-auto">
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
                        <button onClick={onClose} className="p-2 hover:bg-gray-800 rounded-full transition-colors" aria-label="Close modal">
                            <X size={24} />
                        </button>
                    </div>

                    {/* Version Selector - only show if multiple versions */}
                    {versions.length > 1 && (
                        <div className="bg-gray-800/50 p-3 rounded-xl border border-gray-700">
                            <label className="block text-xs font-medium text-gray-500 mb-2">Installed Version</label>
                            <select
                                value={selectedVersionId || selectedVersion?.id || ''}
                                onChange={(e) => setSelectedVersionId(parseInt(e.target.value))}
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
                                                onClick={() => {
                                                    navigator.clipboard.writeText(word);
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
                                        dangerouslySetInnerHTML={{ __html: modelDescription }}
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
                                        dangerouslySetInnerHTML={{ __html: versionDescription }}
                                    />
                                </div>
                            )}

                            {/* Provider Status */}
                            {file.provider_statuses && Object.keys(file.provider_statuses).length > 0 && (
                                <div>
                                    <h3 className="text-sm font-medium text-gray-400 mb-2">Provider Status</h3>
                                    <div className="space-y-2">
                                        {Object.entries(file.provider_statuses).map(([providerId, statusData]) => {
                                            const status = typeof statusData === 'object' ? statusData.status : statusData;
                                            const colorClass = {
                                                ready: 'text-green-400 bg-green-500/20 border-green-500/30',
                                                installed: 'text-green-400 bg-green-500/20 border-green-500/30',
                                                downloading: 'text-yellow-400 bg-yellow-500/20 border-yellow-500/30',
                                                pending: 'text-gray-400 bg-gray-500/20 border-gray-500/30',
                                                failed: 'text-red-400 bg-red-500/20 border-red-500/30'
                                            }[status] || 'text-gray-400 bg-gray-500/20 border-gray-500/30';

                                            return (
                                                <div key={providerId} className={`flex items-center justify-between px-3 py-2 rounded-lg border ${colorClass}`}>
                                                    <span className="text-sm">{providerId.replace('modal-', '')}</span>
                                                    <span className="text-xs capitalize">{status}</span>
                                                </div>
                                            );
                                        })}
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
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
