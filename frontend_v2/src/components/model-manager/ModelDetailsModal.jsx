import { useState, useMemo } from 'react';
import { X, AlertCircle, ExternalLink, Wand2, RefreshCw, Plus, Download, Loader2, Check } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { sanitizeHtml } from '../../utils/sanitize';
import { api, modelsApi, providersApi } from '../../api';
import ModalOverlay from '../common/ModalOverlay';
import CivitaiSearchModal from './CivitaiSearchModal';
import AutopopulateSelector from './AutopopulateSelector';
import { copyToClipboard } from '../../utils/clipboard';
import { formatBytes } from '../../utils/bytes';
import { QUERY_KEYS } from '../../constants/queryKeys';
import { installedVersionsKey } from '../../hooks/useCivitaiSearch';
import { useAutopopulateModel } from '../../hooks/useAutopopulate';

/**
 * Query keys whose pages carry a model's tag list. A new tag is only useful if
 * the list that filters on tags can see it, and there used to be two such lists:
 * the model manager's Installed tab and the in-generator ModelSelector.
 *
 * They were two independent caches of one list, under `['models', …]` and
 * `['installed-models', …]`, and every mutation here had to remember to
 * invalidate both. They now share `modelListKey` (`constants/queryKeys.js`),
 * whose keys all start with `[QUERY_KEYS.MODELS]`, so the prefix below reaches
 * every variant of the one list — including a future `pageSize` or a new
 * filter combination, which the old two-element literal would not have covered
 * had the shape moved again.
 */
const invalidateModelLists = (queryClient) => {
    queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.MODELS] });
};

const tagQueryKey = (modelId) => ['model-tags', modelId];

/**
 * Add and remove tags on one model.
 *
 * The read path cannot answer "is this tag mine?". `GET /api/files` returns
 * `tags` as bare strings — the ModelTag `source` column never leaves the
 * backend on that route — and the backend *refuses* to delete a CivitAI-owned
 * tag, because a resync would recreate it. So a delete control is rendered only
 * for a tag the maintenance endpoint has positively reported as `user`, and for
 * nothing else: while provenance is loading, after it failed, or for any tag it
 * did not mention, there is no delete control. An unhandled rejection from a
 * 404 is the alternative, and that is worse than not offering the button.
 */
