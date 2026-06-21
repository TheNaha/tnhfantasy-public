import { useEffect, useState, useCallback } from 'react';
import { Search, Loader2, Download, Globe, Filter } from 'lucide-react';
import toast from 'react-hot-toast';
import { api } from '../../api';
import { ModelCardSkeleton } from '../Skeleton';
import ModelCard from './ModelCard';
import ModelImportCard from './ModelImportCard';

const SORT_OPTIONS = [['', 'Relevance'], ['Newest', 'Newest'], ['Most Downloaded', 'Downloads'], ['Most Liked', 'Likes']];
const PERIOD_OPTIONS = [['', 'All Time'], ['Year', 'Year'], ['Month', 'Month'], ['Week', 'Week'], ['Day', 'Day']];

function MultiSelectDropdown({ label, options, selected, onChange }) {
    const [open, setOpen] = useState(false);
    return (
        <div className="relative flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-wider text-gray-500">{label}</label>
            <div 
                className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white cursor-pointer select-none h-[30px] flex items-center min-w-[100px]"
                onClick={() => setOpen(!open)}
            >
                {selected.length === 0 ? 'All' : `${selected.length} Selected`}
            </div>
            {open && (
                <>
                    <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
                    <div className="absolute top-full left-0 mt-1 w-48 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-20 max-h-60 overflow-y-auto py-1">
                        {options.map(opt => {
                            const value = typeof opt === 'string' ? opt : opt[0];
                            const text = typeof opt === 'string' ? opt : opt[1];
                            if (!value) return null;
                            const isChecked = selected.includes(value);
                            return (
                                <label key={value} className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-700 cursor-pointer">
                                    <input 
                                        type="checkbox" 
                                        checked={isChecked}
                                        onChange={() => {
                                            if (isChecked) onChange(selected.filter(v => v !== value));
                                            else onChange([...selected, value]);
                                        }}
                                        className="rounded bg-gray-900 border-gray-600 text-blue-500 focus:ring-blue-500 w-3 h-3"
                                    />
                                    <span className="text-xs text-white truncate">{text}</span>
                                </label>
                            );
                        })}
                    </div>
                </>
            )}
        </div>
    );
}

