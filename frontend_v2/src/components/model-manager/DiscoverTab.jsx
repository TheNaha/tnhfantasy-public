import { useEffect, useState, useMemo } from 'react';
import { Search, Loader2, Download, Globe, Filter } from 'lucide-react';
import toast from 'react-hot-toast';
import { api } from '../../api';

import ModelCard from './ModelCard';
import ModelImportCard from './ModelImportCard';
import { useCivitaiEnums, useCivitaiTags, useCivitaiSearch } from '../../hooks/useCivitaiSearch';
import useDebounce from '../../hooks/useDebounce';

const SORT_OPTIONS = [['', 'Relevance'], ['Newest', 'Newest'], ['Most Downloaded', 'Downloads'], ['Most Liked', 'Likes']];
const PERIOD_OPTIONS = [['', 'All Time'], ['Year', 'Year'], ['Month', 'Month'], ['Week', 'Week'], ['Day', 'Day']];

function MultiSelectDropdown({ label, options, selected, onChange }) {
    const [open, setOpen] = useState(false);
    return (
        <div className="relative flex flex-col gap-1.5">
            <label className="text-xs font-bold uppercase tracking-widest text-gray-500">{label}</label>
            <div 
                className="bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 py-2 text-xs font-medium text-white cursor-pointer select-none h-10 flex items-center min-w-[120px] shadow-inner transition-colors hover:border-white/20"
                onClick={() => setOpen(!open)}
            >
                {selected.length === 0 ? 'All' : `${selected.length} Selected`}
            </div>
            {open && (
                <>
                    <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
                    <div className="absolute top-[calc(100%+0.5rem)] left-0 w-56 glass-panel border border-white/10 rounded-2xl shadow-2xl z-20 max-h-64 overflow-y-auto p-2 backdrop-blur-xl">
                        {options.map(opt => {
                            const value = typeof opt === 'string' ? opt : opt[0];
                            const text = typeof opt === 'string' ? opt : opt[1];
                            if (!value) return null;
                            const isChecked = selected.includes(value);
                            return (
                                <label key={value} className="flex items-center gap-3 p-2.5 hover:bg-white/5 rounded-xl cursor-pointer transition-colors">
                                    <input 
                                        type="checkbox" 
                                        checked={isChecked}
                                        onChange={() => {
                                            if (isChecked) onChange(selected.filter(v => v !== value));
                                            else onChange([...selected, value]);
                                        }}
                                        className="rounded border-white/10 bg-black/40 text-blue-500 focus:ring-blue-500/50 w-4 h-4"
                                    />
                                    <span className="text-sm font-medium text-gray-300 line-clamp-2 sm:truncate break-words">{text}</span>
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

    const debouncedQuery = useDebounce(query, 600);
    const debouncedUsername = useDebounce(filterUsername, 600);
    const debouncedTag = useDebounce(filterTag, 600);

    const { data: enumsData } = useCivitaiEnums();
    const { data: tagsData } = useCivitaiTags();
    
    const civitaiEnums = enumsData || { ModelType: [], BaseModel: [] };
    const popularTags = tagsData || [];

    const filters = useMemo(() => ({
        source,
        query: debouncedQuery,
        types: filterTypes,
        sort: filterSort,
        baseModels: filterBaseModels,
        nsfw: filterNsfw,
        period: filterPeriod,
        username: debouncedUsername,
        tag: debouncedTag
    }), [source, debouncedQuery, filterTypes, filterSort, filterBaseModels, filterNsfw, filterPeriod, debouncedUsername, debouncedTag]);

    const {
        data: searchData,
        fetchNextPage,
        hasNextPage,
        isFetching,
        isFetchingNextPage
    } = useCivitaiSearch(filters);

    const results = useMemo(() => {
        return searchData ? searchData.pages.flatMap(page => page.items || []) : [];
    }, [searchData]);

    const handleSearch = (e) => {
        e.preventDefault();
        // Since we debounce, forcing a search might not be immediately necessary.
    };

    const handleLoadMore = () => {
        if (!isFetchingNextPage && hasNextPage) {
            fetchNextPage();
        }
    };

    const handleUrlImport = async () => {
        if (!urlInput.trim()) return;

        setImporting(true);
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
        <div className="space-y-4 md:space-y-6">
            {/* Search & Import Bar */}
            {/* Search & Import Bar */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Search */}
                <form onSubmit={handleSearch} className="relative flex gap-3">
                    <div className="relative flex-1">
                        <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500" size={20} />
                        <input
                            type="text"
                            aria-label="Search models" placeholder="Search models..."
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            enterKeyHint="search"
                            className="w-full bg-[#0B0E14]/80 border border-white/10 rounded-xl pl-12 pr-4 py-3.5 text-white focus:ring-2 focus:ring-blue-500/50 outline-none shadow-inner glow-focus placeholder-gray-600 font-medium"
                        />
                    </div>
                    <select
                        value={source}
                        onChange={(e) => setSource(e.target.value)}
                        className="bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 text-white focus:outline-none focus:ring-2 focus:ring-blue-500/50 font-medium shadow-inner glow-focus"
                    >
                        <option value="civitai">CivitAI</option>
                        <option value="huggingface">HuggingFace</option>
                    </select>
                    <button
                        type="submit"
                        className="bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white px-6 rounded-xl font-bold transition-all duration-300 flex items-center shadow-lg hover:shadow-[0_0_15px_rgba(59,130,246,0.4)] transform active:scale-95 border border-white/10"
                    >
                        Search
                    </button>
                </form>

                {/* URL Import — `min-w-0` on the row and the input. The import
                    button is a 50px `px-6` control that cannot shrink, and the
                    input's automatic minimum is its intrinsic width, so at 360px
                    the pair overflowed by 11px and the app root's
                    `overflow-x-hidden` put the whole button outside the viewport:
                    the only way to import a model by URL was unreachable on a
                    phone. */}
                <div className="flex gap-3 min-w-0">
                    <input
                        type="text"
                        aria-label="Model URL to import" placeholder="Paste CivitAI or HuggingFace URL..."
                        value={urlInput}
                        onChange={(e) => setUrlInput(e.target.value)}
                        className="flex-1 min-w-0 bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 py-3.5 text-white focus:outline-none focus:ring-2 focus:ring-purple-500/50 shadow-inner glow-focus placeholder-gray-600 font-medium transition-all"
                    />
                    <button
                        onClick={handleUrlImport}
                        disabled={importing || !urlInput}
                        className="bg-black/40 hover:bg-[#0B0E14] disabled:opacity-50 disabled:cursor-not-allowed text-white border border-white/10 hover:border-purple-500/50 px-6 rounded-xl font-bold transition-all duration-300 flex items-center gap-2 shadow-lg hover:shadow-[0_0_15px_rgba(168,85,247,0.3)] transform active:scale-95"
                        aria-label="Import model from URL"
                    >
                        {importing ? <Loader2 className="animate-spin text-purple-400" /> : <Download size={20} className="text-purple-400" />}
                        Import
                    </button>
                </div>
            </div>

            {/* Popular Tags & Active Filters (CivitAI only) */}
            {source === 'civitai' && (
                <div className="flex flex-col gap-4">
                    {(filterUsername || filterTag) && (
                        <div className="flex flex-wrap items-center gap-3">
                            <span className="text-xs font-bold text-gray-500 uppercase tracking-widest">Active Filters:</span>
                            {filterUsername && (
                                <div className="flex items-center gap-1.5 bg-blue-500/10 border border-blue-500/30 text-blue-300 px-3 py-1.5 rounded-full text-xs shadow-inner">
                                    <span className="font-bold tracking-wide">@{filterUsername}</span>
                                    <button onClick={() => setFilterUsername("")} className="hover:text-white ml-1 transition-colors">✕</button>
                                </div>
                            )}
                            {filterTag && (
                                <div className="flex items-center gap-1.5 bg-purple-500/10 border border-purple-500/30 text-purple-300 px-3 py-1.5 rounded-full text-xs shadow-inner">
                                    <span className="font-bold tracking-wide">#{filterTag}</span>
                                    <button onClick={() => setFilterTag("")} className="hover:text-white ml-1 transition-colors">✕</button>
                                </div>
                            )}
                        </div>
                    )}
                    {popularTags.length > 0 && (
                        <div className="flex overflow-x-auto no-scrollbar items-center gap-2 pb-2 px-1">
                            <span className="text-xs font-bold text-gray-500 uppercase tracking-widest whitespace-nowrap sticky left-0 bg-[#0B0E14] pr-4 z-10 shrink-0">Trending</span>
                            {popularTags.map(t => (
                                <button
                                    key={t.name}
                                    onClick={() => setFilterTag(filterTag === t.name ? "" : t.name)}
                                    className={`shrink-0 whitespace-nowrap px-4 py-1.5 rounded-full text-2xs font-bold tracking-widest uppercase transition-all duration-300 shadow-inner ${
                                        filterTag === t.name 
                                            ? 'bg-purple-600/20 border border-purple-500 text-purple-300 shadow-[0_0_10px_rgba(168,85,247,0.3)]' 
                                            : 'bg-[#0B0E14]/80 border border-white/5 text-gray-400 hover:bg-white/5 hover:text-white hover:border-white/10'
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
                <div className="flex flex-wrap gap-4 p-5 rounded-2xl border border-white/5 bg-[#0B0E14]/60 shadow-inner">
                    <MultiSelectDropdown 
                        label="Type" 
                        options={civitaiEnums.ModelType} 
                        selected={filterTypes} 
                        onChange={setFilterTypes} 
                    />
                    <div className="flex flex-col gap-1.5">
                        <label className="text-xs font-bold uppercase tracking-widest text-gray-500">Sort</label>
                        <select value={filterSort} onChange={e => setFilterSort(e.target.value)}
                            className="bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 py-2 text-xs font-medium text-white h-10 shadow-inner glow-focus focus:ring-2 focus:ring-blue-500/50 outline-none">
                            {SORT_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                    </div>
                    <MultiSelectDropdown 
                        label="Base Model" 
                        options={civitaiEnums.BaseModel} 
                        selected={filterBaseModels} 
                        onChange={setFilterBaseModels} 
                    />
                    <div className="flex flex-col gap-1.5">
                        <label className="text-xs font-bold uppercase tracking-widest text-gray-500">NSFW</label>
                        <select value={filterNsfw} onChange={e => setFilterNsfw(e.target.value)}
                            className="bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 py-2 text-xs font-medium text-white h-10 shadow-inner glow-focus focus:ring-2 focus:ring-blue-500/50 outline-none">
                            <option value="">All</option>
                            <option value="true">NSFW</option>
                            <option value="false">SFW Only</option>
                        </select>
                    </div>
                    <div className="flex flex-col gap-1.5">
                        <label className="text-xs font-bold uppercase tracking-widest text-gray-500">Period</label>
                        <select value={filterPeriod} onChange={e => setFilterPeriod(e.target.value)}
                            className="bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 py-2 text-xs font-medium text-white h-10 shadow-inner glow-focus focus:ring-2 focus:ring-blue-500/50 outline-none">
                            {PERIOD_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                    </div>
                    <div className="flex flex-col gap-1.5">
                        <label className="text-xs font-bold uppercase tracking-widest text-gray-500">Creator</label>
                        <input 
                            type="text" 
                            aria-label="CivitAI username" placeholder="@username"
                            value={filterUsername}
                            onChange={e => setFilterUsername(e.target.value)}
                            className="bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 py-2 text-xs font-medium text-white h-10 w-[140px] shadow-inner glow-focus focus:ring-2 focus:ring-blue-500/50 outline-none placeholder-gray-600"
                        />
                    </div>
                    <div className="flex flex-col gap-1.5">
                        <label className="text-xs font-bold uppercase tracking-widest text-gray-500">Tag</label>
                        <input 
                            type="text" 
                            aria-label="Model tag" placeholder="#tag"
                            value={filterTag}
                            onChange={e => setFilterTag(e.target.value)}
                            className="bg-[#0B0E14]/80 border border-white/10 rounded-xl px-4 py-2 text-xs font-medium text-white h-10 w-[140px] shadow-inner glow-focus focus:ring-2 focus:ring-purple-500/50 outline-none placeholder-gray-600"
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
                            className="text-2xs font-bold uppercase tracking-widest text-red-400 hover:text-white px-4 py-2.5 rounded-xl border border-red-500/20 bg-red-500/10 hover:bg-red-500/20 transition-colors shadow-inner h-10">
                            Clear
                        </button>
                    </div>
                </div>
            )}

            {/* Modal Overlay for ModelImportCard */}
            {importedModel && (
                <ModelImportCard model={importedModel} onCancel={() => setImportedModel(null)} />
            )}

            {/* Content Area */}
            {isFetching && !isFetchingNextPage ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                    {Array.from({ length: 8 }).map((_, i) => (
                        <div key={i} className="aspect-[2/3] bg-white/5 rounded-2xl animate-pulse shadow-inner" />
                    ))}
                </div>
            ) : results.length > 0 ? (
                <div className="space-y-4 md:space-y-6">
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
                    
                    {hasNextPage && (
                        <div className="flex justify-center pt-6 pb-10">
                            <button
                                onClick={handleLoadMore}
                                disabled={isFetchingNextPage}
                                className="bg-[#0B0E14]/80 hover:bg-black/40 disabled:opacity-50 text-white px-8 py-3.5 rounded-2xl font-bold tracking-wide flex items-center gap-3 transition-all duration-300 border border-white/10 shadow-lg hover:shadow-[0_0_15px_rgba(255,255,255,0.1)] transform active:scale-95"
                            >
                                {isFetchingNextPage ? (
                                    <>
                                        <Loader2 className="animate-spin text-blue-400" size={20} />
                                        <span>Loading more...</span>
                                    </>
                                ) : (
                                    'Load More Results'
                                )}
                            </button>
                        </div>
                    )}
                </div>
            ) : (
                <div className="text-center py-24 text-gray-500 glass-panel rounded-3xl border border-white/5 shadow-2xl">
                    <Globe size={64} className="mx-auto mb-6 opacity-40 text-blue-400 drop-shadow-[0_0_15px_rgba(59,130,246,0.5)]" />
                    <p className="text-xl font-bold tracking-wide text-gray-300">Search for models or paste a URL (CivitAI / HuggingFace) to get started</p>
                </div>
            )}
        </div>
    );
}
