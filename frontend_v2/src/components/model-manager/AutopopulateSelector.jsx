import { useState, useEffect } from 'react';
import { X, Loader2, Search, Wand2, Star, Download, AlertCircle, Image as ImageIcon } from 'lucide-react';
import toast from 'react-hot-toast';
import { api } from '../../api';

function matchTone(score) {
    if (score >= 100) return 'text-green-400 bg-green-500/20 border-green-500/30';
    if (score >= 60) return 'text-blue-400 bg-blue-500/20 border-blue-500/30';
    if (score >= 30) return 'text-yellow-400 bg-yellow-500/20 border-yellow-500/30';
    return 'text-red-400 bg-red-500/20 border-red-500/30';
}

function ScoreBadge({ score, label }) {
    const color = matchTone(score);
    return (
        <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${color}`}>
            {score}% · {label}
        </span>
    );
}

export default function AutopopulateSelector({ modelId, modelName, modelType, onClose, onComplete }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [selectedCivitaiId, setSelectedCivitaiId] = useState(null);
    const [applying, setApplying] = useState(false);
    const [manualQuery, setManualQuery] = useState('');
    const [manualResults, setManualResults] = useState(null);
    const [searchingManual, setSearchingManual] = useState(false);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError(null);
        api.get(`/api/v2/models/${modelId}/autopopulate-candidates`)
            .then(res => {
                if (!cancelled) setData(res);
            })
            .catch(err => {
                if (!cancelled) setError(err.message);
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => { cancelled = true; };
    }, [modelId]);

    const candidates = data?.candidates || [];

    const handleApply = async () => {
        if (!selectedCivitaiId) {
            toast.error('Select a model first');
            return;
        }
        setApplying(true);
        try {
            await api.post(`/api/v2/models/${modelId}/autopopulate`, { civitai_id: selectedCivitaiId });
            toast.success('Model metadata updated!');
            if (onComplete) onComplete();
            onClose();
        } catch (err) {
            toast.error('Failed to autopopulate: ' + (err.message || 'Unknown error'));
        } finally {
            setApplying(false);
        }
    };

    const handleManualSearch = async (e) => {
        e.preventDefault();
        if (!manualQuery.trim()) return;
        setSearchingManual(true);
        setManualResults(null);
        try {
            const params = new URLSearchParams({ query: manualQuery, limit: '12' });
            const res = await api.get(`/api/v2/models/external/civitai?${params.toString()}`);
            setManualResults(res.items || []);
        } catch (err) {
            toast.error('Search failed: ' + err.message);
        } finally {
            setSearchingManual(false);
        }
    };

    return (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm" onClick={onClose}>
            <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-5xl max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>

                {/* Header */}
                <div className="p-6 border-b border-gray-800 flex items-center justify-between">
                    <div>
                        <h2 className="text-xl font-bold text-white flex items-center gap-2">
                            <Wand2 size={20} className="text-blue-400" />
                            Match with CivitAI
                        </h2>
                        <p className="text-sm text-gray-400 mt-1">
                            Find the matching CivitAI model for <span className="text-white font-medium">{data?.model_name || modelName}</span>
                        </p>
                    </div>
                    <button onClick={onClose} className="p-2 hover:bg-gray-800 rounded-full transition-colors">
                        <X size={20} />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                    {/* Local Model Summary */}
                    <div className="bg-gray-800/40 border border-gray-700/50 rounded-xl p-4">
                        <div className="flex items-start justify-between">
                            <div>
                                <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">Local Model</h3>
                                <p className="text-white font-medium text-lg mt-1">{data?.model_name || modelName}</p>
                                <div className="flex items-center gap-2 mt-1">
                                    <span className="px-2 py-0.5 bg-gray-800 rounded text-xs text-gray-400 border border-gray-700">
                                        {data?.model_type || modelType || 'Unknown'}
                                    </span>
                                    {data?.model_directory && (
                                        <span className="text-xs text-gray-500">{data.model_directory}</span>
                                    )}
                                </div>
                                <p className="text-xs text-gray-500 mt-2 line-clamp-2">{data?.model_description || 'No description'}</p>
                                {data?.raw_filenames?.length > 0 && (
                                    <p className="text-[10px] text-gray-600 mt-2 font-mono truncate max-w-md" title={data.raw_filenames[0]}>
                                        {data.raw_filenames[0]}
                                    </p>
                                )}
                            </div>
                            <span className="px-2 py-1 bg-yellow-900/40 text-yellow-400 border border-yellow-700/50 rounded text-xs font-medium">
                                Auto-discovered
                            </span>
                        </div>
                    </div>

                    {/* Loading */}
                    {loading && (
                        <div className="flex justify-center items-center py-16">
                            <Loader2 className="animate-spin text-blue-500" size={32} />
                            <span className="ml-3 text-gray-400">Searching CivitAI...</span>
                        </div>
                    )}

                    {/* Error */}
                    {error && !loading && (
                        <div className="bg-red-900/20 border border-red-700/30 rounded-xl p-6 text-center">
                            <AlertCircle className="mx-auto mb-2 text-red-400" size={32} />
                            <p className="text-red-300">Failed to search CivitAI</p>
                            <p className="text-red-400/70 text-sm mt-1">{error}</p>
                        </div>
                    )}

                    {/* Candidates */}
                    {!loading && !error && candidates.length > 0 && (
                        <div>
                            <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">
                                Matching Models ({candidates.length})
                            </h3>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                                {candidates.map((candidate) => {
                                    const cm = candidate.civitai_model;
                                    const isSelected = selectedCivitaiId === cm.id;
                                    const previewUrl = cm.modelVersions?.[0]?.images?.[0]?.url || null;
                                    const isBest = candidate.score >= 100;

                                    return (
                                        <div
                                            key={cm.id}
                                            onClick={() => setSelectedCivitaiId(cm.id)}
                                            className={`group relative bg-gray-800 rounded-xl overflow-hidden border-2 transition-all cursor-pointer ${isSelected
                                                ? 'border-blue-500 ring-2 ring-blue-500/30'
                                                : isBest
                                                    ? 'border-green-700/50 hover:border-green-500'
                                                    : 'border-gray-700 hover:border-gray-500'
                                                }`}
                                        >
                                            {/* Preview */}
                                            <div className="aspect-[2/3] bg-gray-900 relative">
                                                {previewUrl ? (
                                                    <img
                                                        src={previewUrl}
                                                        alt={cm.name}
                                                        className="w-full h-full object-cover"
                                                        loading="lazy"
                                                        onError={(e) => { e.target.style.display = 'none'; }}
                                                    />
                                                ) : (
                                                    <div className="flex items-center justify-center h-full text-gray-600">
                                                        <ImageIcon size={32} className="opacity-30" />
                                                    </div>
                                                )}

                                                {/* Score badge */}
                                                <div className="absolute top-2 right-2">
                                                    <ScoreBadge score={candidate.score_percent || candidate.score} label={candidate.match_label} />
                                                </div>

                                                {/* Selected check */}
                                                {isSelected && (
                                                    <div className="absolute top-2 left-2 bg-blue-500 text-white rounded-full p-1">
                                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                                        </svg>
                                                    </div>
                                                )}

                                                {/* Type badge */}
                                                <div className="absolute bottom-2 left-2 bg-black/60 backdrop-blur text-white text-[10px] px-2 py-0.5 rounded">
                                                    {cm.type}
                                                </div>
                                            </div>

                                            {/* Info */}
                                            <div className="p-3">
                                                <h4 className="text-sm font-semibold text-white line-clamp-1" title={cm.name}>{cm.name}</h4>
                                                <div className="flex items-center gap-3 text-xs text-gray-400 mt-1">
                                                    {cm.stats && (
                                                        <>
                                                            <span className="flex items-center gap-1">
                                                                <Star size={10} className="text-yellow-500" />
                                                                {(cm.stats.thumbsUpCount || 0).toLocaleString()}
                                                            </span>
                                                            <span className="flex items-center gap-1">
                                                                <Download size={10} />
                                                                {(cm.stats.downloadCount || 0).toLocaleString()}
                                                            </span>
                                                        </>
                                                    )}
                                                </div>
                                                {cm.creator?.username && (
                                                    <p className="text-[10px] text-gray-500 mt-1">by {cm.creator.username}</p>
                                                )}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {/* No candidates — allow manual search */}
                    {!loading && !error && candidates.length === 0 && (
                        <div className="bg-gray-800/40 border border-gray-700/50 rounded-xl p-6">
                            <div className="text-center mb-4">
                                <Search className="mx-auto mb-2 text-gray-500" size={28} />
                                <p className="text-gray-300 font-medium">No matches found automatically</p>
                                <p className="text-gray-500 text-sm mt-1">Try searching CivitAI manually:</p>
                            </div>
                            <form onSubmit={handleManualSearch} className="flex gap-2 max-w-xl mx-auto">
                                <input
                                    type="text"
                                    value={manualQuery}
                                    onChange={e => setManualQuery(e.target.value)}
                                    placeholder="Search CivitAI..."
                                    className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-4 py-2.5 text-white text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                                    autoFocus
                                />
                                <button
                                    type="submit"
                                    disabled={searchingManual || !manualQuery.trim()}
                                    className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-5 py-2.5 rounded-lg font-medium text-sm transition-colors flex items-center gap-2"
                                >
                                    {searchingManual ? <Loader2 className="animate-spin" size={16} /> : <Search size={16} />}
                                    Search
                                </button>
                            </form>

                            {/* Manual search results */}
                            {manualResults && manualResults.length > 0 && (
                                <div className="mt-6">
                                    <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">Search Results</h3>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                                        {manualResults.map(cm => {
                                            const isSelected = selectedCivitaiId === cm.id;
                                            const previewUrl = cm.modelVersions?.[0]?.images?.[0]?.url || null;
                                            return (
                                                <div
                                                    key={cm.id}
                                                    onClick={() => setSelectedCivitaiId(cm.id)}
                                                    className={`group relative bg-gray-800 rounded-xl overflow-hidden border-2 transition-all cursor-pointer ${isSelected
                                                        ? 'border-blue-500 ring-2 ring-blue-500/30'
                                                        : 'border-gray-700 hover:border-gray-500'
                                                        }`}
                                                >
                                                    <div className="aspect-[2/3] bg-gray-900 relative">
                                                        {previewUrl ? (
                                                            <img src={previewUrl} alt={cm.name} className="w-full h-full object-cover" loading="lazy"
                                                                onError={(e) => { e.target.style.display = 'none'; }} />
                                                        ) : (
                                                            <div className="flex items-center justify-center h-full text-gray-600"><ImageIcon size={32} className="opacity-30" /></div>
                                                        )}
                                                        {isSelected && (
                                                            <div className="absolute top-2 left-2 bg-blue-500 text-white rounded-full p-1">
                                                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                                                </svg>
                                                            </div>
                                                        )}
                                                        <div className="absolute bottom-2 left-2 bg-black/60 backdrop-blur text-white text-[10px] px-2 py-0.5 rounded">{cm.type}</div>
                                                    </div>
                                                    <div className="p-3">
                                                        <h4 className="text-sm font-semibold text-white line-clamp-1" title={cm.name}>{cm.name}</h4>
                                                        <div className="flex items-center gap-3 text-xs text-gray-400 mt-1">
                                                            <span className="flex items-center gap-1"><Star size={10} className="text-yellow-500" />{(cm.stats?.thumbsUpCount || 0).toLocaleString()}</span>
                                                            <span className="flex items-center gap-1"><Download size={10} />{(cm.stats?.downloadCount || 0).toLocaleString()}</span>
                                                        </div>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}
                            {manualResults && manualResults.length === 0 && !searchingManual && (
                                <p className="text-center text-gray-500 text-sm mt-4">No results found for that query.</p>
                            )}
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="p-6 border-t border-gray-800 flex items-center justify-between">
                    <p className="text-xs text-gray-500">
                        {selectedCivitaiId ? '1 model selected' : 'Select a matching model from CivitAI'}
                    </p>
                    <div className="flex gap-3">
                        <button
                            onClick={onClose}
                            className="px-5 py-2.5 bg-gray-800 hover:bg-gray-700 rounded-xl text-gray-300 text-sm transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handleApply}
                            disabled={!selectedCivitaiId || applying}
                            className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl font-medium text-sm transition-colors flex items-center gap-2"
                        >
                            {applying ? <Loader2 className="animate-spin" size={16} /> : <Wand2 size={16} />}
                            {applying ? 'Applying...' : 'Apply Metadata'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
