import { useState } from 'react';
import { Loader2, Download, Check, X } from 'lucide-react';
import { createPortal } from 'react-dom';
import toast from 'react-hot-toast';
import { sanitizeHtml } from '../../utils/sanitize';
import { api } from '../../api';
import { useCheckInstalledVersions } from '../../hooks/useCivitaiSearch';
import { useEscapeKey } from '../../hooks/useEscapeKey';
import { formatBytes, KB } from '../../utils/bytes';
import StatCard from '../ui/StatCard';

export default function ModelImportCard({ model, onCancel }) {
    // Escape dismisses, matching the shared ModalOverlay dialogs and the
    // "Esc → Close modals" line in KeyboardShortcutsModal.
    useEscapeKey(onCancel);
    const [selectedVersionId, setSelectedVersionId] = useState(model.modelVersions?.[0]?.id);
    const [activeImageIndex, setActiveImageIndex] = useState(0);
    const [installing, setInstalling] = useState(false);
    const { data: installedVersions = [] } = useCheckInstalledVersions(model.id);

    const selectedVersion = model.modelVersions?.find(v => v.id === parseInt(selectedVersionId)) || model.modelVersions?.[0];
    const primaryFile = selectedVersion?.files?.find(f => f.primary) || selectedVersion?.files?.[0];
    const selectedVersionPreviewId = selectedVersion?.civitai_version_id || selectedVersion?.id;
    
    const versionImages = selectedVersion?.images || [];
    const directPreviewImage = versionImages[activeImageIndex]?.url || versionImages[0]?.url || null;
    const cachedPreviewImage = model.id
        ? `/api/v2/models/preview/${model.id}${selectedVersionPreviewId ? `?version_id=${selectedVersionPreviewId}&image_index=${activeImageIndex}` : `?image_index=${activeImageIndex}`}`
        : null;
    const previewImage = directPreviewImage || cachedPreviewImage;

    const allVersions = model.modelVersions || [];
    const uninstalledVersions = allVersions.filter(v => !installedVersions.includes(v.id));
    const isSelectedVersionInstalled = installedVersions.includes(parseInt(selectedVersionId));

    const handleAddToLibrary = async (installAll = false) => {
        if (!allVersions.length) return;

        const versionsToInstall = installAll
            ? uninstalledVersions
            : [selectedVersion].filter(Boolean);

        if (!versionsToInstall.length) {
            toast.error("No uninstalled versions to install.");
            return;
        }

        if (!installAll && isSelectedVersionInstalled) {
            toast.error(`${selectedVersion.name} is already installed. Select a different version.`);
            return;
        }

        setInstalling(true);
        try {
            const payload = {
                civitai_data: model,
                selected_versions: versionsToInstall.map((v, idx) => ({
                    version_id: v.id,
                    is_default: idx === 0 && !installedVersions.length
                }))
            };

            // Trailing slash: the collection route is `@router.post("/")`, so
            // the bare path answered 307 and re-issued the POST.
            const result = await api.post('/api/v2/models/', payload);
            if (installAll) {
                toast.success(`Installing ${versionsToInstall.length} version(s) of ${model.name}. Workers will download on next sync.`);
            } else if (result.skipped_versions?.length > 0) {
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
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4 overflow-y-auto">
            {/* `h-[80vh]` + `overflow-hidden` + a FIXED 400px left pane meant the
                two-column layout could not reflow: below `sm`, the 400px pane
                exceeded the available width (viewport minus the p-4 backdrop),
                `flex-1` on the right collapsed to 0, and the parent's
                `overflow-hidden` clipped the overflow with no scroll. The version
                selector and the Install button were unreachable on a phone with
                no way to reach them — the one dialog whose entire purpose is
                choosing a version and installing.

                Fixed by stacking below `sm` (the left pane becomes full-width
                and the whole dialog scrolls) and only side-by-side from `sm` up.
                `max-h`/`overflow-y-auto` on the outer panel keeps the footer
                reachable on a short landscape viewport too. */}
            <div className="bg-gray-900 w-full max-w-5xl h-[80vh] max-h-[90vh] rounded-2xl border border-gray-800 flex flex-col sm:flex-row overflow-y-auto sm:overflow-hidden shadow-2xl">
                {/* Left: Images */}
                <div className="w-full sm:w-[400px] sm:shrink-0 bg-gray-950 p-4 sm:border-r border-gray-800 flex flex-col gap-4 overflow-y-auto relative">
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
                <div className="flex-1 p-6 space-y-4 md:space-y-6 overflow-y-auto relative flex flex-col">
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
                        <button
                            onClick={onCancel}
                            className="p-2 hover:bg-gray-800 rounded-full transition-colors"
                            aria-label="Close model import"
                            title="Close"
                        >
                            <X size={24} aria-hidden="true" />
                        </button>
                    </div>

                    <div className="bg-gray-800/50 p-4 rounded-xl border border-gray-700">
                        <div className="flex justify-between items-center mb-2">
                            <label className="block text-xs font-medium text-gray-500">
                                Select Version
                                {allVersions.length > 1 && (
                                    <span className="ml-1 text-gray-400">
                                        ({allVersions.length} available{uninstalledVersions.length > 0 ? `, ${uninstalledVersions.length} not installed` : ''})
                                    </span>
                                )}
                            </label>
                        </div>
                        <select
                            value={selectedVersionId}
                            onChange={(e) => {
                                setSelectedVersionId(e.target.value);
                                setActiveImageIndex(0);
                            }}
                            className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm focus:ring-2 focus:ring-blue-500 outline-none mb-2"
                        >
                            {allVersions.map(v => {
                                const vInstalled = installedVersions.includes(v.id);
                                return (
                                    <option key={v.id} value={v.id}>
                                        {v.name}{v.baseModel ? ` (${v.baseModel})` : ''}{vInstalled ? ' ✓ Installed' : ''}
                                    </option>
                                );
                            })}
                        </select>

                        {allVersions.length > 1 && (
                            <div className="flex flex-wrap gap-1.5 mb-3 max-h-24 overflow-y-auto pt-1">
                                {allVersions.map((v) => {
                                    const isInst = installedVersions.includes(v.id);
                                    const isCurrent = String(v.id) === String(selectedVersionId);
                                    return (
                                        <button
                                            key={v.id}
                                            type="button"
                                            onClick={() => {
                                                setSelectedVersionId(v.id);
                                                setActiveImageIndex(0);
                                            }}
                                            className={`text-2xs px-2.5 py-1 rounded-md border transition-all flex items-center gap-1 ${
                                                isCurrent
                                                    ? 'bg-blue-600/40 border-blue-500 text-blue-200 ring-1 ring-blue-500/50'
                                                    : isInst
                                                    ? 'bg-gray-800/80 border-gray-700 text-gray-400 hover:text-gray-200'
                                                    : 'bg-gray-900 border-gray-700 text-gray-300 hover:border-gray-500'
                                            }`}
                                        >
                                            {isInst && <Check size={11} className="text-green-400 flex-shrink-0" />}
                                            <span className="truncate max-w-[140px]">{v.name}</span>
                                            {v.baseModel && <span className="text-gray-500">({v.baseModel})</span>}
                                        </button>
                                    );
                                })}
                            </div>
                        )}

                        {selectedVersion && (
                            <div className="flex gap-4 text-sm text-gray-400 border-t border-gray-700/50 pt-3">
                                <div><span className="text-gray-500">Base Model:</span> <span className="text-white">{selectedVersion.baseModel || 'Unknown'}</span></div>
                                <div><span className="text-gray-500">File Size:</span> <span className="text-white">{primaryFile ? formatBytes(primaryFile.sizeKB * KB) : 'Unknown'}</span></div>
                            </div>
                        )}
                    </div>

                    {/* Stats */}
                    {model.stats && (
                        <div className="grid grid-cols-2 gap-4 bg-gray-800/30 p-4 rounded-xl border border-gray-700/50">
                            <StatCard
                                label="Downloads"
                                value={(model.stats.downloadCount || 0).toLocaleString()}
                                colorClass="text-white"
                                labelClass="text-xs text-gray-500 uppercase tracking-wider"
                            />
                            <StatCard
                                label="Likes"
                                value={(model.stats.thumbsUpCount || 0).toLocaleString()}
                                colorClass="text-green-400"
                                labelClass="text-xs text-gray-500 uppercase tracking-wider"
                            />
                        </div>
                    )}

                    {/* Description */}
                    {model.description && (
                        <div className="space-y-2 flex-1 pb-20">
                            <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wider">Description</h3>
                            <div
                                className="prose prose-invert prose-sm max-w-none text-gray-300 bg-gray-950/30 p-4 rounded-xl border border-gray-800/50"
                                dangerouslySetInnerHTML={{ __html: sanitizeHtml(model.description) }}
                            />
                        </div>
                    )}

                    {/* Action Bar */}
                    <div className="absolute bottom-0 left-0 right-0 p-4 sm:p-6 bg-gradient-to-t from-gray-900 via-gray-900 to-transparent flex flex-col sm:flex-row gap-2.5">
                        {allVersions.length > 1 && uninstalledVersions.length > 1 && (
                            <button
                                onClick={() => handleAddToLibrary(true)}
                                disabled={installing}
                                className="flex-1 py-3 px-4 rounded-xl font-medium flex items-center justify-center gap-2 shadow-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 transition-colors"
                            >
                                {installing ? <Loader2 className="animate-spin" size={18} /> : <Download size={18} />}
                                <span>Install All ({uninstalledVersions.length} new)</span>
                            </button>
                        )}
                        <button
                            onClick={() => handleAddToLibrary(false)}
                            disabled={installing || isSelectedVersionInstalled}
                            className={`flex-1 py-3 px-4 rounded-xl font-medium flex items-center justify-center gap-2 shadow-lg transition-colors ${
                                isSelectedVersionInstalled
                                    ? 'bg-gray-700 text-gray-400 cursor-not-allowed'
                                    : 'bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white'
                            }`}
                        >
                            {installing ? <Loader2 className="animate-spin" size={18} /> : isSelectedVersionInstalled ? <Check size={18} /> : <Download size={18} />}
                            <span>{isSelectedVersionInstalled ? `${selectedVersion?.name || 'Version'} Installed` : `Add ${selectedVersion?.name || 'Selected'} to Library`}</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>,
        document.body
    );
}
