import { useState, useEffect, useMemo } from 'react';
import { Search, Filter, X, Loader2, RotateCw, Trash2, HardDrive, Globe, Wand2 } from 'lucide-react';
import ProgressiveImage from '../ProgressiveImage';
import { getOptimizedImageUrl } from '../../utils/imageOptimization';
import toast from 'react-hot-toast';
import { filesApi, api } from '../../api';
import { useInfiniteScroll } from '../../hooks/useInfiniteScroll';
import { useInfiniteQuery } from '@tanstack/react-query';
import useProvidersPageData from '../../hooks/useProvidersPageData';
import { MODEL_MANAGER_CATEGORIES } from '../../constants/modelDirectories';
import { getProviderDisplayName } from '../../utils/providerUtils';
import {
    availabilityTone,
    formatAvailabilityBadgeLabel,
    getModelAvailabilitySummary,
} from '../../utils/modelAvailability';
import ModelDetailsModal from './ModelDetailsModal';
import BatchAutopopulateModal from './BatchAutopopulateModal';
import BatchResyncModal from './BatchResyncModal';

const CATEGORIES = MODEL_MANAGER_CATEGORIES;
export default function InstalledTab({ openConfirm, itemsPerPage = 20 }) {
    const [category, setCategory] = useState(() => {
        return localStorage.getItem('modelManagerCategory') || "checkpoints";
    });

    useEffect(() => {
        localStorage.setItem('modelManagerCategory', category);
    }, [category]);

    const [selectedModel, setSelectedModel] = useState(null);
    const [showBatchModal, setShowBatchModal] = useState(false);
    const [showBatchResyncModal, setShowBatchResyncModal] = useState(false);
    const [searchTerm, setSearchTerm] = useState("");
    const [selectedTags, setSelectedTags] = useState([]);

    const [sortBy, setSortBy] = useState('name_asc');
    const [filterBaseModel, setFilterBaseModel] = useState('all');
    const [filterType, setFilterType] = useState('all');
    const [showNSFW, setShowNSFW] = useState(true);
    const [availableTags, setAvailableTags] = useState([]);
    const { providers, isLoading: providersLoading } = useProvidersPageData();

    const path = CATEGORIES.find(c => c.id === category)?.path;

    const {
        data,
        fetchNextPage,
        hasNextPage,
        isFetching,
        isFetchingNextPage,
        refetch,
    } = useInfiniteQuery({
        queryKey: ['installed-models', path, searchTerm, sortBy, filterBaseModel, filterType, showNSFW, selectedTags],
        queryFn: async ({ pageParam = 0 }) => {
            if (!path) return { files: [], total: 0 };
            const sortMap = { name: "name_asc", date: "date_desc", size: "size_desc", rating: "rating_desc" };
            const res = await filesApi.list({
                directory: path,
                limit: itemsPerPage,
                offset: pageParam,
                sort: sortMap[sortBy] || "name_asc",
                search: searchTerm,
                base_model: filterBaseModel !== 'all' ? filterBaseModel : undefined,
                model_type: filterType !== 'all' ? filterType : undefined,
                show_nsfw: showNSFW,
                tags: selectedTags.length > 0 ? selectedTags.join(",") : undefined,
            });
            return res;
        },
        getNextPageParam: (lastPage, allPages) => {
            const loaded = allPages.reduce((acc, page) => acc + (page.files?.length || 0), 0);
            return (lastPage.files?.length >= itemsPerPage && loaded < (lastPage.total || 0)) ? loaded : undefined;
        },
        enabled: !!path,
    });

    const filteredFiles = useMemo(() => {
        return data?.pages.flatMap(page => page.files || []) || [];
    }, [data]);

    const loading = isFetching && !isFetchingNextPage;
    const loadingMore = isFetchingNextPage;
    const hasMore = hasNextPage;

    useEffect(() => {
        // Collect tags from all fetched models so far
        const tags = new Set(availableTags);
        filteredFiles.forEach(f => {
            if (f.tags) f.tags.forEach(t => tags.add(t));
        });
        const tagsArr = Array.from(tags).sort();
        if (tagsArr.length > availableTags.length) {
            setAvailableTags(tagsArr);
        }
    }, [filteredFiles, availableTags]);

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

    const handleRefresh = () => {
        refetch();
    };

    const sentinelRef = useInfiniteScroll({
        hasMore: hasMore && !loading,
        onLoadMore: () => fetchNextPage(),
        loading: loadingMore,
        rootMargin: '400px'
    });

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
            refetch();
        } catch (e) {
            console.error("Delete failed:", e);
            toast.error("Error deleting model");
        }
    };

    return (
        <div className="space-y-4 md:space-y-6">
            <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-hide">
                {CATEGORIES.map(cat => (
                    <button
                        key={cat.id}
                        onClick={() => setCategory(cat.id)}
                        className={`px-5 py-2.5 rounded-full text-[11px] font-bold uppercase tracking-widest whitespace-nowrap transition-all duration-300 shadow-lg ${category === cat.id ? 'bg-blue-600/20 text-blue-400 border border-blue-500 shadow-[0_0_15px_rgba(59,130,246,0.3)]' : 'bg-[#0B0E14]/80 text-gray-400 border border-white/5 hover:bg-black/40 hover:text-white hover:border-white/10'
                            }`}
                    >
                        {cat.label}
                    </button>
                ))}
            </div>

            {/* Sort and Filter Controls */}
            <div className="flex gap-3 flex-wrap">
                <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value)}
                    className="bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 py-2 text-xs font-medium text-white focus:outline-none focus:ring-2 focus:ring-blue-500/50 shadow-inner glow-focus"
                >
                    <option value="name">Sort: Name</option>
                    <option value="date">Sort: Date</option>
                    <option value="size">Sort: Size</option>
                    <option value="rating">Sort: Rating</option>
                </select>

                <select
                    value={filterBaseModel}
                    onChange={(e) => setFilterBaseModel(e.target.value)}
                    className="bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 py-2 text-xs font-medium text-white focus:outline-none focus:ring-2 focus:ring-blue-500/50 shadow-inner glow-focus"
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
                    className="bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 py-2 text-xs font-medium text-white focus:outline-none focus:ring-2 focus:ring-blue-500/50 shadow-inner glow-focus"
                >
                    <option value="all">All Types</option>
                    <option value="Checkpoint">Checkpoint</option>
                    <option value="LORA">LoRA</option>
                    <option value="TextualInversion">Embedding</option>
                </select>

                <label className="flex items-center gap-2.5 bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 py-2 text-[11px] font-bold text-gray-400 uppercase tracking-widest cursor-pointer hover:border-white/20 transition-colors shadow-inner">
                    <input
                        type="checkbox"
                        checked={showNSFW}
                        onChange={(e) => setShowNSFW(e.target.checked)}
                        className="rounded w-3.5 h-3.5 bg-black/40 border-gray-600 text-blue-500 focus:ring-blue-500"
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
                        className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-2 text-[11px] font-bold text-red-400 uppercase tracking-widest hover:bg-red-500/20 hover:border-red-500/30 transition-colors shadow-inner"
                    >
                        Clear Filters
                    </button>
                )}
            </div>

            {/* Search and Filter Bar */}
            <div className="mb-6 space-y-4">
                <div className="flex flex-wrap gap-4">
                    <div className="relative flex-1">
                        <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500" size={20} />
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
                            className="w-full bg-[#0B0E14]/80 border border-white/10 rounded-xl pl-12 pr-4 py-3 text-white focus:ring-2 focus:ring-blue-500/50 outline-none shadow-inner glow-focus placeholder-gray-600 font-medium"
                        />
                    </div>

                    <button
                        onClick={handleRefresh}
                        className="p-3 bg-[#0B0E14]/80 border border-white/10 rounded-xl text-gray-400 hover:text-white hover:border-white/20 transition-all shadow-inner hover:shadow-[0_0_10px_rgba(255,255,255,0.1)]"
                        title="Refresh List"
                        aria-label="Refresh List"
                    >
                        <RotateCw size={20} />
                    </button>

                    <button
                        onClick={() => setShowBatchModal(true)}
                        className="p-3 bg-[#0B0E14]/80 hover:bg-black/40 rounded-xl border border-white/10 transition-all shadow-inner hover:shadow-[0_0_10px_rgba(255,255,255,0.1)]"
                        title="Batch Autopopulate Models"
                        aria-label="Batch Autopopulate Models"
                    >
                        <Wand2 size={20} className="text-purple-400 drop-shadow-md" />
                    </button>

                    <button
                        onClick={() => setShowBatchResyncModal(true)}
                        className="p-3 bg-[#0B0E14]/80 hover:bg-black/40 rounded-xl border border-white/10 transition-all shadow-inner hover:shadow-[0_0_10px_rgba(255,255,255,0.1)]"
                        title="Resync All Metadata"
                        aria-label="Resync All Metadata"
                    >
                        <RotateCw size={20} className="text-blue-400 hover:text-blue-300 drop-shadow-md" />
                    </button>

                    <button
                        onClick={async () => {
                            try {
                                const res = await api.post('/api/v2/models/maintenance/cleanup-orphans');
                                toast.success(`Cleanup complete! Removed ${res.removed_models} orphaned models.`);
                            } catch (err) {
                                toast.error('Failed to cleanup orphans: ' + err.message);
                            }
                        }}
                        className="p-3 bg-[#0B0E14]/80 hover:bg-black/40 rounded-xl border border-white/10 transition-all shadow-inner hover:shadow-[0_0_10px_rgba(255,255,255,0.1)]"
                        title="Cleanup Orphaned Models"
                        aria-label="Cleanup Orphaned Models"
                    >
                        <Trash2 size={20} className="text-red-400 hover:text-red-300 drop-shadow-md" />
                    </button>

                    {availableTags.length > 0 && (
                        <div className="relative group">
                            <button className="flex items-center gap-2 px-5 py-3 bg-[#0B0E14]/80 border border-white/10 rounded-xl text-gray-300 hover:text-white hover:border-white/20 shadow-inner transition-all">
                                <Filter size={20} />
                                <span className="font-bold text-[11px] uppercase tracking-widest">Tags ({selectedTags.length})</span>
                            </button>
                            <div className="absolute right-0 mt-2 w-64 max-h-96 overflow-y-auto glass-panel border border-white/10 rounded-2xl shadow-2xl p-3 hidden group-hover:block z-20 backdrop-blur-xl">
                                {availableTags.map(tag => (
                                    <label key={tag} className="flex items-center gap-3 p-2 hover:bg-white/5 rounded-xl cursor-pointer transition-colors">
                                        <input
                                            type="checkbox"
                                            checked={selectedTags.includes(tag)}
                                            onChange={(e) => {
                                                if (e.target.checked) setSelectedTags([...selectedTags, tag]);
                                                else setSelectedTags(selectedTags.filter(t => t !== tag));
                                            }}
                                            className="rounded border-white/10 bg-black/40 text-blue-500 focus:ring-blue-500/50"
                                        />
                                        <span className="text-sm font-medium text-gray-300">{tag}</span>
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
                            <span key={tag} className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-500/20 text-blue-300 rounded-full text-xs font-bold border border-blue-500/30 shadow-inner">
                                {tag}
                                <button onClick={() => setSelectedTags(selectedTags.filter(t => t !== tag))} className="hover:text-white transition-colors" aria-label={`Remove tag ${tag}`}>
                                    <X size={14} />
                                </button>
                            </span>
                        ))}
                        <button onClick={() => setSelectedTags([])} className="text-xs font-bold text-gray-500 hover:text-gray-300 uppercase tracking-widest transition-colors" aria-label="Clear all tags">
                            Clear all
                        </button>
                    </div>
                )}
            </div>

            {loading && filteredFiles.length === 0 ? (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6">
                    {Array.from({ length: 10 }).map((_, i) => (
                        <div key={i} className="aspect-[2/3] bg-white/5 rounded-2xl animate-pulse shadow-inner" />
                    ))}
                </div>
            ) : filteredFiles.length === 0 ? (
                <div className="text-center py-20 text-gray-500 glass-panel rounded-3xl border border-white/5">
                    <HardDrive className="mx-auto mb-4 opacity-50 text-blue-400 drop-shadow-[0_0_10px_rgba(59,130,246,0.4)]" size={64} />
                    <p className="text-xl font-bold tracking-wide text-gray-300">No models found</p>
                    <p className="text-sm opacity-70 mt-2">Try adjusting your search or filters</p>
                </div>
            ) : (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6">
                    {filteredFiles.map(file => {
                        const availability = getModelAvailabilitySummary(
                            file.provider_statuses,
                            providers,
                            { providersLoading }
                        );
                        const showAvailabilityBadge = availability.hasStatusData;
                        const availabilityLabel = formatAvailabilityBadgeLabel(availability.label);
                        const proxyPreviewUrl = file.civitai_id ? `/api/v2/models/preview/${file.civitai_id}?image_index=0` : null;
                        const previewImage = proxyPreviewUrl || file.preview;

                        return (
                            <div
                                key={file.name}
                                onClick={() => setSelectedModel(file)}
                                className="group relative bg-[#0B0E14]/80 rounded-2xl overflow-hidden border border-white/5 hover:border-blue-500/50 hover:shadow-[0_0_20px_rgba(59,130,246,0.2)] transition-all duration-300 aspect-[2/3] cursor-pointer"
                            >
                                <div className="absolute inset-0">
                                    {previewImage ? (
                                        <ProgressiveImage
                                            src={previewImage}
                                            medium={getOptimizedImageUrl(previewImage, 450)}
                                            alt={file.display_name || file.name}
                                            className="w-full h-full object-cover transition-transform duration-700 group-hover:scale-110"
                                            size="medium"
                                            aspectRatio="2/3"
                                            onError={(e) => { e.target.style.display = 'none'; }}
                                        />
                                    ) : (
                                        <div className="w-full h-full bg-gradient-to-br from-black/60 to-black/20 flex items-center justify-center text-gray-600/50">
                                            <Globe size={48} />
                                        </div>
                                    )}
                                    <div className="absolute inset-0 bg-gradient-to-t from-[#0B0E14] via-[#0B0E14]/60 to-transparent opacity-90 transition-opacity duration-300 group-hover:opacity-75" />
                                </div>

                                <div className="absolute bottom-0 left-0 right-0 p-4">
                                    <h3 className="text-sm font-bold text-white line-clamp-2 mb-2 drop-shadow-md tracking-wide" title={file.display_name || file.name}>
                                        {file.display_name || file.name}
                                    </h3>
                                    {file.description?.includes("Auto-discovered") && (
                                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-yellow-900/40 text-yellow-400 border border-yellow-700/50 mb-1">
                                            Auto-discovered
                                        </span>
                                    )}
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

            {showBatchModal && (
                <BatchAutopopulateModal onClose={() => {
                    setShowBatchModal(false);
                    handleRefresh();
                }} />
            )}

            {showBatchResyncModal && (
                <BatchResyncModal onClose={() => setShowBatchResyncModal(false)} />
            )}
        </div>
    );
}
