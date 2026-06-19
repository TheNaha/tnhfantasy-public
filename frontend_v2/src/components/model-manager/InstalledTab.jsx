import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Search, Filter, X, Loader2, RotateCw, Trash2, HardDrive, Globe } from 'lucide-react';
import toast from 'react-hot-toast';
import { filesApi, api } from '../../api';
import { useInfiniteScroll } from '../../hooks/useInfiniteScroll';
import useProvidersPageData from '../../hooks/useProvidersPageData';
import { MODEL_MANAGER_CATEGORIES } from '../../constants/modelDirectories';
import { getProviderDisplayName } from '../../utils/providerUtils';
import {
    availabilityTone,
    formatAvailabilityBadgeLabel,
    getModelAvailabilitySummary,
} from '../../utils/modelAvailability';
import ModelDetailsModal from './ModelDetailsModal';

const CATEGORIES = MODEL_MANAGER_CATEGORIES;

export default function InstalledTab({ openConfirm, itemsPerPage = 20 }) {
    const [category, setCategory] = useState("checkpoints");
    const [files, setFiles] = useState([]);
    const [loading, setLoading] = useState(false);
    const [loadingMore, setLoadingMore] = useState(false);
    const [selectedModel, setSelectedModel] = useState(null);
    const [searchTerm, setSearchTerm] = useState("");
    const [selectedTags, setSelectedTags] = useState([]);

    const [sortBy, setSortBy] = useState('name_asc');
    const [filterBaseModel, setFilterBaseModel] = useState('all');
    const [filterType, setFilterType] = useState('all');
    const [showNSFW, setShowNSFW] = useState(true);
    const [availableTags, setAvailableTags] = useState([]);
    const [, setOffset] = useState(0);
    const [hasMore, setHasMore] = useState(true);
    const offsetRef = useRef(0);
    const { providers, isLoading: providersLoading } = useProvidersPageData();

    const fetchFiles = useCallback(async (reset = false, search = "") => {
        if (reset) {
            setLoading(true);
            setOffset(0);
            offsetRef.current = 0;
            setFiles([]);
            setHasMore(true);
            setAvailableTags([]);
        } else {
            setLoadingMore(true);
        }

        try {
            const path = CATEGORIES.find(c => c.id === category)?.path;
            if (!path) return;

            const currentOffset = reset ? 0 : offsetRef.current;
            const params = {
                directory: path,
                limit: itemsPerPage,
                offset: currentOffset,
                sort: sortBy  // Use the sortBy state
            };
            if (search) params.search = search;

            const data = await filesApi.list(params);
            const newFiles = data.files || [];

            if (reset) {
                setFiles(newFiles);
                setOffset(itemsPerPage);
                offsetRef.current = itemsPerPage;
            } else {
                setFiles(prev => {
                    const existingNames = new Set(prev.map(f => f.name));
                    const uniqueNewFiles = newFiles.filter(f => !existingNames.has(f.name));
                    return [...prev, ...uniqueNewFiles];
                });
                offsetRef.current += itemsPerPage;
                setOffset(offsetRef.current);
            }

            // Only has more if we received a full page AND there's a total indicating more
            const total = data.total || 0;
            const loadedSoFar = currentOffset + newFiles.length;
            setHasMore(newFiles.length >= itemsPerPage && loadedSoFar < total);

            setAvailableTags(prev => {
                const tags = new Set(prev);
                newFiles.forEach(f => {
                    if (f.tags) {
                        f.tags.forEach(t => tags.add(t));
                    }
                });
                return Array.from(tags).sort();
            });
        } catch (e) {
            console.error("Failed to fetch files", e);
            toast.error("Failed to load installed models");
        } finally {
            setLoading(false);
            setLoadingMore(false);
        }
    }, [category, itemsPerPage, sortBy]);

    const handleCheckDependencies = async (file) => {
        if (!file.model_id) return;
        
        try {
            toast.promise(
                api.post(`/api/v2/models/${file.model_id}/check-dependencies`),
                {
                    loading: 'Checking dependencies...',
                    success: 'Dependencies triggered! Check provider status.',
                    error: 'Failed to check dependencies'
                }
            );
        } catch (error) {
            console.error(error);
        }
    };

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchFiles(true, searchTerm);
        }, 500);
        return () => clearTimeout(timer);
    }, [searchTerm, category, sortBy, fetchFiles]);  // Added sortBy

    const handleRefresh = () => {
        fetchFiles(true, searchTerm);
    };

    const sentinelRef = useInfiniteScroll({
        hasMore: hasMore && !loading,
        onLoadMore: () => fetchFiles(false),
        loading: loadingMore,
        rootMargin: '400px'
    });

    const filteredFiles = useMemo(() => {
        let result = files.filter(file => {
            // ⚡ Bolt: Combined filters into a single pass to prevent O(N * 4) iteration overhead
            const matchesTags = selectedTags.length === 0 ||
                selectedTags.every(tag => file.tags?.includes(tag));

            const matchesBaseModel = filterBaseModel === 'all' || file.base_model === filterBaseModel;
            const matchesType = filterType === 'all' || file.type === filterType;
            const matchesNSFW = showNSFW || !file.nsfw;

            return matchesTags && matchesBaseModel && matchesType && matchesNSFW;
        });

        result.sort((a, b) => {
            switch (sortBy) {
                case 'name':
                    return (a.name || '').localeCompare(b.name || '');
                case 'date':
                    return (b.modified_time || 0) - (a.modified_time || 0);
                case 'size':
                    return (b.size || 0) - (a.size || 0);
                case 'rating':
                    return (b.stats?.thumbsUp || 0) - (a.stats?.thumbsUp || 0);
                default:
                    return 0;
            }
        });

        return result;
    }, [files, selectedTags, sortBy, filterBaseModel, filterType, showNSFW]);

    const handleDelete = async (file) => {
        const displayName = file.display_name || file.name;
        const modelId = file.model_id;

        const accepted = await openConfirm({
            title: "Delete Model",
            message: `Are you sure you want to delete ${displayName}? This will also remove it from all providers.`,
            isDangerous: true,
            confirmText: "Delete",
        });
        if (!accepted) return;
        try {
            if (modelId) {
                // Use V2 API with proper provider sync
                const { modelsApi } = await import('../../api');
                await modelsApi.deleteV2(modelId);
                toast.success(`Deleted ${displayName} and synced providers`);
            } else {
                // Fallback to legacy file deletion
                await filesApi.deleteMultiple([file.name]);
                toast.success("Deleted " + displayName);
            }
            fetchFiles(true);
        } catch (e) {
            console.error("Delete failed:", e);
            toast.error("Error deleting model");
        }
    };

    return (
        <div className="space-y-6">
            <div className="flex gap-2 overflow-x-auto pb-2">
                {CATEGORIES.map(cat => (
                    <button
                        key={cat.id}
                        onClick={() => setCategory(cat.id)}
                        className={`px-4 py-2 rounded-full text-sm font-medium whitespace-nowrap transition-colors ${category === cat.id ? 'bg-gray-700 text-white border border-gray-600' : 'bg-gray-900 text-gray-400 border border-gray-800 hover:border-gray-700'
                            }`}
                    >
                        {cat.label}
                    </button>
                ))}
            </div>

            {/* Sort and Filter Controls */}
            <div className="flex gap-2 flex-wrap">
                <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value)}
                    className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                >
                    <option value="name">Sort: Name</option>
                    <option value="date">Sort: Date</option>
                    <option value="size">Sort: Size</option>
                    <option value="rating">Sort: Rating</option>
                </select>

                <select
                    value={filterBaseModel}
                    onChange={(e) => setFilterBaseModel(e.target.value)}
                    className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                >
                    <option value="all">All Base Models</option>
                    <option value="SD 1.5">SD 1.5</option>
                    <option value="SDXL 1.0">SDXL</option>
                    <option value="SD 3">SD 3</option>
                    <option value="Pony">Pony</option>
                    <option value="Flux.1 D">Flux Dev</option>
                    <option value="Flux.1 S">Flux Schnell</option>
                </select>

                <select
                    value={filterType}
                    onChange={(e) => setFilterType(e.target.value)}
                    className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                >
                    <option value="all">All Types</option>
                    <option value="Checkpoint">Checkpoint</option>
                    <option value="LORA">LoRA</option>
                    <option value="TextualInversion">Embedding</option>
                </select>

                <label className="flex items-center gap-2 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white cursor-pointer hover:border-blue-500">
                    <input
                        type="checkbox"
                        checked={showNSFW}
                        onChange={(e) => setShowNSFW(e.target.checked)}
                        className="rounded w-3 h-3"
                    />
                    Show NSFW
                </label>

                {(filterBaseModel !== 'all' || filterType !== 'all' || !showNSFW) && (
                    <button
                        onClick={() => {
                            setFilterBaseModel('all');
                            setFilterType('all');
                            setShowNSFW(true);
                        }}
                        className="bg-red-900/30 border border-red-800 rounded-lg px-3 py-1.5 text-xs text-red-300 hover:bg-red-900/50"
                    >
                        Clear Filters
                    </button>
                )}
            </div>

            {/* Search and Filter Bar */}
            <div className="mb-6 space-y-4">
                <div className="flex flex-wrap gap-4">
                    <div className="relative flex-1">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={20} />
                        <input
                            type="text"
                            placeholder="Search models..."
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    e.preventDefault();
                                }
                            }}
                            enterKeyHint="search"
                            className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-10 pr-4 py-2 text-white focus:ring-2 focus:ring-blue-500 outline-none"
                        />
                    </div>

                    <button
                        onClick={handleRefresh}
                        className="p-2 bg-gray-900 border border-gray-700 rounded-lg text-gray-300 hover:text-white hover:border-gray-500 transition-colors"
                        title="Refresh List"
                        aria-label="Refresh List"
                    >
                        <RotateCw size={20} />
                    </button>

                    {availableTags.length > 0 && (
                        <div className="relative group">
                            <button className="flex items-center gap-2 px-4 py-2 bg-gray-900 border border-gray-700 rounded-lg text-gray-300 hover:text-white hover:border-gray-500">
                                <Filter size={20} />
                                <span>Tags ({selectedTags.length})</span>
                            </button>
                            <div className="absolute right-0 mt-2 w-64 max-h-96 overflow-y-auto bg-gray-900 border border-gray-700 rounded-xl shadow-xl p-2 hidden group-hover:block z-20">
                                {availableTags.map(tag => (
                                    <label key={tag} className="flex items-center gap-2 p-2 hover:bg-gray-800 rounded cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={selectedTags.includes(tag)}
                                            onChange={(e) => {
                                                if (e.target.checked) setSelectedTags([...selectedTags, tag]);
                                                else setSelectedTags(selectedTags.filter(t => t !== tag));
                                            }}
                                            className="rounded border-gray-700 bg-gray-800 text-blue-500"
                                        />
                                        <span className="text-sm text-gray-300">{tag}</span>
                                    </label>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                {/* Selected Tags Pills */}
                {selectedTags.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                        {selectedTags.map(tag => (
                            <span key={tag} className="flex items-center gap-1 px-2 py-1 bg-blue-500/20 text-blue-300 rounded-full text-xs border border-blue-500/30">
                                {tag}
                                <button onClick={() => setSelectedTags(selectedTags.filter(t => t !== tag))} className="hover:text-white" aria-label={`Remove tag ${tag}`}>
                                    <X size={12} />
                                </button>
                            </span>
                        ))}
                        <button onClick={() => setSelectedTags([])} className="text-xs text-gray-500 hover:text-gray-300 underline" aria-label="Clear all tags">
                            Clear all
                        </button>
                    </div>
                )}
            </div>

            {loading && filteredFiles.length === 0 ? (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                    {Array.from({ length: 10 }).map((_, i) => (
                        <div key={i} className="aspect-[2/3] bg-gray-800 rounded-xl animate-pulse" />
                    ))}
                </div>
            ) : filteredFiles.length === 0 ? (
                <div className="text-center py-20 text-gray-500">
                    <HardDrive className="mx-auto mb-4 opacity-50" size={48} />
                    <p className="text-lg">No models found</p>
                    <p className="text-sm opacity-70">Try adjusting your search or filters</p>
                </div>
            ) : (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                    {filteredFiles.map(file => {
                        const availability = getModelAvailabilitySummary(
                            file.provider_statuses,
                            providers,
                            { providersLoading }
                        );
                        const showAvailabilityBadge = availability.hasStatusData;
                        const availabilityLabel = formatAvailabilityBadgeLabel(availability.label);

                        return (
                            <div
                                key={file.name}
                                onClick={() => setSelectedModel(file)}
                                className="group relative bg-gray-900 rounded-xl overflow-hidden border border-gray-800 hover:border-gray-600 transition-all aspect-[2/3] cursor-pointer"
                            >
                                <div className="absolute inset-0">
                                    {file.preview ? (
                                        <img
                                            src={file.preview}
                                            alt={file.display_name || file.name}
                                            className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
                                            loading="lazy"
                                            decoding="async"
                                            fetchPriority="low"
                                            onError={(e) => {
                                                if (file.civitai_id) {
                                                    const proxyPreview = `/api/v2/models/preview/${file.civitai_id}?image_index=0`;
                                                    if (e.currentTarget.src !== proxyPreview) {
                                                        e.currentTarget.src = proxyPreview;
                                                        return;
                                                    }
                                                }
                                                e.target.style.display = 'none';
                                            }}
                                        />
                                    ) : file.civitai_id ? (
                                        <img
                                            src={`/api/v2/models/preview/${file.civitai_id}?image_index=0`}
                                            alt={file.display_name || file.name}
                                            className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
                                            loading="lazy"
                                            decoding="async"
                                            fetchPriority="low"
                                            onError={(e) => { e.target.style.display = 'none'; }}
                                        />
                                    ) : (
                                        <div className="w-full h-full bg-gray-800 flex items-center justify-center text-gray-600">
                                            <Globe size={32} />
                                        </div>
                                    )}
                                    <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-transparent opacity-80" />
                                </div>

                                <div className="absolute bottom-0 left-0 right-0 p-3">
                                    <h3 className="text-sm font-medium text-white line-clamp-2 mb-1" title={file.display_name || file.name}>
                                        {file.display_name || file.name}
                                    </h3>
                                    <div className="flex items-center justify-between text-xs text-gray-400 gap-2">
                                        <div className="flex items-center gap-2 min-w-0">
                                            <span>{(file.size / 1024 / 1024).toFixed(0)} MB</span>
                                            {showAvailabilityBadge && (
                                                <span
                                                    className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${availabilityTone(availability.label)}`}
                                                    title={availability.detail || availability.label}
                                                >
                                                    {availabilityLabel}
                                                </span>
                                            )}
                                        </div>
                                        <div className="flex items-center gap-1">
                                            {/* Dependency Check Button for DB-tracked models */}
                                            {file.model_id && (
                                                <button
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleCheckDependencies(file);
                                                    }}
                                                    className="p-1.5 hover:bg-blue-500/20 hover:text-blue-400 rounded-full transition-colors"
                                                    title="Check & Download Dependencies (CLIP/VAE)"
                                                    aria-label="Check & Download Dependencies"
                                                >
                                                    <RotateCw size={14} />
                                                </button>
                                            )}
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleDelete(file);
                                                }}
                                                className="p-1.5 hover:bg-red-500/20 hover:text-red-400 rounded-full transition-colors"
                                                title="Delete"
                                                aria-label={`Delete ${file.display_name || file.name}`}
                                            >
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                    </div>

                                    {/* Provider sync status initials */}
                                    {file.provider_statuses && Object.keys(file.provider_statuses).length > 0 && (
                                        <div className="mt-1 flex gap-1">
                                            {Object.entries(file.provider_statuses).map(([providerId, status]) => {
                                                const providerShort = getProviderDisplayName(providerId);
                                                const initial = providerShort.charAt(0).toUpperCase();
                                                const statusValue = typeof status === 'object' ? status.status : status;
                                                const colorClass = {
                                                    installed: 'text-green-400',
                                                    ready: 'text-green-400',
                                                    downloading: 'text-yellow-400',
                                                    pending: 'text-gray-400',
                                                    failed: 'text-red-400'
                                                }[statusValue] || 'text-gray-400';
                                                return (
                                                    <span
                                                        key={providerId}
                                                        title={`${providerShort}: ${statusValue}`}
                                                        className={`text-xs font-bold ${colorClass}`}
                                                    >
                                                        {initial}
                                                    </span>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            <div ref={sentinelRef} className="h-4" />

            {loadingMore && (
                <div className="flex justify-center py-8">
                    <Loader2 className="animate-spin text-gray-400" size={32} />
                </div>
            )}

            {selectedModel && (
                <ModelDetailsModal
                    file={selectedModel}
                    onClose={() => setSelectedModel(null)}
                />
            )}
        </div>
    );
}
