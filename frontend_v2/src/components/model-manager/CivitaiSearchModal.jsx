import { useState } from 'react';
import { X, Search, Loader2, Star, Download } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import ModalOverlay from '../common/ModalOverlay';
import ProgressiveImage from '../ProgressiveImage';
import { getOptimizedImageUrl } from '../../utils/imageOptimization';

export default function CivitaiSearchModal({ initialQuery, onClose, onSelect }) {
    // We clean up initial query locally so user sees a clean input
    const cleanInitialQuery = (initialQuery || "").replace(/(_|\.safetensors|\.ckpt|v\d+.*)/gi, ' ').trim();
    
    const [searchInput, setSearchInput] = useState(cleanInitialQuery);
    const [query, setQuery] = useState(cleanInitialQuery);
    const [type, setType] = useState("");
    const [sort, setSort] = useState("Highest Rated");
    const [baseModel, setBaseModel] = useState("");
    const [nsfw, setNsfw] = useState("false");

    const { data: results, isLoading, isError, error } = useQuery({
        queryKey: ['civitaiSearch', query, type, sort, baseModel, nsfw],
        queryFn: async () => {
            if (!query) return { items: [] };
            const params = new URLSearchParams({ query });
            if (type) params.append('types', type);
            if (sort) params.append('sort', sort);
            if (baseModel) params.append('baseModels', baseModel);
            if (nsfw !== "") params.append('nsfw', nsfw);
            params.append('limit', '20');
            const data = await api.get(`/api/v2/models/external/civitai?${params.toString()}`);
            return data;
        },
        enabled: !!query,
        retry: false
    });

    const handleSearch = (e) => {
        e.preventDefault();
        setQuery(searchInput);
    };

    return (
        <ModalOverlay onClose={onClose} className="z-[60] bg-black/80 backdrop-blur-sm">
            <div
                role="dialog"
                aria-modal="true"
                aria-label="Search CivitAI"
                className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-5xl max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
                
                {/* Header & Search */}
                <div className="p-6 border-b border-gray-800 space-y-4">
                    <div className="flex justify-between items-center">
                        <h2 className="text-xl font-bold text-white">Search CivitAI</h2>
                        <button onClick={onClose} className="p-2 hover:bg-gray-800 rounded-full transition-colors">
                            <X size={20} />
                        </button>
                    </div>

                    <form onSubmit={handleSearch} className="flex gap-2">
                        <div className="relative flex-1">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={18} />
                            <input
                                type="text"
                                aria-label="Search CivitAI models" placeholder="Search CivitAI models..."
                                value={searchInput}
                                onChange={(e) => setSearchInput(e.target.value)}
                                className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-10 pr-4 py-2.5 text-white focus:ring-2 focus:ring-blue-500 outline-none"
                                autoFocus
                            />
                        </div>
                        <button type="submit" className="bg-blue-600 hover:bg-blue-500 text-white px-6 py-2.5 rounded-lg font-medium transition-colors">
                            Search
                        </button>
                    </form>

                    {/* Filters */}
                    <div className="flex flex-wrap gap-3">
                        <select 
                            value={type} onChange={e => setType(e.target.value)}
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white focus:ring-2 focus:ring-blue-500 outline-none"
                        >
                            <option value="">All Types</option>
                            <option value="Checkpoint">Checkpoint</option>
                            <option value="LORA">LoRA</option>
                            <option value="TextualInversion">Textual Inversion</option>
                            <option value="Controlnet">ControlNet</option>
                            <option value="VAE">VAE</option>
                        </select>
                        <select 
                            value={baseModel} onChange={e => setBaseModel(e.target.value)}
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white focus:ring-2 focus:ring-blue-500 outline-none"
                        >
                            <option value="">All Base Models</option>
                            <option value="SD 1.5">SD 1.5</option>
                            <option value="SDXL 1.0">SDXL 1.0</option>
                            <option value="Pony">Pony</option>
                            <option value="Flux.1 D">Flux.1 D</option>
                            <option value="Flux.1 S">Flux.1 S</option>
                        </select>
                        <select 
                            value={sort} onChange={e => setSort(e.target.value)}
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white focus:ring-2 focus:ring-blue-500 outline-none"
                        >
                            <option value="Highest Rated">Highest Rated</option>
                            <option value="Most Downloaded">Most Downloaded</option>
                            <option value="Newest">Newest</option>
                        </select>
                        <select 
                            value={nsfw} onChange={e => setNsfw(e.target.value)}
                            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white focus:ring-2 focus:ring-blue-500 outline-none"
                        >
                            <option value="false">Safe for Work</option>
                            <option value="true">Include NSFW</option>
                        </select>
                    </div>
                </div>

                {/* Results Area */}
                <div className="flex-1 overflow-y-auto p-6 bg-black/20">
                    {isLoading ? (
                        <div className="flex justify-center items-center h-full min-h-[300px]">
                            <Loader2 className="animate-spin text-blue-500" size={32} />
                        </div>
                    ) : isError ? (
                        <div className="text-center text-red-400 mt-10 min-h-[300px]">
                            Failed to search: {error?.message}
                        </div>
                    ) : results?.items?.length > 0 ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                            {results.items.map(model => (
                                <div key={model.id} className="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden hover:border-blue-500/50 transition-colors flex flex-col group">
                                    <div className="aspect-[2/3] bg-gray-900 relative">
                                        {model.modelVersions?.[0]?.images?.[0]?.url && (() => {
                                            const proxyUrl = `/api/v2/models/preview/${model.id}?image_index=0`;
                                            return (
                                                <ProgressiveImage 
                                                    src={proxyUrl} 
                                                    medium={getOptimizedImageUrl(proxyUrl, 450)}
                                                    alt={model.name}
                                                    className="absolute inset-0 w-full h-full object-cover"
                                                    size="medium"
                                                    aspectRatio="2/3"
                                                />
                                            );
                                        })()}
                                        <div className="absolute top-2 right-2 bg-black/60 backdrop-blur text-white text-xs px-2 py-1 rounded">
                                            {model.type}
                                        </div>
                                    </div>
                                    <div className="p-3 flex-1 flex flex-col">
                                        <h3 className="font-bold text-sm text-white line-clamp-1 mb-1">{model.name}</h3>
                                        <div className="flex items-center gap-3 text-xs text-gray-400 mb-3">
                                            <div className="flex items-center gap-1">
                                                <Star size={12} className="text-yellow-500" />
                                                {(model.stats?.thumbsUpCount || 0).toLocaleString()}
                                            </div>
                                            <div className="flex items-center gap-1">
                                                <Download size={12} />
                                                {(model.stats?.downloadCount || 0).toLocaleString()}
                                            </div>
                                        </div>
                                        <button 
                                            onClick={() => onSelect(model)}
                                            className="w-full mt-auto bg-blue-600/20 hover:bg-blue-600 text-blue-400 hover:text-white border border-blue-500/30 hover:border-blue-500 py-2 rounded-lg text-sm font-medium transition-all"
                                        >
                                            Select & Autopopulate
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : query ? (
                        <div className="text-center text-gray-500 mt-10 min-h-[300px]">
                            No models found matching "{query}"
                        </div>
                    ) : (
                        <div className="text-center text-gray-500 mt-10 min-h-[300px]">
                            Enter a search query to find models
                        </div>
                    )}
                </div>
            </div>
        </ModalOverlay>
    );
}
