import { useState, useEffect } from 'react';
import { Loader2, Download, Check, X } from 'lucide-react';
import { createPortal } from 'react-dom';
import toast from 'react-hot-toast';
import DOMPurify from 'dompurify';
import { api } from '../../api';

export default function ModelImportCard({ model, onCancel }) {
    const [selectedVersionId, setSelectedVersionId] = useState(model.modelVersions?.[0]?.id);
    const [activeImageIndex, setActiveImageIndex] = useState(0);
    const [installing, setInstalling] = useState(false);
    const [installedVersions, setInstalledVersions] = useState([]);

    // Check which versions are already installed
    useEffect(() => {
        if (model.id) {
            api.get(`/api/v2/models/check-installed/${model.id}`)
                .then(data => setInstalledVersions(data.installed_versions || []))
                .catch(() => setInstalledVersions([]));
        }
    }, [model.id]);

    const selectedVersion = model.modelVersions?.find(v => v.id === parseInt(selectedVersionId)) || model.modelVersions?.[0];
    const primaryFile = selectedVersion?.files?.find(f => f.primary) || selectedVersion?.files?.[0];
    const selectedVersionPreviewId = selectedVersion?.civitai_version_id || selectedVersion?.id;
    
    const versionImages = selectedVersion?.images || [];
    const directPreviewImage = versionImages[activeImageIndex]?.url || versionImages[0]?.url || null;
    const cachedPreviewImage = model.id
        ? `/api/v2/models/preview/${model.id}${selectedVersionPreviewId ? `?version_id=${selectedVersionPreviewId}&image_index=${activeImageIndex}` : `?image_index=${activeImageIndex}`}`
        : null;
    const previewImage = directPreviewImage || cachedPreviewImage;

    const isSelectedVersionInstalled = installedVersions.includes(parseInt(selectedVersionId));

    const handleAddToLibrary = async () => {
        if (!selectedVersion || !primaryFile) return;

        if (isSelectedVersionInstalled) {
            toast.error(`${selectedVersion.name} is already installed. Select a different version.`);
            return;
        }

        setInstalling(true);
        try {
            const payload = {
                civitai_data: model,
                selected_versions: [
                    { version_id: parseInt(selectedVersionId), is_default: true }
                ]
            };

            const result = await api.post('/api/v2/models', payload);
            if (result.skipped_versions?.length > 0) {
                toast.success(`Added ${model.name} (${selectedVersion.name}). Skipped ${result.skipped_versions.length} already installed version(s).`);
            } else {
                toast.success(`Added ${model.name} (${selectedVersion.name}) to library. Workers will download on next sync.`);
            }
            onCancel();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setInstalling(false);
        }
    };

    return createPortal(
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4">
            <div className="bg-gray-900 w-full max-w-5xl h-[80vh] rounded-2xl border border-gray-800 flex overflow-hidden shadow-2xl">
                {/* Left: Images */}
                <div className="w-[400px] bg-gray-950 p-4 border-r border-gray-800 flex flex-col gap-4 overflow-y-auto relative">
                    {previewImage ? (
                        <div className="relative aspect-[2/3] rounded-xl overflow-hidden border border-gray-800 bg-gray-900 shrink-0">
                            <img
                                src={previewImage}
                                alt={model.name}
                                className="w-full h-full object-contain"
                                decoding="async"
                                onError={(e) => {
                                    if (cachedPreviewImage && e.currentTarget.src !== cachedPreviewImage) {
                                        e.currentTarget.src = cachedPreviewImage;
                                        return;
                                    }
                                    e.target.style.display = 'none';
                                }}
                            />
                        </div>
                    ) : (
                        <div className="relative aspect-[2/3] rounded-xl border border-gray-800 bg-gray-900 shrink-0 flex items-center justify-center text-gray-600">
                            No Preview
                        </div>
                    )}

                    {versionImages.length > 1 && (
                        <div className="grid grid-cols-3 gap-2 pb-20">
                            {versionImages.map((img, i) => (
                                <button
                                    key={i}
                                    onClick={() => setActiveImageIndex(i)}
                                    className={`aspect-square rounded-lg overflow-hidden border ${activeImageIndex === i ? 'border-blue-500' : 'border-gray-800'} hover:border-gray-600 transition-all`}
                                >
                                    <img
                                        src={img.url}
                                        alt={`Preview ${i}`}
                                        className="w-full h-full object-cover"
                                        loading="lazy"
                                    />
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                {/* Right: Details */}
                <div className="flex-1 p-6 space-y-6 overflow-y-auto relative flex flex-col">
                    <div className="flex justify-between items-start">
                        <div>
                            <h2 className="text-2xl font-bold text-white">{model.name}</h2>
                            <div className="flex items-center gap-2 mt-1 text-sm text-gray-400 flex-wrap">
                                <span className="px-2 py-0.5 bg-gray-800 rounded border border-gray-700">{model.type}</span>
                                {model.creator?.username && (
                                    <span className="text-gray-500">by {model.creator.username}</span>
                                )}
                            </div>
                        </div>
                        <button onClick={onCancel} className="p-2 hover:bg-gray-800 rounded-full transition-colors">
                            <X size={24} />
                        </button>
                    </div>

                    <div className="bg-gray-800/50 p-4 rounded-xl border border-gray-700">
                        <label className="block text-xs font-medium text-gray-500 mb-2">Select Version</label>
                        <select
                            value={selectedVersionId}
                            onChange={(e) => {
                                setSelectedVersionId(e.target.value);
                                setActiveImageIndex(0);
                            }}
                            className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm focus:ring-2 focus:ring-blue-500 outline-none mb-3"
                        >
                            {model.modelVersions?.map(v => {
                                const vInstalled = installedVersions.includes(v.id);
                                return (
                                    <option key={v.id} value={v.id}>
                                        {v.name}{v.baseModel ? ` (${v.baseModel})` : ''}{vInstalled ? ' ✓ Installed' : ''}
                                    </option>
                                );
                            })}
                        </select>

                        {selectedVersion && (
                            <div className="flex gap-4 text-sm text-gray-400 border-t border-gray-700/50 pt-3">
                                <div><span className="text-gray-500">Base Model:</span> <span className="text-white">{selectedVersion.baseModel || 'Unknown'}</span></div>
                                <div><span className="text-gray-500">File Size:</span> <span className="text-white">{primaryFile ? (primaryFile.sizeKB / 1024).toFixed(2) + ' MB' : 'Unknown'}</span></div>
                            </div>
                        )}
                    </div>

                    {/* Stats */}
                    {model.stats && (
                        <div className="grid grid-cols-2 gap-4 bg-gray-800/30 p-4 rounded-xl border border-gray-700/50">
                            <div className="text-center">
                                <div className="text-lg font-bold text-white">{(model.stats.downloadCount || 0).toLocaleString()}</div>
                                <div className="text-xs text-gray-500 uppercase tracking-wider">Downloads</div>
                            </div>
                            <div className="text-center">
                                <div className="text-lg font-bold text-green-400">{(model.stats.thumbsUpCount || 0).toLocaleString()}</div>
                                <div className="text-xs text-gray-500 uppercase tracking-wider">Likes</div>
                            </div>
                        </div>
                    )}

                    {/* Description */}
                    {model.description && (
                        <div className="space-y-2 flex-1 pb-20">
                            <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Description</h3>
                            <div
                                className="prose prose-invert prose-sm max-w-none text-gray-300 bg-gray-950/30 p-4 rounded-xl border border-gray-800/50"
                                dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(model.description) }}
                            />
                        </div>
                    )}

                    {/* Action Bar */}
                    <div className="absolute bottom-0 left-0 right-0 p-6 bg-gradient-to-t from-gray-900 via-gray-900 to-transparent">
                        <button
                            onClick={handleAddToLibrary}
                            disabled={installing || isSelectedVersionInstalled}
                            className={`w-full py-3 rounded-xl font-medium flex items-center justify-center gap-2 shadow-lg ${isSelectedVersionInstalled
                                ? 'bg-gray-700 text-gray-400 cursor-not-allowed'
                                : 'bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white'
                            }`}
                        >
                            {installing ? <Loader2 className="animate-spin" /> : isSelectedVersionInstalled ? <Check size={18} /> : <Download size={18} />}
                            {isSelectedVersionInstalled ? 'Already Installed' : 'Add to Library'}
                        </button>
                    </div>
                </div>
            </div>
        </div>,
        document.body
    );
}
