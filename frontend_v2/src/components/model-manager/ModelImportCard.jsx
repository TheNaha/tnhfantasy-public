import { useState, useEffect } from 'react';
import { Loader2, Download, Check } from 'lucide-react';
import toast from 'react-hot-toast';
import DOMPurify from 'dompurify';
import { api } from '../../api';

export default function ModelImportCard({ model, onCancel }) {
    const [selectedVersionId, setSelectedVersionId] = useState(model.modelVersions?.[0]?.id);
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
    const directPreviewImage = selectedVersion?.images?.[0]?.url || null;
    const cachedPreviewImage = model.id
        ? `/api/v2/models/preview/${model.id}${selectedVersionPreviewId ? `?version_id=${selectedVersionPreviewId}&image_index=0` : '?image_index=0'}`
        : null;
    const previewImage = directPreviewImage || cachedPreviewImage;
    const isSelectedVersionInstalled = installedVersions.includes(parseInt(selectedVersionId));

    const handleAddToLibrary = async () => {
        if (!selectedVersion || !primaryFile) return;

        // Warn if version is already installed
        if (isSelectedVersionInstalled) {
            toast.error(`${selectedVersion.name} is already installed. Select a different version.`);
            return;
        }

        setInstalling(true);
        try {
            // Use V2 API which stores normalized version data
            const payload = {
                civitai_data: model,  // Full CivitAI response
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

    return (
        <div className="bg-gray-900 rounded-xl overflow-hidden border border-gray-700 flex flex-col md:flex-row max-w-4xl mx-auto">
            {/* Preview Image */}
            <div className="w-full md:w-1/3 aspect-[2/3] md:aspect-auto relative bg-gray-800">
                {previewImage ? (
                    <img
                        src={previewImage}
                        alt={model.name}
                        className="absolute inset-0 w-full h-full object-cover"
                        decoding="async"
                        fetchPriority="low"
                        onError={(e) => {
                            if (cachedPreviewImage && e.currentTarget.src !== cachedPreviewImage) {
                                e.currentTarget.src = cachedPreviewImage;
                                return;
                            }
                            e.currentTarget.style.display = 'none';
                        }}
                    />
                ) : (
                    <div className="flex items-center justify-center h-full text-gray-600">No Preview</div>
                )}
            </div>

            {/* Details */}
            <div className="p-6 flex-1 flex flex-col gap-4">
                <div>
                    <div className="flex justify-between items-start">
                        <h2 className="text-2xl font-bold text-white">{model.name}</h2>
                        <span className="px-2 py-1 bg-gray-800 rounded text-xs text-gray-400 border border-gray-700">
                            {model.type}
                        </span>
                    </div>
                    <p className="text-gray-400 text-sm mt-2 line-clamp-3" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(model.description) }}></p>
                </div>

                <div className="bg-gray-800/50 p-4 rounded-lg border border-gray-700 space-y-3">
                    <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1">Select Version</label>
                        <select
                            value={selectedVersionId}
                            onChange={(e) => setSelectedVersionId(e.target.value)}
                            className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm"
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
                    </div>

                    {selectedVersion && (
                        <div className="text-xs text-gray-400 space-y-1">
                            <div className="flex justify-between">
                                <span>Base Model:</span>
                                <span className="text-white">{selectedVersion.baseModel || 'Unknown'}</span>
                            </div>
                            <div className="flex justify-between">
                                <span>File Size:</span>
                                <span className="text-white">
                                    {primaryFile ? (primaryFile.sizeKB / 1024).toFixed(2) + ' MB' : 'Unknown'}
                                </span>
                            </div>
                        </div>
                    )}
                </div>

                <div className="mt-auto flex gap-3">
                    <button
                        onClick={handleAddToLibrary}
                        disabled={installing || isSelectedVersionInstalled}
                        className={`flex-1 py-3 rounded-xl font-medium flex items-center justify-center gap-2 ${isSelectedVersionInstalled
                                ? 'bg-gray-700 text-gray-400 cursor-not-allowed'
                                : 'bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white'
                            }`}
                        aria-label={isSelectedVersionInstalled ? "Model already installed" : "Add to Library"}
                    >
                        {installing ? <Loader2 className="animate-spin" /> : isSelectedVersionInstalled ? <Check size={18} /> : <Download size={18} />}
                        {isSelectedVersionInstalled ? 'Already Installed' : 'Add to Library'}
                    </button>
                    <button
                        onClick={onCancel}
                        className="px-4 py-3 bg-gray-800 hover:bg-gray-700 rounded-xl text-gray-300"
                        aria-label="Cancel import"
                    >
                        Cancel
                    </button>
                </div>
            </div>
        </div>
    );
}
