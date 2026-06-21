import { useEffect, useState, useCallback } from 'react';
import { Search, Loader2, Download, Globe, Filter } from 'lucide-react';
import toast from 'react-hot-toast';
import { api } from '../../api';
import { ModelCardSkeleton } from '../Skeleton';
import ModelCard from './ModelCard';
import ModelImportCard from './ModelImportCard';

const MODEL_TYPES = ['', 'Checkpoint', 'LORA', 'LoRA', 'VAE', 'Controlnet', 'Upscaler', 'TextualInversion', 'Hypernetwork', 'MotionModule'];
const SORT_OPTIONS = [['', 'Relevance'], ['Newest', 'Newest'], ['Most Downloaded', 'Downloads'], ['Most Liked', 'Likes']];
const BASE_MODELS = ['', 'SD1.5', 'SDXL', 'SD3', 'SD3.5', 'FLUX', 'Pony', 'Illustrious'];

export default function DiscoverTab() {
    const [query, setQuery] = useState("");
    const [urlInput, setUrlInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [results, setResults] = useState([]);
    const [importing, setImporting] = useState(false);
    const [importedModel, setImportedModel] = useState(null);
    const [source, setSource] = useState("civitai");
    const [installedInfoByModelId, setInstalledInfoByModelId] = useState({});
    const [showFilters, setShowFilters] = useState(false);
    const [filterType, setFilterType] = useState("");
    const [filterSort, setFilterSort] = useState("");
    const [filterBaseModel, setFilterBaseModel] = useState("");
    const [filterNsfw, setFilterNsfw] = useState("");

    const buildSearchUrl = useCallback(() => {
        const endpoint = source === 'civitai' ? '/api/v2/models/external/civitai' : '/api/v2/models/external/huggingface';
        const params = new URLSearchParams({ query, limit: '20' });
        if (source === 'civitai') {
            if (filterType) params.append('types', filterType);
            if (filterSort) params.append('sort', filterSort);
            if (filterBaseModel) params.append('baseModels', filterBaseModel);
            if (filterNsfw) params.append('nsfw', filterNsfw);
        }
        return `${endpoint}?${params.toString()}`;
    }, [query, source, filterType, filterSort, filterBaseModel, filterNsfw]);

    const handleSearch = async (e) => {
        e.preventDefault();
        if (!query.trim()) return;

        setLoading(true);
        setImportedModel(null);
        setInstalledInfoByModelId({});
        try {
            const url = buildSearchUrl();
            const data = await api.get(url);
            setResults(data.items || []);
        } catch (err) {
            toast.error(err.message);
        } finally {
            setLoading(false);
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
                            type="button"
                            onClick={() => setShowFilters(v => !v)}
                            className={`rounded-xl px-3 border transition-colors ${
                                showFilters || filterType || filterSort || filterBaseModel || filterNsfw
                                    ? 'bg-blue-500/10 border-blue-500/30 text-blue-400'
                                    : 'bg-gray-900 border-gray-700 text-gray-400 hover:text-white'
                            }`}
                            title="Toggle filters"
                        >
                            <Filter size={18} />
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

            {/* Filter bar (CivitAI only) */}
            {showFilters && source === 'civitai' && (
                <div className="flex flex-wrap gap-3 p-4 rounded-xl border border-gray-700 bg-gray-900/60">
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] uppercase tracking-wider text-gray-500">Type</label>
                        <select value={filterType} onChange={e => setFilterType(e.target.value)}
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white">
                            {MODEL_TYPES.map(t => <option key={t} value={t}>{t || 'All Types'}</option>)}
                        </select>
                    </div>
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] uppercase tracking-wider text-gray-500">Sort</label>
                        <select value={filterSort} onChange={e => setFilterSort(e.target.value)}
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white">
                            {SORT_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                    </div>
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] uppercase tracking-wider text-gray-500">Base Model</label>
                        <select value={filterBaseModel} onChange={e => setFilterBaseModel(e.target.value)}
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white">
                            {BASE_MODELS.map(b => <option key={b} value={b}>{b || 'All'}</option>)}
                        </select>
                    </div>
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] uppercase tracking-wider text-gray-500">NSFW</label>
                        <select value={filterNsfw} onChange={e => setFilterNsfw(e.target.value)}
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white">
                            <option value="">All</option>
                            <option value="true">NSFW</option>
                            <option value="false">SFW Only</option>
                        </select>
                    </div>
                    <div className="flex items-end">
                        <button onClick={() => { setFilterType(""); setFilterSort(""); setFilterBaseModel(""); setFilterNsfw(""); }}
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
            ) : (
                <div className="text-center py-20 text-gray-500">
                    <Globe size={48} className="mx-auto mb-4 opacity-20" />
                    <p>Search for models or paste a URL (CivitAI / HuggingFace) to get started</p>
                </div>
            )}
        </div>
    );
}