export function ModelTagEditor({ modelId, tags = [] }) {
    const queryClient = useQueryClient();
    const [draft, setDraft] = useState('');

    const tagQuery = useQuery({
        queryKey: tagQueryKey(modelId),
        queryFn: () => modelsApi.listTags(modelId),
        enabled: !!modelId,
        staleTime: 30_000,
    });

    // tag -> 'user' | 'civitai' | undefined. A miss means "unknown", never
    // "civitai": the union constraint means a tag a user added first stays
    // user-owned, so an absent entry really is unknown, not known-bad.
    const sources = useMemo(() => {
        const map = new Map();
        for (const entry of tagQuery.data?.tags || []) {
            if (entry?.tag) map.set(entry.tag, entry.source);
        }
        return map;
    }, [tagQuery.data]);

    // Union of what the list payload carried and what the provenance endpoint
    // reports, so a tag added a moment ago is visible before the list refetch
    // lands. Order follows the list payload first, then anything new.
    const allTags = useMemo(() => {
        const ordered = [];
        const seen = new Set();
        for (const tag of tags) {
            if (tag && !seen.has(tag)) { seen.add(tag); ordered.push(tag); }
        }
        for (const tag of sources.keys()) {
            if (!seen.has(tag)) { seen.add(tag); ordered.push(tag); }
        }
        return ordered;
    }, [tags, sources]);

    const addMutation = useMutation({
        mutationFn: (tag) => modelsApi.addTag(modelId, tag),
        onSuccess: (result, tag) => {
            // Patch the provenance cache directly so the new tag renders (and is
            // deletable) immediately; the invalidation above is what makes it
            // *filterable*, which is the half that needs a round trip.
            queryClient.setQueryData(tagQueryKey(modelId), (prev) => {
                const existing = prev?.tags || [];
                if (existing.some((t) => t.tag === tag)) return prev;
                return { tags: [...existing, { tag, source: result?.source || 'user' }] };
            });
            invalidateModelLists(queryClient);
            setDraft('');
            toast.success(
                result?.created === false
                    ? `"${tag}" was already on this model`
                    : `Tagged "${tag}"`
            );
        },
        onError: (error) => toast.error(`Could not add tag: ${error.message}`),
    });

    const removeMutation = useMutation({
        mutationFn: (tag) => modelsApi.removeTag(modelId, tag),
        onSuccess: (_result, tag) => {
            queryClient.setQueryData(tagQueryKey(modelId), (prev) => ({
                tags: (prev?.tags || []).filter((t) => t.tag !== tag),
            }));
            invalidateModelLists(queryClient);
            toast.success(`Removed tag "${tag}"`);
        },
        onError: (error, tag) => {
            // A 404 is the backend declining, not a broken request: the row is
            // CivitAI's (or has already gone) and a resync would put it back.
            // Say that, and resync our own view of provenance, rather than
            // surfacing a bare status code or an unhandled rejection.
            if (error?.status === 404) {
                queryClient.invalidateQueries({ queryKey: tagQueryKey(modelId) });
                toast.error(
                    `"${tag}" is a CivitAI tag. Resyncs replace it, so it cannot be removed — add your own tag instead.`
                );
                return;
            }
            toast.error(`Could not remove tag: ${error.message}`);
        },
    });

    const submitDraft = (event) => {
        event.preventDefault();
        const tag = draft.trim();
        if (!tag) return;
        addMutation.mutate(tag);
    };

    const userTags = allTags.filter((tag) => sources.get(tag) === 'user');
    const otherTags = allTags.filter((tag) => sources.get(tag) !== 'user');
    const provenancePending = tagQuery.isPending;

    const renderTag = (tag, removable) => (
        <span
            key={tag}
            className={`px-2 py-1 rounded-full text-xs border flex items-center gap-1 ${
                removable
                    ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
                    : 'bg-gray-800 text-gray-400 border-gray-700'
            }`}
        >
            {tag}
            {removable && (
                <button
                    type="button"
                    onClick={() => removeMutation.mutate(tag)}
                    disabled={removeMutation.isPending}
                    className="text-emerald-400/70 hover:text-white transition-colors disabled:opacity-40"
                    aria-label={`Remove tag ${tag}`}
                >
                    <X size={12} />
                </button>
            )}
        </span>
    );

    return (
        <div className="space-y-3">
            {userTags.length > 0 && (
                <div>
                    <h4 className="text-2xs uppercase tracking-widest text-gray-500 mb-1.5">Your tags</h4>
                    <div className="flex flex-wrap gap-2">{userTags.map((tag) => renderTag(tag, true))}</div>
                </div>
            )}

            {otherTags.length > 0 && (
                <div>
                    <h4 className="text-2xs uppercase tracking-widest text-gray-500 mb-1.5">
                        {provenancePending ? 'Tags' : 'CivitAI tags'}
                    </h4>
                    <div className="flex flex-wrap gap-2">{otherTags.map((tag) => renderTag(tag, false))}</div>
                    <p className="text-2xs text-gray-500 mt-1.5">
                        {provenancePending
                            ? 'Checking which tags are yours…'
                            : 'Synced from CivitAI, which replaces them on every resync — so they cannot be deleted here.'}
                    </p>
                </div>
            )}

            {allTags.length === 0 && (
                <p className="text-xs text-gray-500">
                    No tags yet. Tags are searchable — a character, a pose, a style.
                </p>
            )}

            <form onSubmit={submitDraft} className="flex gap-2">
                <input
                    type="text"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder="Add a tag…"
                    aria-label="Add a tag"
                    maxLength={64}
                    className="flex-1 bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-emerald-500/50"
                />
                <button
                    type="submit"
                    disabled={!draft.trim() || addMutation.isPending}
                    className="px-3 py-1.5 bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded-lg text-sm font-medium hover:bg-emerald-500/30 transition-colors inline-flex items-center gap-1 disabled:opacity-40"
                >
                    <Plus size={14} />
                    {addMutation.isPending ? 'Adding…' : 'Add'}
                </button>
            </form>
        </div>
    );
}

