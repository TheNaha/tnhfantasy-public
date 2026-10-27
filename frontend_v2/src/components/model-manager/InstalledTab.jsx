import { useState, useEffect, useMemo, useCallback, memo } from 'react';
import { Search, Loader2, RotateCw, Trash2, HardDrive, Globe, Wand2, Check, CheckSquare, Download, X } from 'lucide-react';
import ProgressiveImage from '../ProgressiveImage';
import { modelListKey } from '../../constants/queryKeys';
import { getOptimizedImageUrl } from '../../utils/imageOptimization';
import { formatBytes } from '../../utils/bytes';
import { nextOffsetPageParam } from '../../utils/pagination';
import toast from 'react-hot-toast';
import { filesApi, api, modelsApi, providersApi } from '../../api';
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
import ModelTagFilter from '../selector/ModelTagFilter';
import ModelDetailsModal from './ModelDetailsModal';
import BatchAutopopulateModal from './BatchAutopopulateModal';
import BatchResyncModal from './BatchResyncModal';
import { QueryErrorState } from '../common/QueryState';

const CATEGORIES = MODEL_MANAGER_CATEGORIES;

/**
 * One row of the installed-model grid.
 */
const InstalledModelRow = memo(function InstalledModelRow({
    file,
    providers,
    providersLoading,
    onSelect,
    onCheckDependencies,
    onDelete,
    isSelectMode,
    isSelected,
    onToggleSelect,
}) {
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
            onClick={() => {
                if (isSelectMode) {
                    onToggleSelect(file);
                } else {
                    onSelect(file);
                }
            }}
            className={`group relative bg-[#0B0E14]/80 rounded-2xl overflow-hidden border transition-all duration-300 aspect-[2/3] cursor-pointer ${
                isSelected
                    ? 'border-blue-500 shadow-[0_0_20px_rgba(59,130,246,0.35)] ring-1 ring-blue-500'
                    : 'border-white/5 hover:border-blue-500/50 hover:shadow-[0_0_20px_rgba(59,130,246,0.2)]'
            }`}
        >
            {/* Selection Checkbox */}
            <div
                className={`absolute top-3 left-3 z-20 transition-all duration-200 ${
                    isSelected || isSelectMode ? 'opacity-100 scale-100' : 'opacity-0 scale-95 group-hover:opacity-100 group-hover:scale-100'
                }`}
                onClick={(e) => {
                    e.stopPropagation();
                    onToggleSelect(file);
                }}
            >
                <div
                    className={`w-6 h-6 rounded-lg flex items-center justify-center border shadow-lg backdrop-blur-md transition-all ${
                        isSelected
                            ? 'bg-blue-600 border-blue-400 text-white'
                            : 'bg-black/60 border-white/20 text-transparent hover:border-white/40'
                    }`}
                >
                    <Check size={13} strokeWidth={3} className={isSelected ? 'block text-white' : 'hidden'} />
                </div>
            </div>

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
                <h3 className="text-sm font-bold text-white line-clamp-2 break-words hyphens-auto mb-2 drop-shadow-md tracking-wide" title={file.display_name || file.name}>
                    {file.display_name || file.name}
                </h3>
                {file.description?.includes("Auto-discovered") && (
                    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-yellow-900/40 text-yellow-400 border border-yellow-700/50 mb-1">
                        Auto-discovered
                    </span>
                )}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between text-xs text-gray-400 gap-2">
                    <div className="flex flex-wrap items-center gap-1.5 flex-1 min-w-0">
                        <span className="shrink-0">{formatBytes(file.size)}</span>
                        {showAvailabilityBadge && (
                            <span
                                className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-xs sm:text-2xs font-medium shrink-0 max-w-full truncate ${availabilityTone(availability.label)}`}
                                title={availability.detail || availability.label}
                            >
                                {availabilityLabel}
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-1 shrink-0 self-end sm:self-auto">
                        {/* Dependency Check Button for DB-tracked models */}
                        {file.model_id && (
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onCheckDependencies(file);
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
                                onDelete(file);
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
                                partial: 'text-amber-400',
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
});

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
    const [filterAvailability, setFilterAvailability] = useState('all');
    const [showNSFW, setShowNSFW] = useState(true);
    const [availableTags, setAvailableTags] = useState([]);
    const { providers, isLoading: providersLoading } = useProvidersPageData();

    // Multi-Selection State
    const [isSelectMode, setIsSelectMode] = useState(false);
    const [selectedFiles, setSelectedFiles] = useState([]);
    const [showBatchSyncModal, setShowBatchSyncModal] = useState(false);

    const path = CATEGORIES.find(c => c.id === category)?.path;

    const {
        data,
        fetchNextPage,
        hasNextPage,
        isFetching,
        isFetchingNextPage,
        isError,
        error,
        refetch,
    } = useInfiniteQuery({
        queryKey: modelListKey({
            directory: path,
            search: searchTerm,
            sortBy,
            baseModel: filterBaseModel,
            modelType: filterType,
            showNSFW,
            selectedTags,
            pageSize: itemsPerPage,
        }),
        queryFn: async ({ pageParam = 0, signal }) => {
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
            }, { signal });
            return res;
        },
        getNextPageParam: nextOffsetPageParam,
        enabled: !!path,
    });

    const rawFilteredFiles = useMemo(() => {
        return data?.pages.flatMap(page => page.files || []) || [];
    }, [data]);

    // Apply availability filter if set
    const filteredFiles = useMemo(() => {
        if (filterAvailability === 'all') return rawFilteredFiles;
        return rawFilteredFiles.filter(file => {
            const statuses = Object.values(file.provider_statuses || {});
            if (filterAvailability === 'ready') {
                return statuses.some(s => (typeof s === 'object' ? s.status : s) === 'ready' || (typeof s === 'object' ? s.status : s) === 'installed');
            }
            if (filterAvailability === 'missing') {
                return statuses.some(s => (typeof s === 'object' ? s.status : s) === 'missing' || (typeof s === 'object' ? s.status : s) === 'failed') || statuses.length === 0;
            }
            return true;
        });
    }, [rawFilteredFiles, filterAvailability]);

    // Aggregate storage metrics
    const totalStorageBytes = useMemo(() => {
        return filteredFiles.reduce((acc, f) => acc + (f.size || 0), 0);
    }, [filteredFiles]);

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

    const handleCheckDependencies = useCallback(async (file) => {
        if (!file.model_id) return;

        try {
            toast.promise(
                api.post(`/api/v2/models/maintenance/${file.model_id}/check-dependencies`),
                {
                    loading: 'Checking dependencies...',
                    success: 'Dependencies triggered! Check provider status.',
                    error: 'Failed to check dependencies'
                }
            );
        } catch {
            toast.error('Failed to check dependencies');
        }
    }, []);

    const handleRefresh = () => {
        refetch();
    };

    const sentinelRef = useInfiniteScroll({
        hasMore: hasMore && !loading,
        onLoadMore: () => fetchNextPage(),
        loading: loadingMore,
        rootMargin: '400px'
    });

    const handleDelete = useCallback(async (file) => {
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
                await modelsApi.deleteV2(modelId);
                toast.success(`Deleted ${displayName} and synced providers`);
            } else {
                await filesApi.deleteMultiple([file.name]);
                toast.success("Deleted " + displayName);
            }
            refetch();
        } catch {
            toast.error("Error deleting model");
        }
    }, [openConfirm, refetch]);

    // Multi-Selection Handlers
    const handleToggleSelect = useCallback((file) => {
        setSelectedFiles(prev => {
            const exists = prev.some(f => f.name === file.name);
            if (exists) {
                return prev.filter(f => f.name !== file.name);
            } else {
                return [...prev, file];
            }
        });
    }, []);

    const handleSelectAll = useCallback(() => {
        if (selectedFiles.length === filteredFiles.length) {
            setSelectedFiles([]);
        } else {
            setSelectedFiles([...filteredFiles]);
        }
    }, [selectedFiles.length, filteredFiles]);

    const handleBatchDelete = useCallback(async () => {
        if (selectedFiles.length === 0) return;
        const accepted = await openConfirm({
            title: "Batch Delete Models",
            message: `Are you sure you want to delete ${selectedFiles.length} selected model(s)? This will also remove them from all providers.`,
            isDangerous: true,
            confirmText: `Delete ${selectedFiles.length} Models`,
        });
        if (!accepted) return;

        try {
            for (const file of selectedFiles) {
                if (file.model_id) {
                    await modelsApi.deleteV2(file.model_id);
                } else {
                    await filesApi.deleteMultiple([file.name]);
                }
            }
            toast.success(`Deleted ${selectedFiles.length} models`);
            setSelectedFiles([]);
            refetch();
        } catch {
            toast.error("Error during batch delete");
        }
    }, [openConfirm, refetch, selectedFiles]);

    const handleBatchSyncSubmit = async (providerId) => {
        if (selectedFiles.length === 0 || !providerId) return;
        try {
            const fileIds = selectedFiles.map(f => f.file_id).filter(Boolean);
            const modelIds = selectedFiles.map(f => f.model_id).filter(Boolean);
            await providersApi.downloadModels(providerId, { file_ids: fileIds, model_ids: modelIds });
            toast.success(`Queued sync of ${selectedFiles.length} model(s) to ${providerId}`);
            setSelectedFiles([]);
            setShowBatchSyncModal(false);
            refetch();
        } catch (err) {
            toast.error(`Sync failed: ${err.message}`);
        }
    };

    return (
        <div className="space-y-4 md:space-y-6">
            {/* Storage Footprint Analytics Bar */}
            <div className="bg-[#0B0E14]/70 border border-white/5 rounded-2xl p-4 shadow-inner">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                        <div className="p-2.5 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-400 shadow-inner">
                            <HardDrive size={20} />
                        </div>
                        <div>
                            <div className="text-2xs font-bold text-gray-500 uppercase tracking-widest">Library Storage</div>
                            <div className="text-sm font-black text-white flex items-center gap-2">
                                <span>{formatBytes(totalStorageBytes)}</span>
                                <span className="text-xs font-normal text-gray-500">
                                    • {filteredFiles.length} models visible
                                </span>
                            </div>
                        </div>
                    </div>

                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => {
                                setIsSelectMode(!isSelectMode);
                                if (isSelectMode) setSelectedFiles([]);
                            }}
                            className={`px-3 py-1.5 rounded-xl text-xs font-bold border transition-all flex items-center gap-1.5 ${
                                isSelectMode
                                    ? 'bg-blue-600 text-white border-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.3)]'
                                    : 'bg-[#0B0E14] text-gray-300 border-white/10 hover:border-white/20'
                            }`}
                        >
                            <CheckSquare size={13} />
                            <span>{isSelectMode ? 'Cancel Selection' : 'Select Models'}</span>
                        </button>
                    </div>
                </div>
            </div>

            {/* Category Tabs */}
            <div className="flex overflow-x-auto no-scrollbar gap-2 pb-2 px-1">
                {CATEGORIES.map(cat => (
                    <button
                        key={cat.id}
                        onClick={() => {
                            setCategory(cat.id);
                            setSelectedFiles([]);
                        }}
                        className={`shrink-0 px-5 py-2.5 rounded-full text-2xs font-bold uppercase tracking-widest whitespace-nowrap transition-all duration-300 shadow-lg ${
                            category === cat.id
                                ? 'bg-blue-600/20 text-blue-400 border border-blue-500 shadow-[0_0_15px_rgba(59,130,246,0.3)]'
                                : 'bg-[#0B0E14]/80 text-gray-400 border border-white/5 hover:bg-black/40 hover:text-white hover:border-white/10'
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

                <select
                    value={filterAvailability}
                    onChange={(e) => setFilterAvailability(e.target.value)}
                    className="bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 py-2 text-xs font-medium text-white focus:outline-none focus:ring-2 focus:ring-blue-500/50 shadow-inner glow-focus"
                >
                    <option value="all">All Availability</option>
                    <option value="ready">Ready on Providers</option>
                    <option value="missing">Missing / Needs Sync</option>
                </select>

                <label className="flex items-center gap-2.5 bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 py-2 text-2xs font-bold text-gray-400 uppercase tracking-widest cursor-pointer hover:border-white/20 transition-colors shadow-inner">
                    <input
                        type="checkbox"
                        checked={showNSFW}
                        onChange={(e) => setShowNSFW(e.target.checked)}
                        className="rounded w-3.5 h-3.5 bg-black/40 border-gray-600 text-blue-500 focus:ring-blue-500"
                    />
                    Show NSFW
                </label>

                {(filterBaseModel !== 'all' || filterType !== 'all' || filterAvailability !== 'all' || !showNSFW) && (
                    <button
                        onClick={() => {
                            setFilterBaseModel('all');
                            setFilterType('all');
                            setFilterAvailability('all');
                            setShowNSFW(true);
                        }}
                        className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-2 text-2xs font-bold text-red-400 uppercase tracking-widest hover:bg-red-500/20 hover:border-red-500/30 transition-colors shadow-inner"
                    >
                        Clear Filters
                    </button>
                )}
            </div>

            {/* Search and Action Bar */}
            <div className="mb-6 space-y-4">
                <div className="flex flex-wrap gap-4">
                    <div className="relative flex-1">
                        <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500" size={20} />
                        <input
                            type="text"
                            aria-label="Search models" placeholder="Search models..."
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
                                toast.success(`Cleanup complete! Removed ${res.deleted_models?.length ?? 0} orphaned models.`);
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

                    <ModelTagFilter
                        availableTags={availableTags}
                        selectedTags={selectedTags}
                        onSelectedTagsChange={setSelectedTags}
                        tagsError={isError ? error : null}
                        onRetryTags={refetch}
                    />
                </div>
            </div>

            {/* Model Grid */}
            {loading && filteredFiles.length === 0 ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6">
                    {Array.from({ length: 10 }).map((_, i) => (
                        <div key={i} className="aspect-[2/3] bg-white/5 rounded-2xl animate-pulse shadow-inner" />
                    ))}
                </div>
            ) : isError ? (
                <QueryErrorState noun="installed models" error={error} onRetry={refetch} />
            ) : filteredFiles.length === 0 ? (
                <div className="text-center py-20 text-gray-500 glass-panel rounded-3xl border border-white/5">
                    <HardDrive className="mx-auto mb-4 opacity-50 text-blue-400 drop-shadow-[0_0_10px_rgba(59,130,246,0.4)]" size={64} />
                    <p className="text-xl font-bold tracking-wide text-gray-300">No models found</p>
                    <p className="text-sm opacity-70 mt-2">Try adjusting your search or filters</p>
                </div>
            ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6">
                    {filteredFiles.map(file => (
                        <InstalledModelRow
                            key={file.name}
                            file={file}
                            providers={providers}
                            providersLoading={providersLoading}
                            onSelect={setSelectedModel}
                            onCheckDependencies={handleCheckDependencies}
                            onDelete={handleDelete}
                            isSelectMode={isSelectMode}
                            isSelected={selectedFiles.some(f => f.name === file.name)}
                            onToggleSelect={handleToggleSelect}
                        />
                    ))}
                </div>
            )}

            <div ref={sentinelRef} className="h-4" />

            {loadingMore && (
                <div className="flex justify-center py-8">
                    <Loader2 className="animate-spin text-gray-400" size={32} />
                </div>
            )}

            {/* Multi-Selection Floating Action Bar */}
            {selectedFiles.length > 0 && (
                <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 bg-[#0B0E14]/95 border border-white/10 rounded-2xl p-3 shadow-2xl backdrop-blur-xl flex items-center gap-3 animate-in fade-in slide-in-from-bottom-4 max-w-[95vw] overflow-x-auto">
                    <div className="px-3 py-1 bg-blue-500/20 text-blue-400 rounded-lg text-xs font-bold border border-blue-500/30 whitespace-nowrap">
                        {selectedFiles.length} selected
                    </div>
                    <button
                        onClick={handleSelectAll}
                        className="px-3 py-1.5 hover:bg-white/5 rounded-lg text-xs font-medium text-gray-300 transition-colors whitespace-nowrap"
                    >
                        {selectedFiles.length === filteredFiles.length ? 'Deselect All' : `Select All (${filteredFiles.length})`}
                    </button>
                    <button
                        onClick={() => setSelectedFiles([])}
                        className="px-3 py-1.5 hover:bg-white/5 rounded-lg text-xs font-medium text-gray-400 hover:text-white transition-colors"
                    >
                        Clear
                    </button>

                    <div className="h-4 w-px bg-white/10" />

                    <button
                        onClick={() => setShowBatchSyncModal(true)}
                        className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold flex items-center gap-1.5 shadow-md transition-all active:scale-95 whitespace-nowrap"
                    >
                        <Download size={13} />
                        <span>Sync to Provider...</span>
                    </button>

                    <button
                        onClick={handleBatchDelete}
                        className="px-3 py-1.5 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 text-red-300 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-all active:scale-95 whitespace-nowrap"
                    >
                        <Trash2 size={13} />
                        <span>Delete Selected</span>
                    </button>
                </div>
            )}

            {/* Batch Provider Sync Modal */}
            {showBatchSyncModal && (
                <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
                    <div className="bg-gray-800 rounded-2xl border border-gray-700 max-w-md w-full p-6 shadow-2xl space-y-4">
                        <div className="flex items-center justify-between border-b border-gray-700 pb-3">
                            <h3 className="text-base font-bold text-white">Sync {selectedFiles.length} Models</h3>
                            <button
                                onClick={() => setShowBatchSyncModal(false)}
                                className="text-gray-400 hover:text-white"
                            >
                                <X size={18} />
                            </button>
                        </div>
                        <p className="text-xs text-gray-400">
                            Select a target provider to queue downloads for the {selectedFiles.length} selected models.
                        </p>
                        <div className="space-y-2 max-h-56 overflow-y-auto custom-scrollbar">
                            {providers.filter(p => p.enabled).map(p => (
                                <button
                                    key={p.id}
                                    onClick={() => handleBatchSyncSubmit(p.id)}
                                    className="w-full flex items-center justify-between p-3 rounded-xl border border-gray-700 hover:border-blue-500/50 bg-gray-900/60 hover:bg-gray-750 transition-all text-left"
                                >
                                    <div>
                                        <div className="text-xs font-bold text-white">{p.name || p.id}</div>
                                        <div className="text-2xs text-gray-500 uppercase">{p.type}</div>
                                    </div>
                                    <span className="text-xs font-bold text-blue-400">Sync →</span>
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {selectedModel && (
                <ModelDetailsModal
                    file={selectedModel}
                    providers={providers}
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
