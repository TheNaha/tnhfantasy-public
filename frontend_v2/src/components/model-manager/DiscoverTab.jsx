import { useState } from 'react';
import { Search, Loader2, Download, Globe } from 'lucide-react';
import toast from 'react-hot-toast';
import { api } from '../../api';
import { ModelCardSkeleton } from '../Skeleton';
import ModelCard from './ModelCard';
import ModelImportCard from './ModelImportCard';

export default function DiscoverTab() {
    const [query, setQuery] = useState("");
    const [urlInput, setUrlInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [results, setResults] = useState([]);
    const [importing, setImporting] = useState(false);
    const [importedModel, setImportedModel] = useState(null);
    const [source, setSource] = useState("civitai");

    const handleSearch = async (e) => {
        e.preventDefault();
        if (!query.trim()) return;

        setLoading(true);
        setImportedModel(null);
        try {
            const endpoint = source === 'civitai' ? '/api/v2/models/external/civitai' : '/api/v2/models/external/huggingface';
            const data = await api.get(`${endpoint}?query=${encodeURIComponent(query)}&limit=20`);
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
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    e.preventDefault();
                                    handleSearch(e);
                                }
                            }}
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
                        <ModelCard key={model.id} model={model} onSelect={handleModelSelect} source={source} />
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