export default function ModelDetailsModal({ file, providers = [], onClose }) {
    const [activeImageIndex, setActiveImageIndex] = useState(null);
    const [selectedVersionId, setSelectedVersionId] = useState(null);
    const [showSearchModal, setShowSearchModal] = useState(false);
    const [showAutopopulateSelector, setShowAutopopulateSelector] = useState(false);
    const [refreshing, setRefreshing] = useState(false);
    const queryClient = useQueryClient();
    // Above the `if (!file) return null` below: this modal returns early when it
    // has no file, and a hook below that line would be called conditionally.
    // It reads nothing from `file` — the id is passed per call — so hoisting it
    // changes nothing but the hook order.
    const autopopulate = useAutopopulateModel();
    const [localProviderStatuses, setLocalProviderStatuses] = useState(() => ({ ...(file?.provider_statuses || {}) }));
    const [syncingProviders, setSyncingProviders] = useState(new Set());

    const compatibleProviders = useMemo(() => {
        const isLlmFile = file?.path?.startsWith('models/llm') || file?.directory?.startsWith('llm');
        const active = (providers || []).filter(p => {
            if (!p.enabled) return false;
            const servesLlm = p.worker_type === 'llm' || p.worker_type === 'hybrid' || (Array.isArray(p.capabilities) && p.capabilities.includes('llm'));
            const servesImage = p.worker_type === 'image' || p.worker_type === 'hybrid' || !p.worker_type || (Array.isArray(p.capabilities) && p.capabilities.includes('image'));
            return isLlmFile ? servesLlm : servesImage;
        });
        const ids = new Set(active.map(p => p.id));
        const combined = [...active];
        if (file?.provider_statuses) {
            Object.keys(file.provider_statuses).forEach(pid => {
                if (!ids.has(pid)) {
                    combined.push({ id: pid, name: pid });
                }
            });
        }
        return combined;
    }, [providers, file]);

    const handleSyncToProvider = async (providerId) => {
        setSyncingProviders(prev => new Set(prev).add(providerId));
        try {
            await providersApi.downloadModels(providerId, {
                file_ids: file.file_id ? [file.file_id] : [],
                model_ids: file.model_id ? [file.model_id] : [],
            });
            toast.success(`Queued download on ${providerId}`);
            setLocalProviderStatuses(prev => ({
                ...prev,
                [providerId]: { status: 'downloading' }
            }));
            invalidateModelLists(queryClient);
        } catch (err) {
            toast.error(`Sync failed: ${err.message}`);
        } finally {
            setSyncingProviders(prev => {
                const next = new Set(prev);
                next.delete(providerId);
                return next;
            });
        }
    };
    
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
            // `useAutopopulateModel` owns the POST and both invalidations: the
            // model-list prefix, and `installedVersionsKey(civitaiId)` — which is
            // `['model','installed',<civitai id>]`, the only query in that
            // namespace and the one `ModelImportCard` reads. Both were written
            // out by hand here; the old `{ queryKey: ['model', file.model_id] }`
            // was two elements under a three-element key, and a *local* id where
            // the query is keyed by a civitai id, so it matched nothing on both
            // counts.
            await autopopulate.mutateAsync({ modelId: file.model_id, civitaiId });
            toast.success(isAutoDiscovered ? "Model details autopopulated!" : "Model metadata refetched!");
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
            queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.MODELS] });
            // A resync re-derives this model's versions, so the installed-versions
            // query for the civitai model it belongs to is the one that moved.
            if (civitaiId) {
                queryClient.invalidateQueries({ queryKey: installedVersionsKey(civitaiId) });
            }
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
                                        dangerouslySetInnerHTML={{ __html: sanitizeHtml(modelDescription) }}
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
                                        dangerouslySetInnerHTML={{ __html: sanitizeHtml(versionDescription) }}
                                    />
                                </div>
                            )}

                            {/* Provider Status */}
                            {compatibleProviders.length > 0 && (
                                <div className="mt-6 pt-4 border-t border-gray-800">
                                    <div className="flex items-center justify-between mb-3">
                                        <h3 className="text-sm font-medium text-gray-400">Provider Sync Status</h3>
                                        <span className="text-2xs text-gray-500 uppercase tracking-wider">
                                            {compatibleProviders.length} active provider(s)
                                        </span>
                                    </div>
                                    <div className="space-y-2">
                                        {compatibleProviders.map((provider) => {
                                            const providerId = provider.id;
                                            const statusData = localProviderStatuses[providerId];
                                            const isSyncing = syncingProviders.has(providerId);
                                            const rawStatus = typeof statusData === 'object' ? statusData.status : statusData;
                                            const status = isSyncing ? 'downloading' : (rawStatus || 'missing');

                                            const colorClass = {
                                                ready: 'text-green-400 bg-green-500/10 border-green-500/30',
                                                installed: 'text-green-400 bg-green-500/10 border-green-500/30',
                                                partial: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
                                                downloading: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20',
                                                pending: 'text-gray-400 bg-gray-500/10 border-gray-500/30',
                                                failed: 'text-red-400 bg-red-500/10 border-red-500/30',
                                                missing: 'text-gray-400 bg-gray-800/40 border-gray-700/50'
                                            }[status] || 'text-gray-400 bg-gray-800/40 border-gray-700/50';

                                            const isReady = status === 'ready' || status === 'installed';
                                            const isDownloading = status === 'downloading';

                                            return (
                                                <div key={providerId} className={`flex items-center justify-between p-2.5 rounded-xl border ${colorClass} transition-all`}>
                                                    <div className="flex items-center gap-2">
                                                        <span className="text-xs font-semibold text-gray-200">
                                                            {provider.name || providerId.replace('modal-', '')}
                                                        </span>
                                                        <span className="text-2xs font-mono uppercase px-1.5 py-0.2 rounded bg-black/40 text-gray-400">
                                                            {provider.type || 'worker'}
                                                        </span>
                                                    </div>

                                                    <div className="flex items-center gap-2">
                                                        {isDownloading ? (
                                                            <span className="inline-flex items-center gap-1 text-xs text-yellow-400 font-medium">
                                                                <Loader2 size={12} className="animate-spin" />
                                                                <span>Downloading...</span>
                                                            </span>
                                                        ) : isReady ? (
                                                            <span className="inline-flex items-center gap-1 text-xs text-green-400 font-medium">
                                                                <Check size={13} strokeWidth={3} />
                                                                <span>Ready</span>
                                                            </span>
                                                        ) : (
                                                            <button
                                                                type="button"
                                                                onClick={() => handleSyncToProvider(providerId)}
                                                                className="px-2.5 py-1 bg-blue-600/80 hover:bg-blue-500 text-white rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors shadow-sm active:scale-95"
                                                                title={`Sync this model to ${providerId}`}
                                                            >
                                                                <Download size={12} />
                                                                <span>Sync to Provider</span>
                                                            </button>
                                                        )}
                                                    </div>
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

                            {/* Tags. Read-only before this: every tag here came
                                from a CivitAI resync, and a resync deletes those
                                rows, so there was no way to record a tag the
                                user cared about. The editor owns provenance and
                                therefore owns the delete controls. */}
                            <div>
                                <h3 className="text-sm font-medium text-gray-400 mb-2">Tags</h3>
                                {file.model_id ? (
                                    <ModelTagEditor modelId={file.model_id} tags={tags} />
                                ) : (
                                    <p className="text-xs text-gray-500">
                                        This model has no database ID, so its tags cannot be edited.
                                    </p>
                                )}
                            </div>

                            {/* File Info */}
                            <div className="text-xs text-gray-500 pt-4 border-t border-gray-800 space-y-1">
                                <p>Filename: <span className="text-gray-400">{file.name}</span></p>
                                <p>Size: <span className="text-gray-400">{formatBytes(file.size)}</span></p>
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