export default function DiscoverTab() {
    const getSaved = (key, defaultVal) => {
        try {
            const val = localStorage.getItem(`civitai_discover_${key}`);
            return val ? JSON.parse(val) : defaultVal;
        } catch {
            return defaultVal;
        }
    };

    const [query, setQuery] = useState(() => getSaved('query', ""));
    const [urlInput, setUrlInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [results, setResults] = useState([]);
    const [importing, setImporting] = useState(false);
    const [importedModel, setImportedModel] = useState(null);
    const [source, setSource] = useState(() => getSaved('source', "civitai"));
    const [installedInfoByModelId, setInstalledInfoByModelId] = useState({});
    const [filterTypes, setFilterTypes] = useState(() => getSaved('types', []));
    const [filterSort, setFilterSort] = useState(() => getSaved('sort', ""));
    const [filterBaseModels, setFilterBaseModels] = useState(() => getSaved('baseModels', []));
    const [filterNsfw, setFilterNsfw] = useState(() => getSaved('nsfw', ""));
    const [filterPeriod, setFilterPeriod] = useState(() => getSaved('period', ""));
    const [filterUsername, setFilterUsername] = useState(() => getSaved('username', ""));
    const [filterTag, setFilterTag] = useState(() => getSaved('tag', ""));
    const [popularTags, setPopularTags] = useState([]);

    // Sync to localStorage
    useEffect(() => {
        localStorage.setItem('civitai_discover_query', JSON.stringify(query));
        localStorage.setItem('civitai_discover_source', JSON.stringify(source));
        localStorage.setItem('civitai_discover_types', JSON.stringify(filterTypes));
        localStorage.setItem('civitai_discover_sort', JSON.stringify(filterSort));
        localStorage.setItem('civitai_discover_baseModels', JSON.stringify(filterBaseModels));
        localStorage.setItem('civitai_discover_nsfw', JSON.stringify(filterNsfw));
        localStorage.setItem('civitai_discover_period', JSON.stringify(filterPeriod));
        localStorage.setItem('civitai_discover_username', JSON.stringify(filterUsername));
        localStorage.setItem('civitai_discover_tag', JSON.stringify(filterTag));
    }, [query, source, filterTypes, filterSort, filterBaseModels, filterNsfw, filterPeriod, filterUsername, filterTag]);
    const [page, setPage] = useState(1);
    const [hasMore, setHasMore] = useState(false);
    const [loadingMore, setLoadingMore] = useState(false);

    const [civitaiEnums, setCivitaiEnums] = useState({ ModelType: [], BaseModel: [] });

    // Fetch CivitAI Enums and Tags on mount
    useEffect(() => {
        const loadEnums = async () => {
            try {
                const data = await api.get('/api/v2/models/external/civitai/enums');
                setCivitaiEnums({
                    ModelType: data.ModelType || [],
                    BaseModel: data.BaseModel || []
                });
            } catch (err) {
                console.warn("Failed to fetch CivitAI enums:", err);
                setCivitaiEnums({
                    ModelType: ['Checkpoint', 'LORA', 'VAE', 'Controlnet', 'Upscaler', 'TextualInversion', 'Hypernetwork', 'MotionModule'],
                    BaseModel: ['SD 1.5', 'SDXL 1.0', 'SD 3', 'SD 3.5', 'Flux.1 D', 'Pony', 'Illustrious']
                });
            }
        };
        const loadTags = async () => {
            try {
                const res = await fetch('https://civitai.com/api/v1/tags?limit=20');
                const data = await res.json();
                setPopularTags(data.items || []);
            } catch (err) {
                console.warn("Failed to fetch CivitAI tags:", err);
            }
        };
        loadEnums();
        loadTags();
    }, []);

    const buildSearchUrl = useCallback((targetPage = 1) => {
        const endpoint = `/api/v2/models/external/${source}`;
        const params = new URLSearchParams({ query, limit: '20' });
        if (source === 'civitai') {
            if (filterTypes.length > 0) params.append('types', filterTypes.join(','));
            if (filterSort) params.append('sort', filterSort);
            if (filterBaseModels.length > 0) params.append('baseModels', filterBaseModels.join(','));
            if (filterNsfw) params.append('nsfw', filterNsfw);
            if (filterPeriod) params.append('period', filterPeriod);
            if (filterUsername) params.append('username', filterUsername);
            if (filterTag) params.append('tag', filterTag);
            params.append('page', targetPage);
        }
        return `${endpoint}?${params.toString()}`;
    }, [query, source, filterTypes, filterSort, filterBaseModels, filterNsfw, filterPeriod, filterUsername, filterTag]);

    const fetchResults = useCallback(async () => {
        // If query is empty, maybe don't search, or if sorting by Newest/Most Downloaded, allow empty query.
        // But CivitAI allows empty queries.
        setLoading(true);
        setImportedModel(null);
        setInstalledInfoByModelId({});
        setPage(1);
        try {
            const url = buildSearchUrl(1);
            const data = await api.get(url);
            setResults(data.items || []);
            setHasMore(!!data.metadata?.nextPage);
        } catch (err) {
            // Only toast if it's not a 502/500 from empty spam
            if (!err.message.includes("502")) {
                toast.error(err.message);
            }
            setResults([]);
        } finally {
            setLoading(false);
        }
    }, [buildSearchUrl]);

    useEffect(() => {
        const handler = setTimeout(() => {
            fetchResults();
        }, 600);
        return () => clearTimeout(handler);
    }, [query, filterTypes, filterSort, filterBaseModels, filterNsfw, filterPeriod, filterUsername, filterTag, source, fetchResults]);

    const handleSearch = (e) => {
        e.preventDefault();
        fetchResults();
    };

    const handleLoadMore = async () => {
        if (loadingMore || !hasMore) return;
        setLoadingMore(true);
        const nextPage = page + 1;
        try {
            const url = buildSearchUrl(nextPage);
            const data = await api.get(url);
            setResults(prev => [...prev, ...(data.items || [])]);
            setHasMore(!!data.metadata?.nextPage);
            setPage(nextPage);
        } catch (err) {
            toast.error(err.message);
        } finally {
            setLoadingMore(false);
        }
    };

    const handleUrlImport = async () => {
        if (!urlInput.trim()) return;

        setImporting(true);
        setResults([]);
        try {
            const data = await api.post('/api/v2/models/external/parse', { url: urlInput });
            setImportedModel(data);
        } catch (err) {
            toast.error(err.message);
        } finally {
            setImporting(false);
        }
    };

    const handleModelSelect = (model) => {
        setImportedModel(model);
        setResults([]);
    };

    useEffect(() => {
        if (source !== 'civitai') {
            setInstalledInfoByModelId({});
            return;
        }

        const civitaiModelIds = results
            .map((model) => model.id)
            .filter((id) => Number.isInteger(id));

        if (civitaiModelIds.length === 0) {
            setInstalledInfoByModelId({});
            return;
        }

        let cancelled = false;

        api.post('/api/v2/models/check-installed/batch', {
            civitai_model_ids: civitaiModelIds,
        })
            .then((data) => {
                if (!cancelled) {
                    setInstalledInfoByModelId(data.models || {});
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setInstalledInfoByModelId({});
                }
            });

        return () => {
            cancelled = true;
        };
    }, [results, source]);

    return (
        <div className="space-y-6">
            {/* Search & Import Bar */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Search */}
                    <form onSubmit={handleSearch} className="relative flex gap-2">
                        <div className="relative flex-1">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={18} />
                            <input
                                type="text"
                                placeholder="Search models..."
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                                enterKeyHint="search"
                                className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-10 pr-4 py-2 text-white focus:ring-2 focus:ring-blue-500 outline-none"
                            />
                        </div>
                        <select
                            value={source}
                            onChange={(e) => setSource(e.target.value)}
                            className="bg-gray-900 border border-gray-700 rounded-xl px-3 text-white focus:outline-none focus:border-blue-500"
                        >
                            <option value="civitai">CivitAI</option>
                            <option value="huggingface">HuggingFace</option>
                        </select>
                        <button
                            type="submit"
                            className="bg-blue-600 hover:bg-blue-500 text-white px-4 rounded-xl font-medium transition-colors flex items-center"
                        >
                            Search
                        </button>
                    </form>

                {/* URL Import */}
                <div className="flex gap-2">
                    <input
                        type="text"
                        placeholder="Paste CivitAI or HuggingFace URL..."
                        value={urlInput}
                        onChange={(e) => setUrlInput(e.target.value)}
                        className="flex-1 bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-blue-500 transition-colors"
                    />
                    <button
                        onClick={handleUrlImport}
                        disabled={importing || !urlInput}
                        className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-6 rounded-xl font-medium transition-colors flex items-center gap-2"
                        aria-label="Import model from URL"
                    >
                        {importing ? <Loader2 className="animate-spin" /> : <Download size={18} />}
                        Import
                    </button>
                </div>
            </div>

            {/* Popular Tags & Active Filters (CivitAI only) */}
            {source === 'civitai' && (
                <div className="flex flex-col gap-3">
                    {(filterUsername || filterTag) && (
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="text-xs text-gray-500 uppercase tracking-wider">Active Filters:</span>
                            {filterUsername && (
                                <div className="flex items-center gap-1 bg-blue-900/50 border border-blue-500/50 text-blue-300 px-3 py-1 rounded-full text-xs">
                                    <span className="font-medium">@{filterUsername}</span>
                                    <button onClick={() => setFilterUsername("")} className="hover:text-white ml-1">✕</button>
                                </div>
                            )}
                            {filterTag && (
                                <div className="flex items-center gap-1 bg-purple-900/50 border border-purple-500/50 text-purple-300 px-3 py-1 rounded-full text-xs">
                                    <span className="font-medium">#{filterTag}</span>
                                    <button onClick={() => setFilterTag("")} className="hover:text-white ml-1">✕</button>
                                </div>
                            )}
                        </div>
                    )}
                    {popularTags.length > 0 && (
                        <div className="flex items-center gap-2 overflow-x-auto pb-2 scrollbar-thin scrollbar-thumb-gray-700 scrollbar-track-transparent">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider whitespace-nowrap sticky left-0 bg-gray-950 pr-2">Trending</span>
                            {popularTags.map(t => (
                                <button
                                    key={t.name}
                                    onClick={() => setFilterTag(filterTag === t.name ? "" : t.name)}
                                    className={`whitespace-nowrap px-3 py-1 rounded-full text-xs transition-colors border ${
                                        filterTag === t.name 
                                            ? 'bg-purple-600 border-purple-500 text-white' 
                                            : 'bg-gray-800 border-gray-700 text-gray-300 hover:bg-gray-700 hover:text-white'
                                    }`}
                                >
                                    {t.name}
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Filter bar (CivitAI only) */}
            {source === 'civitai' && (
                <div className="flex flex-wrap gap-3 p-4 rounded-xl border border-gray-700 bg-gray-900/60">
                    <MultiSelectDropdown 
                        label="Type" 
                        options={civitaiEnums.ModelType} 
                        selected={filterTypes} 
                        onChange={setFilterTypes} 
                    />
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] uppercase tracking-wider text-gray-500">Sort</label>
                        <select value={filterSort} onChange={e => setFilterSort(e.target.value)}
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white h-[30px]">
                            {SORT_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                    </div>
                    <MultiSelectDropdown 
                        label="Base Model" 
                        options={civitaiEnums.BaseModel} 
                        selected={filterBaseModels} 
                        onChange={setFilterBaseModels} 
                    />
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] uppercase tracking-wider text-gray-500">NSFW</label>
                        <select value={filterNsfw} onChange={e => setFilterNsfw(e.target.value)}
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white h-[30px]">
                            <option value="">All</option>
                            <option value="true">NSFW</option>
                            <option value="false">SFW Only</option>
                        </select>
                    </div>
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] uppercase tracking-wider text-gray-500">Period</label>
                        <select value={filterPeriod} onChange={e => setFilterPeriod(e.target.value)}
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white h-[30px]">
                            {PERIOD_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                    </div>
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] uppercase tracking-wider text-gray-500">Creator</label>
                        <input 
                            type="text" 
                            placeholder="@username"
                            value={filterUsername}
                            onChange={e => setFilterUsername(e.target.value)}
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white h-[30px] w-[120px] outline-none focus:border-blue-500"
                        />
                    </div>
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] uppercase tracking-wider text-gray-500">Tag</label>
                        <input 
                            type="text" 
                            placeholder="#tag"
                            value={filterTag}
                            onChange={e => setFilterTag(e.target.value)}
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white h-[30px] w-[120px] outline-none focus:border-purple-500"
                        />
                    </div>
                    <div className="flex items-end">
                        <button onClick={() => { 
                            setFilterTypes([]); 
                            setFilterSort(""); 
                            setFilterBaseModels([]); 
                            setFilterNsfw(""); 
                            setFilterPeriod("");
                            setFilterUsername("");
                            setFilterTag("");
                        }}
                            className="text-xs text-gray-500 hover:text-white px-3 py-1.5 rounded-lg border border-gray-700 bg-gray-800">
                            Clear
                        </button>
                    </div>
                </div>
            )}

            {/* Content Area */}
            {loading ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                    {Array.from({ length: 8 }).map((_, i) => (
                        <ModelCardSkeleton key={i} />
                    ))}
                </div>
            ) : importedModel ? (
                <ModelImportCard model={importedModel} onCancel={() => setImportedModel(null)} />
            ) : results.length > 0 ? (
                <div className="space-y-6">
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                        {results.map(model => (
                            <ModelCard
                                key={model.id}
                                model={model}
                                onSelect={handleModelSelect}
                                source={source}
                                installedInfo={installedInfoByModelId[String(model.id)] || null}
                            />
                        ))}
                    </div>
                    
                    {hasMore && (
                        <div className="flex justify-center pt-4 pb-8">
                            <button
                                onClick={handleLoadMore}
                                disabled={loadingMore}
                                className="bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-white px-6 py-2.5 rounded-xl font-medium flex items-center gap-2 transition-colors border border-gray-700"
                            >
                                {loadingMore ? (
                                    <>
                                        <Loader2 className="animate-spin" size={18} />
                                        Loading more...
                                    </>
                                ) : (
                                    'Load More Results'
                                )}
                            </button>
                        </div>
                    )}
                </div>
            ) : (
                <div className="text-center py-20 text-gray-500">
                    <Globe size={48} className="mx-auto mb-4 opacity-20" />
                    <p>Search for models or paste a URL (CivitAI / HuggingFace) to get started</p>
                </div>
            )}
        </div>
    );
}
